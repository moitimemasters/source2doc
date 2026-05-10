# Coding Guidelines

This document outlines the coding standards and best practices for the `core/` workspace. These guidelines are based on the reference implementations in [`worker/`](worker/) and [`gateway/`](gateway/) packages.

---

## Table of Contents

1. [Import Style](#1-import-style)
2. [No Comments](#2-no-comments)
3. [Typing with Liskov Substitution Principle](#3-typing-with-liskov-substitution-principle)
4. [Prefer Modules over Classes](#4-prefer-modules-over-classes)
5. [Function Decomposition](#5-function-decomposition)
6. [DRY Principle](#6-dry-principle)
7. [Shared Components](#7-shared-components)
8. [Use Libraries](#8-use-libraries)
9. [Return Structured Data](#9-return-structured-data)

---

## 1. Import Style

**Guideline:** Import packages/modules, not names directly. Use convenient acronyms for commonly used modules.

### Standard Acronyms

- `import typing as tp`
- `import dataclasses as dc`
- `import collections.abc as cabc`

### ✅ GOOD Examples

From [`worker/worker/bundler/env.py`](worker/worker/bundler/env.py:1):

```python
import typing as tp

from source2doc.config import S3Config
from source2doc.storage import S3Storage


class BundlerWorkerEnv(tp.Protocol):
    s3_storage: S3Storage
    logger: tp.Any
    _initialized: bool
    _running: bool
```

From [`shared/source2doc/formatter/mdx/env.py`](shared/source2doc/formatter/mdx/env.py:1-2):

```python
from pathlib import Path
import typing as tp


class MDXFormatterEnv(tp.Protocol):
    def get_file_extension(self) -> str: ...
```

From [`worker/worker/bundler/processor.py`](worker/worker/bundler/processor.py:1-9):

```python
from pathlib import Path
import tarfile
import tempfile
from uuid import UUID

from source2doc.config import S3Config
from source2doc.logging import get_logger
from source2doc.models import docs as doc_models
from source2doc.storage import PostgresStorage, S3Storage
```

### ❌ BAD Examples

```python
# DON'T: Import names directly without module context
from typing import Protocol, Any, Dict, List

# DON'T: Mix import styles inconsistently
import typing
from typing import Protocol
```

### Why?

- **Clarity:** Module prefixes make it clear where types/functions come from
- **Consistency:** Standardized acronyms reduce cognitive load
- **Namespace management:** Avoids name collisions and makes refactoring easier

---

## 2. No Comments

**Guideline:** Never write comments for code. Code should be self-documenting through clear naming and structure.

### ✅ GOOD Examples

From [`worker/worker/bundler/processor.py`](worker/worker/bundler/processor.py:63-77):

```python
async def _fetch_bundle_data(
    storage: PostgresStorage,
    generation_id: UUID,
) -> tuple[doc_models.DocIndex, dict[str, doc_models.DocPage]]:
    index = await storage.get_index(generation_id)
    if not index:
        raise ValueError(f"Index not found for generation {generation_id}")

    pages = {}
    for page_id in index.navigation:
        page = await storage.get_page(generation_id, page_id)
        if page:
            pages[page_id] = page

    return index, pages
```

From [`gateway/app/routes/docs/service.py`](gateway/app/routes/docs/service.py:26-30):

```python
async def get_page(storage: PostgresStorage, generation_id: UUID, page_id: str) -> dict:
    page = await storage.get_page(generation_id, page_id)
    if not page:
        raise ResourceNotFoundError(resource_type="page", resource_id=page_id)
    return page.model_dump()
```

### ❌ BAD Examples

```python
# DON'T: Add comments explaining what code does
async def process_data(data: dict) -> dict:
    # Extract the user ID from the data
    user_id = data.get("user_id")

    # Validate that user ID exists
    if not user_id:
        raise ValueError("Missing user ID")

    # Fetch user from database
    user = await db.get_user(user_id)

    # Return user data
    return user.to_dict()
```

### Why?

- **Self-documenting code:** Well-named functions and variables explain intent
- **Maintenance:** Comments become outdated; code doesn't lie
- **Focus:** Forces you to write clearer, more expressive code

---

## 3. Typing with Liskov Substitution Principle

**Guideline:** Accept interfaces (protocols, abstract types) as input parameters. Return concrete types as output.

### Pattern

```python
def function_name(param: AbstractType) -> ConcreteType:
    ...
```

### ✅ GOOD Examples

From [`worker/worker/docgen/service/processor.py`](worker/worker/docgen/service/processor.py:10):

```python
async def process_task(env: DocGenWorkerEnv, task_info: dict):
    # Accepts Protocol (interface) as input
    # Returns nothing (None) - concrete type
    ...
```

From [`shared/source2doc/formatter/mdx/formatter.py`](shared/source2doc/formatter/mdx/formatter.py:9-14):

```python
async def format_bundle(
    env: MDXFormatterEnv,
    index: doc_models.DocIndex,
    pages: dict[str, doc_models.DocPage],
    output_dir: Path,
) -> None:
    # Accepts Protocol (MDXFormatterEnv) and concrete types
    # Returns None (concrete)
    ...
```

From [`gateway/app/routes/docs/service.py`](gateway/app/routes/docs/service.py:9-11):

```python
async def list_bundles(storage: PostgresStorage, limit: int, offset: int) -> list[BundleInfo]:
    bundles_data = await storage.list_bundles(limit=limit, offset=offset)
    return [BundleInfo(**bundle) for bundle in bundles_data]
```

Using `cabc.Iterable` for flexible input:

```python
def process_items(items: cabc.Iterable[str]) -> list[str]:
    return [item.upper() for item in items]
```

### ❌ BAD Examples

```python
# DON'T: Return abstract types
def get_users() -> cabc.Sequence[User]:
    return [User(...), User(...)]  # Caller doesn't know concrete type

# DON'T: Require concrete types when abstract would work
def process_names(names: list[str]) -> None:  # Too restrictive
    for name in names:
        print(name)
```

### Why?

- **Flexibility:** Functions accept any compatible implementation
- **Testability:** Easy to mock interfaces for testing
- **Clarity:** Return types are explicit and predictable
- **LSP compliance:** Follows Liskov Substitution Principle

---

## 4. Prefer Modules over Classes

**Guideline:** Use folders and modules instead of classes when possible. For shared state/parameters, use "env" or "ctx" Protocol objects passed as the first parameter.

### Pattern: Env/Ctx Protocol

Define a Protocol for shared state:

From [`worker/worker/docgen/service/env.py`](worker/worker/docgen/service/env.py:11-23):

```python
class DocGenWorkerEnv(Protocol):
    config: GatewayWorkerConfig
    logger: structlog.stdlib.BoundLogger
    encryption: ConfigEncryption
    redis: aioredis.Redis
    pubsub: Any
    tracker: TaskTracker | None

    _initialized: bool
    _running: bool

    active_workers: dict[str, tuple[Any, Any, Any]]
```

Use it in module functions:

From [`worker/worker/docgen/service/processor.py`](worker/worker/docgen/service/processor.py:10-29):

```python
async def process_task(env: DocGenWorkerEnv, task_info: dict):
    if not env._initialized:
        raise RuntimeError("Worker not initialized")

    if env.redis is None:
        raise RuntimeError("Redis not initialized")

    if env.tracker is None:
        raise RuntimeError("Task tracker not initialized")

    generation_id = UUID(task_info["generation_id"])
    config_key = task_info["config_key"]
    stream_name = task_info.get("stream_name", f"pipeline:{generation_id}")
    qdrant_collection = task_info.get("qdrant_collection")

    env.logger.info(
        "processing_task",
        generation_id=str(generation_id),
        stream_name=stream_name,
    )
    ...
```

### ✅ GOOD Examples

Module-based organization in [`worker/worker/bundler/`](worker/worker/bundler/):

```
bundler/
├── env.py          # Protocol definition
├── processor.py    # Core processing functions
├── templates.py    # Template handling
└── worker.py       # Worker orchestration
```

From [`worker/worker/bundler/processor.py`](worker/worker/bundler/processor.py:21-24):

```python
async def process_bundle_export(
    env: BundlerWorkerEnv,
    task_info: dict,
) -> None:
    # Function accepts env as first parameter (like self)
    ...
```

### ❌ BAD Examples

```python
# DON'T: Use classes when modules would suffice
class BundleProcessor:
    def __init__(self, storage: Storage, logger: Logger):
        self.storage = storage
        self.logger = logger

    def process(self, bundle_id: str) -> None:
        self.logger.info("processing", bundle_id=bundle_id)
        data = self.storage.get(bundle_id)
        self._validate(data)
        self._transform(data)

    def _validate(self, data: dict) -> None:
        ...

    def _transform(self, data: dict) -> None:
        ...
```

Better as modules:

```python
# processor.py
async def process_bundle(env: ProcessorEnv, bundle_id: str) -> None:
    env.logger.info("processing", bundle_id=bundle_id)
    data = await env.storage.get(bundle_id)
    validate_bundle_data(data)
    transform_bundle_data(data)

def validate_bundle_data(data: dict) -> None:
    ...

def transform_bundle_data(data: dict) -> None:
    ...
```

### Why?

- **Modularity:** Functions can be split across multiple files
- **Simplicity:** No class boilerplate, inheritance complexity
- **Testability:** Easy to test individual functions
- **Flexibility:** Can reorganize functions without class constraints

---

## 5. Function Decomposition

**Guideline:** If a function can be decomposed into smaller functions, it should be decomposed.

### ✅ GOOD Examples

From [`worker/worker/bundler/processor.py`](worker/worker/bundler/processor.py:21-60):

```python
async def process_bundle_export(
    env: BundlerWorkerEnv,
    task_info: dict,
) -> None:
    bundle_id = task_info["bundle_id"]
    generation_id = UUID(task_info["generation_id"])
    output_format = task_info["format"]
    s3_config = task_info.get("s3_config")
    postgres_connection_string = task_info["postgres_connection_string"]

    logger.info(
        "processing_bundle_export",
        bundle_id=bundle_id,
        generation_id=str(generation_id),
        format=output_format,
    )

    storage = PostgresStorage(postgres_connection_string)
    await storage.connect()

    try:
        index, pages = await _fetch_bundle_data(storage, generation_id)
        archive_path = await _create_bundle_archive(
            bundle_id,
            output_format,
            index,
            pages,
        )
        s3_key = await _upload_bundle_to_s3(
            env,
            bundle_id,
            output_format,
            archive_path,
            s3_config,
        )

        logger.info("bundle_export_completed", bundle_id=bundle_id, s3_key=s3_key)

    finally:
        await storage.close()
```

Each step is a separate function:

```python
async def _fetch_bundle_data(...) -> tuple[...]:
    ...

async def _create_bundle_archive(...) -> Path:
    ...

async def _upload_bundle_to_s3(...) -> str:
    ...
```

From [`shared/source2doc/formatter/mdx/formatter.py`](shared/source2doc/formatter/mdx/formatter.py:9-24):

```python
async def format_bundle(
    env: MDXFormatterEnv,
    index: doc_models.DocIndex,
    pages: dict[str, doc_models.DocPage],
    output_dir: Path,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    for page_id, page in pages.items():
        content = _format_page(page)
        page_path = output_dir / f"{page_id}{env.get_file_extension()}"
        page_path.write_text(content, encoding="utf-8")

    nav_content = _format_navigation(index.navigation)
    nav_path = output_dir / "navigation.json"
    nav_path.write_text(nav_content, encoding="utf-8")
```

Decomposed into helper functions:

```python
def _format_page(page: doc_models.DocPage) -> str:
    ...

def _format_navigation(navigation: dict) -> str:
    ...
```

### ❌ BAD Examples

```python
# DON'T: Write monolithic functions
async def process_everything(env: Env, data: dict) -> str:
    # Extract data
    bundle_id = data["bundle_id"]
    generation_id = UUID(data["generation_id"])

    # Connect to storage
    storage = PostgresStorage(data["connection_string"])
    await storage.connect()

    # Fetch index
    index = await storage.get_index(generation_id)
    if not index:
        raise ValueError(f"Index not found")

    # Fetch pages
    pages = {}
    for page_id in index.navigation:
        page = await storage.get_page(generation_id, page_id)
        if page:
            pages[page_id] = page

    # Create temp directory
    temp_dir = tempfile.mkdtemp()
    output_dir = Path(temp_dir) / "bundle"
    output_dir.mkdir()

    # Format pages
    for page_id, page in pages.items():
        lines = []
        lines.append(f"# {page.title}")
        lines.append(page.summary)
        for block in page.blocks:
            # ... format blocks
            pass
        content = "\n".join(lines)
        page_path = output_dir / f"{page_id}.md"
        page_path.write_text(content)

    # Create archive
    archive_path = Path(temp_dir) / f"{bundle_id}.tar.gz"
    with tarfile.open(archive_path, "w:gz") as tar:
        tar.add(output_dir, arcname=".")

    # Upload to S3
    async with env.s3_storage.session.client("s3") as s3:
        with open(archive_path, "rb") as f:
            await s3.upload_fileobj(f, env.bucket, f"bundles/{bundle_id}.tar.gz")

    await storage.close()
    return f"bundles/{bundle_id}.tar.gz"
```

### Why?

- **Readability:** Smaller functions are easier to understand
- **Testability:** Each function can be tested independently
- **Reusability:** Decomposed functions can be reused elsewhere
- **Maintainability:** Changes are localized to specific functions

---

## 6. DRY Principle

**Guideline:** Don't Repeat Yourself. Eliminate code duplication by extracting common logic into reusable functions.

### ✅ GOOD Examples

From [`worker/worker/bundler/processor.py`](worker/worker/bundler/processor.py:130-133):

```python
def _get_s3_storage(env: BundlerWorkerEnv, s3_config: dict | None) -> S3Storage:
    if s3_config:
        return S3Storage(S3Config(**s3_config))
    return env.s3_storage
```

This function eliminates duplication of S3 storage initialization logic.

From [`worker/worker/bundler/processor.py`](worker/worker/bundler/processor.py:99-101):

```python
def _create_tarball(source_dir: Path, archive_path: Path) -> None:
    with tarfile.open(archive_path, "w:gz") as tar:
        tar.add(source_dir, arcname=".")
```

Tarball creation logic extracted to a single reusable function.

### ❌ BAD Examples

```python
# DON'T: Duplicate similar logic
async def export_mkdocs_bundle(bundle_id: str, data: dict) -> str:
    temp_dir = tempfile.mkdtemp()
    output_dir = Path(temp_dir) / "bundle"
    output_dir.mkdir()

    # Format as MkDocs
    format_mkdocs(data, output_dir)

    archive_path = Path(temp_dir) / f"{bundle_id}.tar.gz"
    with tarfile.open(archive_path, "w:gz") as tar:
        tar.add(output_dir, arcname=".")

    return await upload_to_s3(archive_path, bundle_id)

async def export_sphinx_bundle(bundle_id: str, data: dict) -> str:
    temp_dir = tempfile.mkdtemp()
    output_dir = Path(temp_dir) / "bundle"
    output_dir.mkdir()

    # Format as Sphinx
    format_sphinx(data, output_dir)

    archive_path = Path(temp_dir) / f"{bundle_id}.tar.gz"
    with tarfile.open(archive_path, "w:gz") as tar:
        tar.add(output_dir, arcname=".")

    return await upload_to_s3(archive_path, bundle_id)
```

Better approach:

```python
async def export_bundle(
    bundle_id: str,
    data: dict,
    formatter: Formatter,
) -> str:
    temp_dir = tempfile.mkdtemp()
    output_dir = Path(temp_dir) / "bundle"
    output_dir.mkdir()

    await formatter.format(data, output_dir)

    archive_path = create_archive(output_dir, bundle_id)
    return await upload_to_s3(archive_path, bundle_id)

def create_archive(source_dir: Path, bundle_id: str) -> Path:
    archive_path = source_dir.parent / f"{bundle_id}.tar.gz"
    with tarfile.open(archive_path, "w:gz") as tar:
        tar.add(source_dir, arcname=".")
    return archive_path
```

### Why?

- **Maintainability:** Changes only need to be made in one place
- **Consistency:** Same logic behaves identically everywhere
- **Reduced bugs:** Fewer copies mean fewer places for bugs to hide

---

## 7. Shared Components

**Guideline:** Place shared components in the separate [`shared/`](shared/) package.

### Structure

```
shared/
└── source2doc/
    ├── config.py
    ├── errors.py
    ├── logging.py
    ├── events/
    │   ├── bus.py
    │   └── redis_bus.py
    ├── formatter/
    │   ├── base.py
    │   ├── mdx/
    │   └── rst/
    ├── models/
    │   ├── chunks.py
    │   ├── docs.py
    │   └── review.py
    └── storage/
        ├── base.py
        ├── postgres.py
        └── s3.py
```

### ✅ GOOD Examples

Shared models used across packages:

From [`worker/worker/bundler/processor.py`](worker/worker/bundler/processor.py:8):

```python
from source2doc.models import docs as doc_models
```

From [`shared/source2doc/formatter/mdx/formatter.py`](shared/source2doc/formatter/mdx/formatter.py:6):

```python
from source2doc.models import docs as doc_models
```

Shared storage implementations:

From [`worker/worker/docgen/service/processor.py`](worker/worker/docgen/service/processor.py:4):

```python
from source2doc.storage import PostgresStorage
```

From [`gateway/app/routes/docs/service.py`](gateway/app/routes/docs/service.py:3):

```python
from source2doc.storage import PostgresStorage
```

### ❌ BAD Examples

```python
# DON'T: Duplicate models in each package
# worker/worker/models/docs.py
class DocPage:
    ...

# gateway/app/models/docs.py
class DocPage:  # Duplicate!
    ...

# DON'T: Copy-paste storage implementations
# worker/worker/storage/postgres.py
class PostgresStorage:
    ...

# gateway/app/storage/postgres.py
class PostgresStorage:  # Duplicate!
    ...
```

### Why?

- **Single source of truth:** Shared code lives in one place
- **Consistency:** All packages use the same implementations
- **Maintainability:** Updates propagate to all consumers
- **Reusability:** Easy to use shared components in new packages

---

## 8. Use Libraries

**Guideline:** Never write solutions that already exist in libraries. Leverage existing, well-tested packages.

### ✅ GOOD Examples

Using standard library and third-party packages:

From [`worker/worker/bundler/processor.py`](worker/worker/bundler/processor.py:1-4):

```python
from pathlib import Path
import tarfile
import tempfile
from uuid import UUID
```

Using established libraries for common tasks:

```python
# Use redis library for Redis operations
import redis.asyncio as aioredis

# Use structlog for structured logging
import structlog

# Use pydantic for data validation
from pydantic import BaseModel, Field

# Use aiobotocore for async S3 operations
from aiobotocore.session import get_session
```

### ❌ BAD Examples

```python
# DON'T: Reimplement UUID generation
def generate_uuid() -> str:
    import random
    import time
    return f"{random.randint(0, 999999)}-{int(time.time())}"

# DON'T: Write custom JSON serialization when json module exists
def dict_to_json(data: dict) -> str:
    result = "{"
    for key, value in data.items():
        result += f'"{key}": "{value}",'
    result = result.rstrip(",") + "}"
    return result

# DON'T: Implement custom path handling
def join_paths(base: str, *parts: str) -> str:
    result = base
    for part in parts:
        if not result.endswith("/"):
            result += "/"
        result += part
    return result

# DON'T: Write custom async Redis client
class CustomRedisClient:
    async def connect(self, host: str, port: int):
        # Custom implementation
        ...
```

### Why?

- **Reliability:** Libraries are battle-tested and maintained
- **Performance:** Optimized implementations
- **Security:** Security patches and updates
- **Time savings:** Focus on business logic, not infrastructure
- **Standards compliance:** Libraries follow best practices and standards

---

## 9. Return Structured Data

**Guideline:** Never return more than one value from a function using tuples. Always create a structured type (dataclass, NamedTuple, or Pydantic model) so that callers can access values by name, not position.

### Problem with Tuples

When returning multiple values as a tuple, callers cannot know the order of values without reading the function implementation or documentation.

### ✅ GOOD Examples

Using dataclass for structured return:

```python
import dataclasses as dc
from pathlib import Path


@dc.dataclass
class FileResult:
    path: Path
    content: str
    size: int


def read_file_with_metadata(filepath: Path) -> FileResult:
    content = filepath.read_text()
    size = filepath.stat().st_size
    return FileResult(
        path=filepath,
        content=content,
        size=size,
    )


result = read_file_with_metadata(Path("example.txt"))
print(result.path)
print(result.content)
print(result.size)
```

Using NamedTuple for immutable results:

```python
import typing as tp


class BundleData(tp.NamedTuple):
    index: dict
    pages: dict[str, dict]
    metadata: dict


def fetch_bundle_data(bundle_id: str) -> BundleData:
    index = get_index(bundle_id)
    pages = get_pages(bundle_id)
    metadata = get_metadata(bundle_id)
    return BundleData(
        index=index,
        pages=pages,
        metadata=metadata,
    )


result = fetch_bundle_data("bundle-123")
print(result.index)
print(result.pages)
print(result.metadata)
```

Using Pydantic model for validation:

```python
from pydantic import BaseModel


class ProcessingResult(BaseModel):
    success: bool
    output_path: str
    errors: list[str]


def process_document(doc_id: str) -> ProcessingResult:
    try:
        output = generate_output(doc_id)
        return ProcessingResult(
            success=True,
            output_path=str(output),
            errors=[],
        )
    except Exception as e:
        return ProcessingResult(
            success=False,
            output_path="",
            errors=[str(e)],
        )


result = process_document("doc-456")
if result.success:
    print(f"Output saved to: {result.output_path}")
else:
    print(f"Errors: {result.errors}")
```

### ❌ BAD Examples

```python
# DON'T: Return tuple - caller doesn't know order
def get_file_info(filepath: str) -> tuple[str, str, int]:
    path = os.path.abspath(filepath)
    content = read_file(filepath)
    size = os.path.getsize(filepath)
    return path, content, size  # Which is which?


# Caller must remember: path, content, size? Or content, path, size?
path, content, size = get_file_info("example.txt")  # Unclear!

# DON'T: Return tuple with many values
def fetch_bundle_data(bundle_id: str) -> tuple[dict, dict, dict, list, str]:
    # Returns: index, pages, metadata, errors, status
    ...
    return index, pages, metadata, errors, status


# Caller must count positions - error-prone!
idx, pgs, meta, errs, status = fetch_bundle_data("bundle-123")

# DON'T: Use positional indexing
def get_user_data(user_id: str) -> tuple[str, str, int]:
    return name, email, age


result = get_user_data("user-123")
print(result[0])  # What is index 0? Name? Email?
print(result[1])  # What is index 1?
```

### Why?

- **Clarity:** Named fields make code self-documenting
- **Type safety:** IDEs can autocomplete field names
- **Refactoring:** Adding/removing fields doesn't break positional unpacking
- **Maintainability:** No need to remember arbitrary ordering
- **Discoverability:** `result.` shows all available fields

---

## Summary

These guidelines ensure:

1. **Consistency:** Uniform code style across the codebase
2. **Maintainability:** Easy to understand and modify
3. **Testability:** Functions and modules are easy to test
4. **Flexibility:** Protocols and interfaces enable loose coupling
5. **Reusability:** Shared components and decomposed functions
6. **Quality:** Leverage proven libraries and eliminate duplication
7. **Clarity:** Structured return types make code self-documenting

When refactoring code, apply these principles systematically to improve code quality and maintainability.
