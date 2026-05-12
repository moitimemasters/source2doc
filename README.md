# source2doc

LLM-генератор технической документации по исходному коду. Скармливаешь git-URL
или tar.gz архив — получаешь полностью свёрстанный сайт документации с
навигацией, цитатами в коде, mermaid-диаграммами, опциональными интерактивными
Code Tours и экспортом в MkDocs / Nextra / Sphinx.

Весь стек поднимается локально в Docker. Конечные пользователи **не вводят
LLM-креды** — админ один раз создаёт preset в `/admin/presets`, и всё
остальное (публичное чтение wiki, code tours, экспорт bundle-ов) использует
этот preset.

---

## Быстрый старт

Нужно: Docker (28+, с Compose v2) и либо `uv`, либо системный `python3` с
`bcrypt` + `cryptography` (helper-скрипты подскажут, если чего-то не хватает).

```bash
git clone <repo> source2doc && cd source2doc
./bootstrap.sh
docker compose --profile app up -d --build
```

`bootstrap.sh` создаст `.env` со случайным Fernet-ключом и bcrypt-хешем
случайного админ-пароля, и **один раз** распечатает пароль в консоль —
сохрани его сразу.

Через 30–60 секунд после первого `up -d --build` стек готов. Открывай:

| URL | Что |
|---|---|
| http://localhost/ | Главная (Traefik: `/api/v1/*` → gateway, всё остальное → UI) |
| http://localhost/admin/login | Логин — `admin` + пароль из вывода bootstrap.sh |
| http://localhost:5050 | pgAdmin (`admin@source2doc.local` / `admin`) |
| http://localhost:6333/dashboard | Qdrant dashboard |
| http://localhost:8080 | Traefik dashboard (debug-only) |

Прямые порты `:3001` (UI) и `:8003` (gateway) тоже открыты для отладки, но
каноничная точка входа — `:80`.

### Свой пароль вместо случайного

```bash
ADMIN_PASSWORD="моё-секретное-слово" ./bootstrap.sh
```

### Пересоздать с нуля

```bash
docker compose --profile app down -v   # снести контейнеры + тома
rm .env
./bootstrap.sh
docker compose --profile app up -d --build
```

---

## Первый сценарий

1. `/admin/login` — логинимся.
2. `/admin/presets` → создаём preset с твоими LLM + embeddings + Qdrant
   кредами, отмечаем default.
3. `/admin/repos` → загружаем tar.gz или вставляем git URL.
4. `/admin/generate` → выбираем репо + preset → старт.
5. Без логина: `/wiki/<project>` для чтения, `/bundles` для экспорта,
   floating `Code Tour`-кнопка для интерактивных туров.

