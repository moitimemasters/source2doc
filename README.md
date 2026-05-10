# source2doc

Платформа для автоматической генерации, конвертации и публикации технической документации из исходного кода с использованием LLM-агентов.

## Компоненты

Система состоит из нескольких независимых сервисов, взаимодействующих через Redis Streams:

1. **Gateway API** — [core/gateway](./core/gateway)
    - FastAPI-сервис (порт `8003`), единая точка входа для UI и CI/CD.
    - Принимает запросы, резолвит named-presets из `config_presets`, шифрует итоговый конфиг тем же Fernet-ключом и публикует задачи в Redis Streams.
    - Читает готовые документы из PostgreSQL и стримит события воркеров в UI через Server-Sent Events (SSE).
    - Дорогие операции (`POST /api/v1/tasks`, `/api/v1/repos/clone`, `/api/v1/repos/upload`, `/api/v1/admin/*`) защищены admin-cookie (`s2d_admin`), выдаваемой `POST /api/v1/admin/auth/login`.
2. **Workers** — [core/worker](./core/worker)
    - Асинхронные консумеры Redis Streams. Один бинарь, четыре режима запуска:
        - `uv run worker docgen` — AI-генерация документации (Planner → Writer → Critic на Pydantic-AI).
        - `uv run worker repos` — клонирование git-репозиториев / распаковка архивов в S3 + индексация в Qdrant.
        - `uv run worker bundler` — упаковка сгенерированной документации в форматы MkDocs / Nextra / Sphinx и выгрузка архива в S3.
        - `uv run worker codetour` — AI-генерация интерактивных туров по коду.
    - Все воркеры поддерживают exactly-once семантику через consumer groups, heartbeat и crash-recovery.
3. **MVP / DocGen core** — [core/mvp](./core/mvp)
    - Standalone реализация Pydantic-AI агентов (`planner`, `writer`, `critic`) и ingest-пайплайна.
    - Используется воркером `docgen`, но может запускаться и как CLI для отладки.
4. **CodeTour core** — [core/codetour](./core/codetour)
    - Отдельный Pydantic-AI агент, генерирующий пошаговые туры по кодовой базе на основе RAG.
5. **Shared** — [core/shared](./core/shared)
    - Общий пакет для Python-компонентов: конфиги (Pydantic), PostgreSQL (asyncpg), Redis event bus, S3 (aioboto3), structlog + логирование в Redis-стримы.
6. **UI** — [source2docui](./source2docui)
    - Next.js 16 / React 19 приложение. Мультипроектная навигация, просмотрщик документации с рендерингом нашего JSON+Markdown формата, страницы стримов/логов, форма генерации, форма bundle-экспорта, админка репозиториев, просмотрщик Code Tours.
    - Все обращения к Gateway идут через прокси-роуты `/api/gateway/*`.

## Хранилища и инфраструктура

| Компонент | Роль |
|---|---|
| PostgreSQL | `documentation_bundles`, `documentation_index`, `documentation_pages`, `repositories`, `codetours` |
| Redis | Streams для задач (`tasks:docgen`, `tasks:repos`, …), per-generation стримы событий, логи, зашифрованные конфиги |
| Qdrant | Векторный индекс кода для RAG (docgen и codetour) |
| S3 / LocalStack | Хранение репозиториев и готовых bundle-архивов |
| pgAdmin | (опционально, для dev) UI для PostgreSQL |

Задачи и статус генерации — **только в Redis Streams**. PostgreSQL хранит только артефакты (документы, репозитории, туры), отдельных таблиц `generation_tasks` / `generation_steps` больше нет (см. миграцию `migrations/05_drop_task_tracking.sql`).

## Быстрый старт (dev)

Подробное руководство — [QUICKSTART.md](./QUICKSTART.md). Тезисно:

1. Сгенерировать ключ шифрования и создать `.env` из `.env.example`:
    ```bash
    ./generate-encryption-key.sh "my-passphrase"
    cp .env.example .env   # и подставить сгенерированный ENCRYPTION_KEY
    ```
