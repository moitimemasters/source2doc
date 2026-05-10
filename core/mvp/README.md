# DocGen Core (`core/mvp`)

Реализация AI-пайплайна генерации документации на Pydantic-AI: ingest → index → plan → write → review → finalize. Используется воркером `docgen` из `core/worker`, но может запускаться и самостоятельно через CLI — для отладки агентов и промптов.

## Установка

```bash
cd core
uv sync   # устанавливает workspace-зависимости, включая docgen_core
```

Для standalone-запуска также нужен доступный Qdrant, Redis и PostgreSQL — проще всего поднять через корневой `docker compose up -d` (инфра-профиль).

## Конфигурация

```bash
cp core/mvp/configs/config.yaml.example core/mvp/configs/config.yaml
```

В `config.yaml` указываются LLM/embeddings-провайдеры, endpoint'ы Qdrant/PostgreSQL/Redis и параметры генерации (`chunk_size`, `search_limit`, `min_citations`, `max_hallucination_retries` и т.п.). Для Yandex Cloud используй `provider: openai-compatible` с соответствующим `base_url` — в `services/llm` есть транспорт, разворачивающий ответ YandexGPT.

Переменные окружения (читаются через `${VAR}` подстановку в YAML):

```bash
export OPENAI_API_KEY=...
# либо YANDEX_API_KEY, OLLAMA_BASE_URL — зависит от провайдера
```

## Запуск напрямую (CLI)

```bash
cd core/mvp
uv run python -m docgen_core.cli generate /path/to/codebase
uv run python -m docgen_core.cli generate /path/to/codebase --config configs/config.yaml
uv run python -m docgen_core.cli generate /path/to/codebase --output docs.json
```

В интеграции с остальной системой запуск обычно идёт через воркер:

```bash
cd core/worker && uv run worker docgen
```

## Структура

```
docgen_core/
├── models/          # Pydantic-модели (DocPage, CodeChunk, Review, PlannerOutput и т.п.)
├── config/          # Загрузка YAML-конфига, схемы
├── services/        # Embeddings-клиенты, Qdrant vectorstore, LLM transport
├── storage/         # Запись документов/логов в PostgreSQL
├── events/          # Event bus поверх Redis Streams
├── pipeline/        # ingest (чанкование кода), index (эмбеддинги → Qdrant)
├── agents/          # Pydantic-AI агенты: planner, writer, critic (+ deps)
├── tools/           # Tools для агентов: list_files, search_code и пр.
├── workers/         # Handlers state-machine (ingest/plan/write/review/finalize)
├── observability.py # structlog + метрики
├── output/          # Сборка финального JSON-артефакта
└── cli.py           # Standalone CLI
```

## Формат результата

JSON со страницами документации:

- `version` — версия формата.
- `snapshot_hash` — хэш снапшота кодовой базы (детектит повторную генерацию на неизменном коде).
- `nodes` — плоский список страниц.
    - `title`, `description`, `blocks[]` — наш кастомный JSON+MD.
    - Каждый блок несёт цитаты (`citations`) со ссылками на файлы и строки кода — основа для Critic-проверок.

При запуске через воркер результат параллельно пишется в PostgreSQL (`documentation_bundles` / `documentation_index` / `documentation_pages`).

## Как шагает state machine

Handlers слушают per-generation Redis-стрим `pipeline:{generation_id}` и эмитят следующий event:

```
generation.requested → ingest.completed → index.completed → plan.created
    → page.write_requested × N → page.written × N
    → Critic: если score/citations плохие — page.revision_requested (обратно на write)
    → page.completed × N → generation.completed
```

Подробный разбор и диаграммы — в [HOWITWORKS.md](../../HOWITWORKS.md#генерация-документации-docgen-pipeline).