CI/прямой HTTP-доступ — см. раздел [HTTP API](#http-api) ниже.

---

## Что в `.env`

`bootstrap.sh` пишет ровно три переменные — всё, что вообще нужно для запуска:

| Переменная | Источник | Используют |
|---|---|---|
| `ENCRYPTION_KEY` | `./generate-encryption-key.sh` (`Fernet.generate_key()`, 32 случайных байта в url-safe base64) | gateway + все воркеры. Шифрует per-task LLM-конфиги в Redis и admin-presets в Postgres. **Должен совпадать** во всех сервисах — иначе воркер не расшифрует payload от gateway. |
| `ADMIN_PASSWORD_HASH` | `./generate-admin-password.sh <пароль>` (bcrypt) | только gateway. Сравнивается с тем, что вводят на `/admin/login`. |
| `POSTGRES_PASSWORD` | по умолчанию `docgen_password` | postgres-контейнер + gateway/worker (через `${POSTGRES_PASSWORD}` в `core/*/config.docker.yaml`). |

`core/gateway/config.docker.yaml` и `core/worker/config.docker.yaml`
закоммичены в репозиторий, ссылаются на эти три значения через `${...}` и
**жёстко хардкодят** Docker DNS-имена (`postgres`, `redis`, `qdrant`,
`localstack`). Для свежего clone больше **ничего трогать не надо**.

> `bootstrap.sh` дублирует `$` в bcrypt-хеше как `$$` — это обязательно: Docker
> Compose интерполирует `$<имя>` в `env_file` и без эскейпа сжирает части хеша.
> Поэтому хеш в `.env` выглядит как `$$2b$$12$$...`, а внутри контейнера
> приходит уже как `$2b$12$...`.

---

## Стек

| Путь | Что |
|---|---|
| [core/gateway](./core/gateway) | FastAPI на `:8003`. Единая точка входа для UI и CI. Выдаёт admin-cookie, публикует задачи в Redis Streams, стримит события воркеров обратно через SSE. |
| [core/worker](./core/worker) | Один бинарь, четыре режима: `docgen` (Planner → Writer → Critic на Pydantic-AI), `repos` (git clone / распаковка tar.gz → S3 + индексация в Qdrant), `bundler` (MkDocs / Nextra / Sphinx), `codetour` (RAG-туры по коду). |
| [core/mvp](./core/mvp) | DocGen-пайплайн + Pydantic-AI агенты. Standalone-CLI — см. [core/mvp/README.md](./core/mvp/README.md). |
| [core/codetour](./core/codetour) | Code-tour агент. |
| [core/shared](./core/shared) | Pydantic-модели конфигов, asyncpg, Redis bus, aioboto3, structlog. |
| [source2docui](./source2docui) | UI на Next.js 16 / React 19. |

Хранилища:

- **PostgreSQL** — `documentation_bundles`, `documentation_index`,
  `documentation_pages`, `repositories`, `codetours`, `config_presets`
  (Fernet-зашифрованный JSON), `admin_sessions`.
- **Redis** — Streams для задач (`tasks:docgen`, `tasks:repos`, …),
  per-generation event-streams, логи, зашифрованные LLM-конфиги.
- **Qdrant** — векторный индекс кода для RAG.
- **S3 (LocalStack)** — оригиналы репозиториев и собранные bundle-архивы.

Задачи и статус генерации — **только в Redis Streams**. Postgres хранит
артефакты (документы, репозитории, туры).

---

## HTTP API

```bash
# 1) логин (один раз, кладёт cookie в jar)
curl -c cookie.jar -X POST http://localhost/api/v1/admin/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"<пароль из bootstrap.sh>"}'

# 2) поставить задачу — по имени preset
curl -b cookie.jar -X POST http://localhost/api/v1/tasks \
  -H "Content-Type: application/json" \
  -d '{"repo_id":"<uuid>","preset":"default"}'

# 3) стрим прогресса (SSE)
curl -N -b cookie.jar http://localhost/api/v1/streams/<generation_id>/stream
```

Публичные read-only роуты — без cookie: `/api/v1/docs/*`,
`/api/v1/bundles/export`, `/api/v1/codetours`, `/api/v1/streams/*`. CI с
собственными ключами может слать `llm` / `embeddings` / `qdrant` прямо в
body — это поле-за-полем перекрывает preset.

---

## Документы для разработчиков

- [core/CODING_GUIDELINES.md](./core/CODING_GUIDELINES.md) — Python-конвенции.
- [core/TESTING.md](./core/TESTING.md) — запуск Python-тестов.
- [source2docui/TESTING.md](./source2docui/TESTING.md) — UI/Playwright-тесты.
- [core/mvp/README.md](./core/mvp/README.md) — standalone DocGen CLI.
- [examples/ci/README.md](./examples/ci/README.md) — рецепты CI (GitHub Actions, GitLab CI).

---

## Troubleshooting

**`docker compose up` падает на старте gateway с
`pydantic.ValidationError: encryption_key field required`.** `.env` пустой
или `${ENCRYPTION_KEY}` не пробросился. Проверь:
```bash
docker compose --profile app config | grep ENCRYPTION_KEY
```
Должно быть непустое значение. Если нет — `rm .env && ./bootstrap.sh`.

**Gateway пишет `Encryption key is not a valid Fernet key`.** Кто-то
руками поправил `.env` и вставил не-url-safe-base64. Перегенерируй:
```bash
rm .env && ./bootstrap.sh
docker compose --profile app up -d --force-recreate gateway worker-docgen worker-repos worker-bundler worker-codetour
```

**Admin login возвращает 401.** Bcrypt-хеш в `.env` не от того пароля,
который ты вводишь. Сгенери новый:
```bash
NEW_HASH=$(./generate-admin-password.sh "новый-пароль")
NEW_HASH_ESC=${NEW_HASH//\$/\$\$}    # удвоить $ для compose
sed -i '' "s|^ADMIN_PASSWORD_HASH=.*|ADMIN_PASSWORD_HASH=$NEW_HASH_ESC|" .env
docker compose restart gateway
```

**Worker не может расшифровать payload от gateway (`InvalidToken`).**
`ENCRYPTION_KEY` в `.env` поменялся, но gateway или воркер остались на
старом значении. `docker compose --profile app up -d --force-recreate`.

**Bucket LocalStack отсутствует.** `localstack-init/init.sh` создаёт
бакет при первом старте контейнера. Если ты переподключил старый
named-volume, бакет может потеряться. Лечится:
```bash
docker compose --profile app down -v
docker compose --profile app up -d --build
```

**Порт 80 уже занят.** Скорее всего, локальный nginx/Apache/Caddy. Либо
выключи их (`sudo brew services stop nginx` и т. п.), либо поменяй
порт-маппинг Traefik в `docker-compose.yml` (`"80:80"` → `"8000:80"`) и
открывай `http://localhost:8000/`.

---

## Лицензия и контрибьюшен

PR welcome. Перед PR прогоняй `ruff` / `mypy` (см. `core/CODING_GUIDELINES.md`)
и UI-тесты (см. `source2docui/TESTING.md`).