2. Поднять инфраструктуру:
    ```bash
    docker compose up -d   # postgres, redis, qdrant, localstack, pgadmin
    ```
   Если используешь Docker Compose v2 как отдельный бинарь (`docker-compose`, без CLI-плагина), команды с `docker compose ...` нужно заменить на `docker-compose ...`. Все примеры ниже работают идентично в обоих вариантах.

   Миграции применяются автоматически при первом старте PostgreSQL (volume `./migrations:/docker-entrypoint-initdb.d`).
3. Запустить Gateway:
    ```bash
    cd core/gateway && uv sync
    uv run gateway --config config.yaml
    ```
4. Запустить воркеры (каждый в своём терминале):
    ```bash
    cd core/worker && uv sync
    uv run worker repos
    uv run worker docgen
    uv run worker bundler
    uv run worker codetour
    ```
5. Запустить UI:
    ```bash
    cd source2docui
    bun install && bun run dev   # или npm install && npm run dev
    ```

Адреса по умолчанию (локальная разработка): Gateway — `http://localhost:8003`, UI — `http://localhost:3000`, Qdrant Dashboard — `http://localhost:6333/dashboard`, pgAdmin — `http://localhost:5050`.

Когда стек поднят с профилем `app`, единая точка входа — `http://localhost/` (Traefik). См. раздел «Единая точка входа (Traefik)» ниже.


## Настройка конфигурационных файлов для Docker

Перед запуском сервиса в Docker необходимо создать и настроить конфигурационные файлы.

### 1. Генерация encryption key и admin-пароля

```bash
./generate-encryption-key.sh "your-passphrase"
./generate-admin-password.sh
```

Сохраните оба значения. `encryption_key` шифрует и пользовательские LLM-конфиги в Redis, и server-side presets в Postgres — он должен совпадать у gateway и всех воркеров. `admin_password_hash` (bcrypt) кладётся только в gateway-конфиги.

### 2. Создание конфигурационных файлов

Скопируйте примеры конфигурационных файлов:

```bash
cp core/gateway/config.docker.yaml.example core/gateway/config.docker.yaml
cp core/worker/config.docker.yaml.example core/worker/config.docker.yaml
```

Все воркеры (`worker-docgen`, `worker-repos`, `worker-bundler`, `worker-codetour`) монтируют один и тот же `core/worker/config.docker.yaml` — отдельные docgen/codetour-конфиги больше не нужны.

### 3. Настройка конфигурационных файлов

Обновите созданные файлы:

1. **Encryption key**: Замените `YOUR_ENCRYPTION_KEY_HERE` на сгенерированный ключ во всех файлах
2. **PostgreSQL пароль**: Замените `YOUR_PASSWORD_HERE` на `docgen_password` в секции `postgres` во всех файлах
3. **Admin password hash** (только gateway): Подставьте bcrypt-хеш из `generate-admin-password.sh` в `admin_password_hash`. `admin_username` оставьте `admin` или поменяйте по вкусу.

**Важно**: Все конфигурационные файлы должны использовать **один и тот же** encryption key:
- `core/gateway/config.docker.yaml`
- `core/worker/config.docker.yaml`

Разные encryption keys приведут к ошибкам расшифровки конфигураций.

### 4. Проверка конфигурации

Перед запуском убедитесь, что:

1. **Все файлы существуют и являются файлами, а не директориями**:
   ```bash
   ls -la core/gateway/config.docker.yaml
   ls -la core/worker/config.docker.yaml
   ```
   Вывод должен показывать `-rw-r--r--` (файл), а не `drwxr-xr-x` (директория).

2. **Все сервисы используют одинаковый encryption key**:
   ```bash
   grep "encryption_key" core/gateway/config.docker.yaml
   grep "encryption_key" core/worker/config.docker*.yaml
   ```

3. **Пароль PostgreSQL во всех файлах совпадает с docker-compose.yml** (`docgen_password`)

## Запуск всего стека в Docker

В `docker-compose.yml` помимо инфраструктурных сервисов определён профиль `app` со всеми приложениями (`gateway`, `worker-docgen`, `worker-repos`, `worker-bundler`, `worker-codetour`, `ui`). Dockerfile'ы лежат в [deploy/docker](./deploy/docker).

