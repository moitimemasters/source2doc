"""Direct PostgresStorage tests against a real Postgres container.

This sits below the HTTP layer and verifies the persistence contract the
gateway and worker depend on. PMI-mapping: indirectly all of 6.3.X that
talk about reading bundles, repositories, codetours and pages from
Postgres.
"""

import datetime as dt
import uuid
from typing import Any

import pytest

from source2doc.models import docs as doc_models
from source2doc.storage import PostgresStorage
from source2doc.storage import codetour as codetour_storage


pytestmark = pytest.mark.e2e


@pytest.fixture
async def storage(real_config: Any):
    s = PostgresStorage(real_config.postgres.connection_string)
    await s.connect()
    yield s
    await s.close()


@pytest.fixture
async def ct_storage(real_config: Any):
    s = codetour_storage.CodetourStorage(real_config.postgres.connection_string)
    await s.connect()
    yield s
    await s.close()


async def test_repository_round_trip(storage: PostgresStorage) -> None:
    repo_id = uuid.uuid4()
    await storage.create_repository(
        repo_id=repo_id,
        name="hello",
        source_type="git",
        git_url="https://github.com/x/hello.git",
        git_branch="main",
    )

    repo = await storage.get_repository(repo_id)
    assert repo is not None
    assert repo.name == "hello"
    assert repo.source_type == "git"
    assert repo.git_url == "https://github.com/x/hello.git"

    listing = await storage.list_repositories()
    assert any(r.repo_id == repo_id for r in listing)


async def test_repository_delete_removes_row(storage: PostgresStorage) -> None:
    repo_id = uuid.uuid4()
    await storage.create_repository(
        repo_id=repo_id,
        name="to-delete",
        source_type="git",
        git_url="https://github.com/x/del.git",
    )
    await storage.delete_repository(repo_id)
    assert await storage.get_repository(repo_id) is None


async def test_bundle_index_pages_round_trip(storage: PostgresStorage) -> None:
    repo_id = uuid.uuid4()
    generation_id = uuid.uuid4()
    await storage.create_repository(
        repo_id=repo_id, name="proj", source_type="git", git_url="https://x/x.git"
    )

    bundle_id = await storage.create_bundle(
        generation_id, "proj", name="Docs", description=None, repo_id=repo_id
    )
    assert bundle_id > 0

    index = doc_models.DocIndex.create(navigation={"intro": "Intro", "usage": "Usage"})
    await storage.write_index(bundle_id, index)

    fetched_index = await storage.get_index(generation_id)
    assert fetched_index is not None
    assert "intro" in fetched_index.navigation

    page = doc_models.DocPage(
        title="Intro",
        summary="Welcome",
        metadata=doc_models.PageMetadata(
            generated_at="2026-05-04T00:00:00Z", reading_time=1, tags=[]
        ),
        blocks=[doc_models.ParagraphBlock(text="hi")],
    )
    await storage.write_page(bundle_id, "intro", page)

    got = await storage.get_page(generation_id, "intro")
    assert got is not None
    assert got.title == "Intro"


async def test_page_versions_round_trip(storage: PostgresStorage) -> None:
    """B11.2: ``record_page_version`` → list → get round-trip.

    Two snapshots written for the same ``page_id`` under different
    ``generation_id``s must come back ordered newest-first, and a
    fetch by ``(page_id, generation_id)`` must return the full body
    that was written. Idempotency on the unique key is also verified
    by re-recording the second snapshot with refreshed content.
    """
    page_id = f"versions-page-{uuid.uuid4().hex[:8]}"
    repo_id = uuid.uuid4()
    gen_a = uuid.uuid4()
    gen_b = uuid.uuid4()

    # Need a real repository to satisfy ``repository_id`` FK semantics
    # in case future migrations add the constraint.
    await storage.create_repository(
        repo_id=repo_id,
        name="versioned",
        source_type="git",
        git_url="https://x/v.git",
    )

    body_a = {
        "title": "Older",
        "summary": "Older summary",
        "blocks": [{"type": "paragraph", "text": "Old body"}],
        "related": [],
    }
    await storage.record_page_version(
        page_id=page_id,
        generation_id=gen_a,
        repository_id=repo_id,
        commit_sha="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        body=body_a,
        body_markdown="# Older\n\nOld body\n",
        metadata={"tags": ["v1"]},
    )

    # Slight delay would be ideal for ordering determinism, but the
    # ``created_at`` clock is millisecond-resolution and the second
    # write below comes after a Postgres round-trip — that's enough.
    body_b = {
        "title": "Newer",
        "summary": "Newer summary",
        "blocks": [{"type": "paragraph", "text": "New body"}],
        "related": ["intro"],
    }
    await storage.record_page_version(
        page_id=page_id,
        generation_id=gen_b,
        repository_id=repo_id,
        commit_sha="bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
        body=body_b,
        body_markdown="# Newer\n\nNew body\n",
        metadata={"tags": ["v2"]},
    )

    # Idempotent re-record should refresh the row in place, not duplicate.
    await storage.record_page_version(
        page_id=page_id,
        generation_id=gen_b,
        repository_id=repo_id,
        commit_sha="bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
        body={**body_b, "summary": "Newer summary (revised)"},
        body_markdown="# Newer\n\nNew body (revised)\n",
        metadata={"tags": ["v2", "revised"]},
    )

    versions = await storage.list_page_versions(page_id)
    assert len(versions) == 2
    assert versions[0].generation_id == gen_b
    assert versions[1].generation_id == gen_a
    assert versions[0].commit_sha == "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"

    detail = await storage.get_page_version(page_id, gen_b)
    assert detail is not None
    assert detail.body["title"] == "Newer"
    assert detail.body["summary"] == "Newer summary (revised)"
    assert detail.body["blocks"][0]["text"] == "New body"
    assert detail.body_markdown is not None
    assert "New body (revised)" in detail.body_markdown
    assert detail.metadata == {"tags": ["v2", "revised"]}
    assert detail.commit_sha == "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"

    missing = await storage.get_page_version(page_id, uuid.uuid4())
    assert missing is None


async def test_codetour_pending_get_round_trip(
    ct_storage: codetour_storage.CodetourStorage,
) -> None:
    tour_id = uuid.uuid4()
    generation_id = uuid.uuid4()

    await ct_storage.create_pending_tour(
        tour_id=tour_id,
        generation_id=generation_id,
        request_payload={"query": "how login works", "max_steps": 5},
    )

    tour = await ct_storage.get_codetour(tour_id)
    assert tour is not None
    assert tour["status"] == "pending"
    assert tour["generation_id"] == str(generation_id)


async def test_codetour_list_by_generation(
    ct_storage: codetour_storage.CodetourStorage,
) -> None:
    generation_id = uuid.uuid4()
    other_gen_id = uuid.uuid4()

    await ct_storage.create_pending_tour(
        tour_id=uuid.uuid4(),
        generation_id=generation_id,
        request_payload={"query": "a"},
    )
    await ct_storage.create_pending_tour(
        tour_id=uuid.uuid4(),
        generation_id=generation_id,
        request_payload={"query": "b"},
    )
    await ct_storage.create_pending_tour(
        tour_id=uuid.uuid4(),
        generation_id=other_gen_id,
        request_payload={"query": "c"},
    )

    tours = await ct_storage.list_codetours_by_generation(generation_id)
    assert len(tours) == 2
