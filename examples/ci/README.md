# CI integrations for source2doc

Drop-in CI/CD recipes that drive a deployed source2doc gateway from your own
project's pipeline. Each one performs the same logical sequence:

1. Authenticate against the gateway (`POST /api/v1/admin/auth/login`).
2. Package the working tree as a `.tar.gz` and upload it
   (`POST /api/v1/repos/upload`).
3. Create a documentation generation task
   (`POST /api/v1/tasks`).
4. Poll the per-generation event stream
   (`GET /api/v1/streams/{generation_id}/events`) until a
   `generation.completed` (success) or `generation.failed` /
   `task.failed` / `step.failed` (failure) event appears, with a 30-minute
   timeout and 10s polling cadence.
5. Resolve the bundle id from `GET /api/v1/docs/bundles`.
6. Request a bundle export in the chosen format
   (`POST /api/v1/bundles/export`).
7. Poll `GET /api/v1/bundles/exports?bundle_id=...` until the archive shows
   up in S3, then download it via
   `GET /api/v1/bundles/exports/download?s3_key=...`.
8. Publish the archive as a CI artifact.

Bundle formats supported by the gateway today: `mkdocs`, `nextra`, `sphinx`.

## Files

| File                                  | Where to put it                   | Purpose                                |
| ------------------------------------- | --------------------------------- | -------------------------------------- |
| `../../.github/workflows/source2doc.yml` | `.github/workflows/source2doc.yml` of consumer repo | GitHub Actions workflow             |
| `.gitlab-ci.yml`                      | `.gitlab-ci.yml` of consumer repo | GitLab CI/CD pipeline                  |
| `Jenkinsfile`                         | `Jenkinsfile` of consumer repo    | Declarative Jenkins pipeline           |

## Prerequisites

- A reachable source2doc deployment. The CI runners must be able to make
  HTTPS requests to it.
- An admin account on the gateway. The current gateway only ships
  cookie-based admin auth (`/api/v1/admin/auth/login` returns a session
  cookie); there is no static API token. The CI workflows therefore log in
  with a username/password pair on each run and log out in a `post` /
  `after_script` block.
- A configured **default LLM preset** on the gateway (or a named preset
  passed via `SOURCE2DOC_PRESET`). Per-task LLM configs are encrypted
  server-side using the gateway's master key, so the recommended pattern
  is to mint and store presets through the admin UI / API and have CI
  reference them by name. Do not try to send raw LLM keys from CI.

## GitHub Actions

1. Copy `.github/workflows/source2doc.yml` from this repository into
   `.github/workflows/source2doc.yml` of the consumer repo.
2. Add repository secrets (Settings -> Secrets and variables -> Actions):
   - `SOURCE2DOC_URL`
   - `SOURCE2DOC_USERNAME`
   - `SOURCE2DOC_PASSWORD`
   - `SOURCE2DOC_PRESET` (optional)
3. The workflow runs on `push` to `main`/`master`, on every pull request,
   and on manual `workflow_dispatch` (where you can override pipeline,
   bundle format, and target branch).
4. On success the bundle archive is published as a workflow artifact
   named `source2doc-bundle-<format>` and retained for 14 days.

## GitLab CI/CD

1. Copy `.gitlab-ci.yml` into the root of the consumer repo. If you
   already have one, add the `source2doc:generate` job and the
   `generate-docs` stage to your existing config (or use `include:`).
2. Add CI/CD variables (Settings -> CI/CD -> Variables):
   - `SOURCE2DOC_URL` (Protected, optionally Masked)
   - `SOURCE2DOC_USERNAME` (Protected)
   - `SOURCE2DOC_PASSWORD` (Protected, Masked)
   - `SOURCE2DOC_PRESET` (optional)
   - `BUNDLE_FORMAT` (optional, default `mkdocs`)
3. The job uses `alpine:3.20` and installs `curl`, `jq`, `tar`, `bash`
   on the fly. If you have a hardened runner image, swap the `image:`
   for one of your own.
4. Artifacts are kept for 14 days under
   `source2doc-<format>.tar.gz`.

## Jenkins

1. Create a Pipeline job pointing at `Jenkinsfile`.
2. Add credentials (Manage Jenkins -> Credentials):
   - `source2doc-url` (Secret Text)
   - `source2doc-username` (Secret Text)
   - `source2doc-password` (Secret Text)
   - `source2doc-preset` (optional, Secret Text)
3. The agent must have `bash`, `curl`, `jq`, and `tar` available.
4. The bundle archive is archived via `archiveArtifacts` on success.

## Notes / known limitations

- The `POST /api/v1/repos/upload`, `POST /api/v1/repos/clone`, and
  `POST /api/v1/tasks` endpoints all require admin auth. There is no
  scoped service-account token today, so the CI uses the same credentials
  as a human admin. If you need stricter isolation, generate a dedicated
  CI account, or front the gateway with your own auth proxy.
- If your gateway lives on a private network, run the CI on a self-hosted
  runner that has line-of-sight to it.
- The polling loop uses a 30-minute timeout (`POLL_TIMEOUT_SECONDS=1800`)
  and a 10-second cadence (`POLL_INTERVAL_SECONDS=10`). Tune these for
  larger repositories / slower LLMs.
