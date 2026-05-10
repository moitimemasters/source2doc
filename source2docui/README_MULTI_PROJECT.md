# Multi-Project Documentation Platform

source2docui теперь поддерживает динамическую загрузку документации для нескольких проектов.

## Архитектура

### Основные компоненты

1. **Project Types** (`lib/wiki/project-types.ts`)
   - Zod-схемы для валидации конфигурации проектов
   - Поддержка filesystem и API источников данных

2. **Project Loader** (`lib/wiki/project-loader.ts`)
   - Singleton для загрузки и кеширования конфигурации проектов
   - Методы для получения проекта по ID или дефолтного проекта

3. **Content Source** (`lib/wiki/content-source.ts`)
   - Абстракция для загрузки контента из разных источников
   - `FileSystemContentSource` - загрузка из файловой системы
   - `ApiContentSource` - загрузка через API
   - `ContentSourceFactory` - фабрика для создания источников

4. **Redux Store** (`lib/store/`)
   - Глобальное состояние для управления проектами
   - Slice для проектов с async thunks

5. **UI Components**
   - `ProjectSelectorContainer` - контейнер с логикой
   - `ProjectSelectorView` - презентационный компонент

## Конфигурация проектов

Файл `config/projects.json`:

```json
{
  "projects": [
    {
      "id": "default",
      "name": "Documentation",
      "description": "Main documentation",
      "source": {
        "type": "filesystem",
        "dataPath": "data/wiki",
        "navigationPath": "config/navigation.json"
      }
    }
  ],
  "defaultProject": "default"
}
```

### Типы источников данных

#### Filesystem Source
```json
{
  "type": "filesystem",
  "dataPath": "data/wiki",
  "navigationPath": "config/navigation.json"
}
```

#### API Source
```json
{
  "type": "api",
  "baseUrl": "https://api.example.com",
  "auth": {
    "type": "bearer",
    "token": "your-token"
  },
  "endpoints": {
    "content": "/api/wiki/{slug}",
    "navigation": "/api/navigation"
  }
}
```

## Routing

URL структура: `/wiki/{projectId}/{...contentSlug}`

Примеры:
- `/wiki/default/getting-started` - дефолтный проект
- `/wiki/project-alpha/installation` - проект alpha
- `/wiki/project-beta/api/overview` - вложенная страница

## API Endpoints

- `GET /api/projects` - список всех проектов
- `GET /api/projects/{projectId}` - информация о проекте

## Добавление нового проекта

1. Создайте директорию для данных проекта
2. Добавьте конфигурацию в `config/projects.json`
3. Создайте файлы wiki и navigation.json
4. Проект автоматически появится в селекторе

## Расширение

### Добавление нового типа источника

1. Создайте Zod-схему в `project-types.ts`
2. Реализуйте `ContentSource` интерфейс
3. Добавьте case в `ContentSourceFactory`

### Кастомизация UI

Компоненты разделены на container/view для легкой кастомизации визуальной части без изменения логики.
