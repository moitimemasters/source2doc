import fakeredis.aioredis
import pytest

from worker.streams import task_state


@pytest.fixture
async def redis():
    r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    yield r
    await r.aclose()


async def test_get_returns_none_for_unknown_message(redis):
    result = await task_state.get(redis, "tasks:test", "123-0")
    assert result is None


async def test_begin_processing_increments_attempts(redis):
    a1 = await task_state.begin_processing(redis, "tasks:test", "123-0", "w-1", 3600)
    a2 = await task_state.begin_processing(redis, "tasks:test", "123-0", "w-1", 3600)
    assert a1 == 1
    assert a2 == 2


async def test_begin_processing_sets_processing_state(redis):
    await task_state.begin_processing(redis, "tasks:test", "123-0", "w-1", 3600)
    state = await task_state.get(redis, "tasks:test", "123-0")
    assert state is not None
    assert state.status == "processing"
    assert state.worker_id == "w-1"
    assert state.attempts == 1


async def test_mark_done_updates_status(redis):
    await task_state.begin_processing(redis, "tasks:test", "123-0", "w-1", 3600)
    await task_state.mark_done(redis, "tasks:test", "123-0", 3600)
    state = await task_state.get(redis, "tasks:test", "123-0")
    assert state.status == "done"
    assert state.attempts == 1  # preserved


async def test_mark_dlq_updates_status(redis):
    await task_state.begin_processing(redis, "tasks:test", "123-0", "w-1", 3600)
    await task_state.mark_dlq(redis, "tasks:test", "123-0", 3600)
    state = await task_state.get(redis, "tasks:test", "123-0")
    assert state.status == "dlq"


async def test_state_key_is_scoped_per_stream(redis):
    await task_state.begin_processing(redis, "tasks:a", "123-0", "w-1", 3600)
    assert await task_state.get(redis, "tasks:b", "123-0") is None