```bash
docker compose --profile app up -d --build
```

Каждый воркер получает свой `WORKER_ID` через переменную окружения (см. [deploy/docker/worker-entrypoint.sh](./deploy/docker/worker-entrypoint.sh)).

### Единая точка входа (Traefik)

Стек `app` поднимает reverse-proxy `traefik:v3.2` на порту `:80`. Это **каноничный URL** для пользователя — `http://localhost/`. Маршрутизация:

| Префикс пути | Куда идёт | Приоритет |
|---|---|---|
| `/api/v1/*` | Gateway (`:8003` внутри сети) | 10 |
| `/` (всё остальное, включая `/wiki`, `/admin`, `/streams`, `/tour`, `/bundles`) | UI (`:3000` внутри сети) | 1 |

SSE (`/api/v1/streams/*/stream`, `/api/v1/logs/*/stream`) проходит через Traefik без буферизации.

Дашборд Traefik (insecure, только для отладки): `http://localhost:8080/`.

Прямые порты `:3001` (UI) и `:8003` (gateway) остаются доступны на host — удобно для разработки, но в обычной работе они не нужны. TLS/HTTPS пока не настроен (pre-prod); под прод стоит включить ACME/Let's Encrypt в Traefik.

## Использование

Сервис работает в **boxed-режиме**: end-user не вводит секретов. Админ один раз настраивает preset (LLM + embeddings + qdrant) через `/admin/presets`, далее любой публичный код-тур или bundle-export использует этот preset на сервере.

### Через UI

1. Залогиниться: `/admin/login` (creds из `core/gateway/config*.yaml`).
2. `/admin/presets` → создать preset, отметить default.
3. `/admin/repos` → загрузить tar.gz или дать git URL.
4. `/admin/generate` → выбрать репо + preset → start.
5. End-user открывает `/wiki/{project}` / `/tour/{tourId}` без логина; кодтур-форма (`Code Tour` floating button) использует default preset.

### Через прямой HTTP / CI

```bash
# 1) залогиниться один раз
curl -c cookie.jar -X POST http://localhost:8003/api/v1/admin/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"..."}'

# 2) создать задачу — preset из config_presets, либо явный override в body
curl -b cookie.jar -X POST http://localhost:8003/api/v1/tasks \
  -H "Content-Type: application/json" \
  -d '{"repo_id":"<uuid>","preset":"production"}'
```

Поля `llm`/`embeddings`/`qdrant` в body перебивают preset поле-за-полем — это путь для CI с собственными credentials. Без admin-cookie на write-routes придёт `401`.

### Прочее

- Прогресс: `GET /api/v1/streams/{generation_id}/stream` (SSE), `/api/v1/logs/{generation_id}/stream` (SSE), страницы `/streams` и `/streams/{id}/logs`.
- Чтение доков: `GET /api/v1/docs/bundles[/{id}/index|/pages/{page_id}]`, или UI `/wiki/{project}/...`.
- Bundle export: `POST /api/v1/bundles/export` (публичный, без LLM), скачивание `GET /api/v1/bundles/exports/download?...`, или UI `/bundles`.
- Code Tour: end-user — `POST /api/v1/codetours` (без LLM-полей в body), admin override — `POST /api/v1/admin/codetours`.

## Что изменилось в boxed-режиме (рефакторинг)

Проект был переведён в **boxed-режим**: end-user не вводит секретов в UI, админ один раз настраивает preset через `/admin/presets`, а CI/прямой HTTP-доступ либо логинится как admin (cookie), либо отправляет полный body c override полями (`llm`, `embeddings`, `qdrant`).

**Изменения:**

