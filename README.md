# source2doc

LLM-powered documentation generator. Point it at a git repo or a tar.gz, get
a fully-rendered docs site (with navigation, code citations, mermaid diagrams,
optional interactive Code Tours, and exportable MkDocs / Nextra / Sphinx
bundles).

The whole stack runs locally in Docker. End-users never type LLM credentials —
an admin configures one preset once via `/admin/presets`, and everything else
(public reads, public code-tours, public bundle exports) uses it.

---

## Quick start

You need Docker (28+, with Compose v2), plus either `uv` or system `python3`
with `bcrypt` + `cryptography` available (the helper scripts will tell you
which to install).

```bash
git clone <this-repo> source2doc && cd source2doc
./bootstrap.sh                                # writes .env, prints admin password
docker compose --profile app up -d --build
```

That's it. After the stack settles (~30s on first build), open:

| URL | What |
|---|---|
| http://localhost/ | UI (Traefik routes `/api/v1/*` to gateway, everything else to UI) |
| http://localhost/admin/login | Admin login — username `admin`, password printed by `bootstrap.sh` |
| http://localhost:5050 | pgAdmin (`admin@source2doc.local` / `admin`) |
| http://localhost:6333/dashboard | Qdrant dashboard |
| http://localhost:8080 | Traefik dashboard (debug) |

Direct ports `:3001` (UI) and `:8003` (gateway) are also exposed for dev
convenience but the canonical entry point is `:80`.

### First-run flow

1. `/admin/login` with the credentials `bootstrap.sh` printed.
2. `/admin/presets` → create a preset with your LLM + embeddings + Qdrant
   credentials. Mark it default.
3. `/admin/repos` → upload a tar.gz or paste a git URL.
4. `/admin/generate` → pick repo + preset → start.
5. Anyone (no login) can then read `/wiki/<project>`, request Code Tours,
   export MkDocs/Nextra/Sphinx bundles via `/bundles`.

---

## What's in `.env`

`bootstrap.sh` writes three values. That's the entire secret surface:

| Var | Source | Used by |
|---|---|---|
| `ENCRYPTION_KEY` | `./generate-encryption-key.sh` (Fernet, 32 random bytes) | gateway + every worker — encrypts per-task LLM configs in Redis and admin presets in Postgres |
| `ADMIN_PASSWORD_HASH` | `./generate-admin-password.sh <password>` (bcrypt) | gateway login |
| `POSTGRES_PASSWORD` | bootstrap default (`docgen_password`) | postgres container + gateway/worker config |

`config.docker.yaml` in `core/gateway/` and `core/worker/` is committed,
references those three values via `${VAR}` substitution at load time, and
otherwise hardcodes the Docker service DNS (`postgres`, `redis`, `qdrant`,
`localstack`). Nothing else should need to be touched for a fresh setup.

### Re-bootstrapping

```bash
docker compose --profile app down -v        # nuke containers + volumes
rm .env
./bootstrap.sh
docker compose --profile app up -d --build
```

### Custom admin password

```bash
ADMIN_PASSWORD="my-real-password" ./bootstrap.sh
```

---

## Stack layout

| Path | What |
|---|---|
| [core/gateway](./core/gateway) | FastAPI on `:8003`. Single ingress to UI + CI. Issues admin cookies, publishes Redis Stream tasks, streams worker events back via SSE. |
| [core/worker](./core/worker) | One binary, four modes: `docgen` (Planner→Writer→Critic on Pydantic-AI), `repos` (git clone / tar.gz unpack → S3 + Qdrant index), `bundler` (export to MkDocs/Nextra/Sphinx), `codetour` (interactive RAG-based tours). |
| [core/mvp](./core/mvp) | DocGen pipeline + Pydantic-AI agents. CLI usage in [core/mvp/README.md](./core/mvp/README.md). |
| [core/codetour](./core/codetour) | Code-tour generation agent. |
| [core/shared](./core/shared) | Shared Pydantic config models, asyncpg, Redis bus, aioboto3, structlog. |
| [source2docui](./source2docui) | Next.js 16 / React 19 UI. |

Storage: PostgreSQL (docs + presets + admin sessions), Redis (task streams,
per-generation event streams, logs, encrypted LLM-config envelopes), Qdrant
(code chunks for RAG), S3/LocalStack (repos + bundle archives).

---

## CI / direct HTTP

```bash
# 1) log in once
curl -c cookie.jar -X POST http://localhost/api/v1/admin/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"<password>"}'

# 2) submit a generation task (preset by name)
curl -b cookie.jar -X POST http://localhost/api/v1/tasks \
  -H "Content-Type: application/json" \
  -d '{"repo_id":"<uuid>","preset":"default"}'
```

Public reads need no cookie: `/api/v1/docs/*`, `/api/v1/bundles/export`,
`/api/v1/codetours`, `/api/v1/streams/*`. CI flows that need to bring their
own LLM key can POST `llm`/`embeddings`/`qdrant` in the body — that overrides
the preset field-by-field.

---

## Developer references

- [core/CODING_GUIDELINES.md](./core/CODING_GUIDELINES.md) — Python conventions.
- [core/TESTING.md](./core/TESTING.md) — running the Python test suite.
- [source2docui/TESTING.md](./source2docui/TESTING.md) — UI / Playwright tests.
- [core/mvp/README.md](./core/mvp/README.md) — standalone DocGen CLI.
- [examples/ci/README.md](./examples/ci/README.md) — CI recipes (GitHub Actions, GitLab CI).

---

## Troubleshooting

**`docker compose up` fails with `ENCRYPTION_KEY` empty.** You skipped
`./bootstrap.sh`. Run it.

**Gateway logs `Encryption key is not a valid Fernet key`.** You hand-edited
`.env` and pasted something that isn't 32 url-safe-base64 bytes. Re-generate
with `./generate-encryption-key.sh > /tmp/k && sed -i '' "s|ENCRYPTION_KEY=.*|ENCRYPTION_KEY=$(cat /tmp/k)|" .env`
or just `rm .env && ./bootstrap.sh`.

**Admin login returns 401.** The bcrypt hash in `.env` doesn't match the
password you're typing. Generate a new one: `./generate-admin-password.sh
"<new password>"` → paste into `.env` under `ADMIN_PASSWORD_HASH=` →
`docker compose restart gateway`.

**LocalStack S3 bucket missing.** `localstack-init/init.sh` runs on first
container start. If you re-created the container without volumes, the bucket
is recreated automatically; if you mounted an old volume, run
`docker compose down -v` and bring it back up.
