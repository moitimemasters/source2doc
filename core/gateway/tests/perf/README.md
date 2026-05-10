# Gateway latency benchmarks

PMI-mapping: ТЗ **СКН-01** (status query latency `<1s`) and **СКН-02**
(SSE push delivery latency `<1s`).

These tests fire concurrent traffic against the in-process FastAPI app
(with `fakeredis` in place of real Redis) and assert that p50/p95
latencies stay within budget. They're slower than the regular test
suite (10–30 s end-to-end), so they're marked `@pytest.mark.perf` and
excluded from default `pytest` runs.

## Running

```bash
cd core/gateway
uv run pytest tests/perf/ -m perf -v
```

The default `pytest tests/` invocation skips this folder (it's not in the
default discovery roots used by CI), but if you want to be explicit add
`--ignore=tests/perf` to your `pytest` command.

## Sample sizes

| File                       | Workload                                        |
|----------------------------|-------------------------------------------------|
| `test_status_latency.py`   | 100 concurrent `GET /streams/{id}/events` calls |
| `test_status_latency.py`   | 100 concurrent `GET /streams` calls (10 streams seeded) |
| `test_sse_push_latency.py` | 10 SSE streams x 50 events each (sequential)    |

## Budgets

| Metric         | Budget    |
|----------------|-----------|
| status p50     | < 200 ms  |
| status p95     | < 1000 ms |
| SSE-push p95   | < 1000 ms |

## Caveats

* Backend is `fakeredis` (in-process), not real Redis — these benchmarks
  measure gateway code-path overhead, not network or Redis I/O. A
  real-stack benchmark needs a separate harness (likely in
  `tests/e2e/` with `testcontainers`).
* Postgres / Qdrant / S3 are stubbed with `AsyncMock`; the streams /
  SSE endpoints don't depend on them, so this is sufficient for СКН-01
  and СКН-02.
