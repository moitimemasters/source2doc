# source2doc

LLM-генератор технической документации по исходному коду.

## Функционал

source2doc принимает git-URL или tar.gz, прогоняет код через LLM-пайплайн
и публикует свёрстанную документацию с
mermaid-диаграммами, RAG-цитатами в коде, интерактивными Code Tours и
экспортом в MkDocs / Nextra / Sphinx.

source2doc состоит из нескольких компонентов:

- **Gateway**, `core/gateway`:
    - FastAPI на `:8003`.
    - Принимает HTTP-запросы от UI и CI.
    - Шифрует preset-конфиги (Fernet), кладёт задачи в Redis Streams.
    - Стримит события воркеров обратно через SSE.
- **Workers**, `core/worker`:
    - Один бинарь, четыре режима: `docgen`, `repos`, `bundler`, `codetour`.
    - Консумят Redis Streams через consumer groups (exactly-once).
- **UI**, `source2docui`:
    - Next.js 16 / React 19.
    - `/admin/*` для конфигурации, `/wiki/*` и `/bundles` — публичные.
- **Core**, `core/shared`, `core/mvp`, `core/codetour`:
    - Pydantic-модели конфигов, Redis bus, Pydantic-AI агенты, RAG-пайплайн.

## Установка

1. Сгенерировать `.env` со случайным Fernet-ключом и bcrypt-хешем
   случайного админ-пароля:

    ```
    $ ./bootstrap.sh
    Generating encryption key...
    Hashing admin password...
    ============================================================
    .env generated.

    Admin login:
      username: admin
      password: 7kQp8RvZ2nMxY4Lf

    SAVE THIS PASSWORD NOW — it is not stored anywhere else.
    ============================================================
    ```

2. Поднять стек:
    ```
    $ docker compose --profile app up -d --build
    ```
    Миграции применятся автоматически.
3. Открыть `http://localhost/` и залогиниться на `/admin/login`.

Свой пароль вместо случайного:

```
$ ADMIN_PASSWORD="my-password" ./bootstrap.sh
```

## Использование

1. Залогиниться на `/admin/login`.
2. Создать preset на `/admin/presets` — LLM, embeddings, Qdrant. Отметить
   default.
3. Загрузить репозиторий на `/admin/repos` — git URL или tar.gz.
4. Запустить генерацию на `/admin/generate` — выбрать репо + preset.
5. Читать на `/wiki/<project>`, экспортировать на `/bundles`,
   генерить Code Tour через floating-кнопку.

Через HTTP:

```
$ curl -c jar -X POST http://localhost/api/v1/admin/auth/login \
    -H 'Content-Type: application/json' \
    -d '{"username":"admin","password":"..."}'

$ curl -b jar -X POST http://localhost/api/v1/tasks \
    -H 'Content-Type: application/json' \
    -d '{"repo_id":"<uuid>","preset":"default"}'

$ curl -N -b jar http://localhost/api/v1/streams/<gen_id>/stream
```

Публичные read-only роуты — без cookie: `/api/v1/docs/*`,
`/api/v1/bundles/export`, `/api/v1/codetours`, `/api/v1/streams/*`.

## Конфигурация

`./bootstrap.sh` пишет три переменные в `.env`:

- `ENCRYPTION_KEY` — Fernet, общий для gateway и воркеров.
- `ADMIN_PASSWORD_HASH` — bcrypt-хеш админ-пароля (gateway).
- `POSTGRES_PASSWORD` — пароль БД.

`core/gateway/config.docker.yaml` и `core/worker/config.docker.yaml`
закоммичены, ссылаются на эти три значения через `${...}`. Больше ничего
менять не нужно.

Доступные адреса:

- `http://localhost/` — UI + Gateway (через Traefik).
- `http://localhost:3001` — UI напрямую.
- `http://localhost:8003` — Gateway напрямую.
- `http://localhost:5050` — pgAdmin (`admin@source2doc.local` / `admin`).
- `http://localhost:6333/dashboard` — Qdrant dashboard.
- `http://localhost:8080` — Traefik dashboard.

## Пересоздать с нуля

```
$ docker compose --profile app down -v
$ rm .env
$ ./bootstrap.sh
$ docker compose --profile app up -d --build
```
