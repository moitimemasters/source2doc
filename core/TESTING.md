# Testing

Two suites: fast unit tests (default) + slow e2e tests (opt-in via `-m e2e`).

## Setup

```bash
cd core
uv sync --extra test            # unit suite deps
uv sync --extra test --extra e2e  # + testcontainers, boto3 (for e2e)
```

## Unit suite (~20s, no Docker)

```bash
uv run --extra test pytest          # all 128 tests
uv run --extra test pytest gateway/tests
uv run --extra test pytest worker/tests
uv run --extra test pytest mvp/tests
uv run --extra test pytest codetour/tests
uv run --extra test pytest shared/tests
```

External services stubbed:
- Redis → `fakeredis`
- Postgres / S3 → `unittest.mock.AsyncMock`
- LLM → `pydantic_ai.models.test.TestModel`

## E2E suite (~10s, requires Docker)

Runs against real Postgres 16, Redis 7, LocalStack 3 in containers.

```bash
uv run --extra test --extra e2e pytest gateway/tests/e2e -m e2e
```

Colima users — point testcontainers at the right socket:

```bash
export DOCKER_HOST="unix://$HOME/.colima/default/docker.sock"
export TESTCONTAINERS_RYUK_DISABLED=true
```

Containers boot once per session. Per-test cleanup: `TRUNCATE` tables, `FLUSHDB`, empty S3 bucket.

## Layout

```
core/
├── pytest.ini                       # asyncio_mode=auto, e2e marker, default skip e2e
├── shared/tests/                    # Fernet, DocBlock formatters
├── gateway/tests/
│   ├── routes/                      # FastAPI routes via TestClient + fakeredis
│   └── e2e/                         # testcontainers integration
├── worker/tests/
│   ├── streams/                     # consumer, recovery (multi-worker, XCLAIM)
│   ├── bundler/                     # mkdocs/nextra/sphinx output
│   ├── repos/                       # tar.gz extraction
│   ├── docgen/                      # processor stream prefix
│   └── encryption/                  # Fernet round-trip
├── mvp/tests/
│   ├── workers/                     # decide(), resilient_handler
│   └── agents/                      # planner/writer/critic via TestModel
└── codetour/tests/                  # step validator
```

## Adding a test

1. Pick the right package (`shared` / `gateway` / `worker` / `mvp` / `codetour`).
2. Drop file under `tests/<module>/test_<name>.py`.
3. `async def test_*` works — `asyncio_mode=auto`.
4. Reuse fixtures from nearest `conftest.py`.

## CI hint

```bash
uv run --extra test pytest -q                            # required, fast
uv run --extra test --extra e2e pytest gateway/tests/e2e -m e2e  # nightly / on-demand
```

## Known flakes

`test_upload_route_lands_archive_in_s3` and `test_repository_exists_and_delete_through_gateway` skipped — Colima host port-forward race when LocalStack + Redis testcontainers boot together. Direct `S3Storage` round-trip tests cover the same paths.