- Новые таблицы Postgres: `config_presets` (Fernet-шифрованный JSON {llm, embeddings, qdrant}), `admin_sessions` (sha256 от opaque token + TTL). См. `migrations/07_boxed_mode.sql`.
- Gateway получил admin-cookie auth (bcrypt пароль в `core/gateway/config.yaml`), routes под `/api/v1/admin/{auth,presets,codetours}` гейтятся `Depends(require_admin)`.
- Public read-only routes остались публичными: `/api/v1/codetours`, `/api/v1/bundles/export`, `/api/v1/docs/*`, `/api/v1/streams/*`. Их DTO **не принимает** `llm`/`embeddings`/`qdrant` — gateway резолвит из default preset.
- Resolver `core/gateway/app/routes/_shared/preset_resolver.py` мерджит request-поля с preset поле-за-полем и эмитит 503 если ни тот, ни другой источник не дают LLM/embeddings.
- UI: `/admin/login`, `/admin/presets` (CRUD + YAML upload через `Load YAML`), `/admin/generate`, `/admin/repos` (clone/upload + list/delete). Старая `/generate` страница и `LLMConfigSection` / `EmbeddingsConfigSection` / `YamlUploader` компоненты удалены — раздались только в админке через `PresetEditor`.
- Public codetour-форма (`CodeTourInput`) больше не показывает поля для api_key. `/wiki`, `/tour/[id]`, `/streams`, `/bundles` — без admin-cookie.
- Workers НЕ менялись — payload в Redis (`config:{generation_id}`) идентичен старому формату; encryption ключ тот же.
- Скрипт `./generate-admin-password.sh` для bcrypt-хеша пароля.
- `proxy.ts` (Next.js 16 convention; раньше был бы `middleware.ts`) гейтит `/admin/*` по cookie.

**End-to-end проверка** (preset с реальным Yandex DeepSeek + Qodo embeddings, репо `sindresorhus/is`):

- ✓ Login через UI → cookie + session в Postgres.
- ✓ YAML upload в редактор preset подхватывает реальный API-ключ из локального `config.ui.yaml` (через `FileReader`).
- ✓ Encryption round-trip preset → Postgres → Redis → worker decryption работает с реальным ключом.
- ✓ Real API: `POST .../deepseek-v3-1-terminus/v1/chat/completions` 200 OK, `POST .../embedder-qodo/v1/embeddings` 200 OK, Qdrant ack.
- ✓ Генерация дошла до записи 6/7 страниц в Postgres.
- ✗ 7-я страница упала с `task.failed: Tool 'search_code' exceeded max retries count of 5`. Корневая причина — НЕ в boxed-режиме: `core/mvp/docgen_core/pipeline/ingest.py:74` хардкодит `*.py` (TS-репо → 0 чанков → пустой Qdrant → empty result через `ModelRetry` → exhaustion). Сами 6 «успешных» страниц состоят из извинений «No Python files found» — writer hallucinated Python boilerplate.

Полный анализ найденных багов и пошаговый план починки (multi-language ingest, fail-fast на пустом корпусе, page-isolation вместо kill-task, soft `search_code` empty-result feedback, language-aware writer prompts, UI phase-grid правда про failures, дедуп `task.failed` на DLQ-requeue) — в [docs/fix-prompt-docgen-infallibility.md](./docs/fix-prompt-docgen-infallibility.md).

**Конфиги и секреты:**

Все `config*.yaml` с реальными секретами добавлены в `.gitignore`. Рядом лежат `*.example.yaml` (или `*.yaml.example`) с placeholder-ами — их можно безопасно коммитить и копировать при первом развёртывании.

## Архитектурные документы

- [HOWITWORKS.md](./HOWITWORKS.md) — детальный разбор того, как компоненты взаимодействуют между собой.
- [context.md](./context.md) — проектный контекст и распределение ролей между участниками.
- [core/CODING_GUIDELINES.md](./core/CODING_GUIDELINES.md) — конвенции Python-кода.
- [source2docui/README_MULTI_PROJECT.md](./source2docui/README_MULTI_PROJECT.md) — мультипроектная архитектура UI.
- [source2docui/TOOLTIPS_FEATURE.md](./source2docui/TOOLTIPS_FEATURE.md) — система подсказок в рендерере документации.
- [docs/superpowers/](./docs/superpowers) — design-доки отдельных инициатив (bundler formatter dev process и др.).
