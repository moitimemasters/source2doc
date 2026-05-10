#!/bin/bash

# Простой скрипт для поиска сокета Podman machine
# Использует только команды podman без обхода файловой системы

set -e

# Проверка наличия podman
if ! command -v podman &> /dev/null; then
    echo "❌ Podman не установлен"
    exit 1
fi

# Проверка наличия jq
if ! command -v jq &> /dev/null; then
    echo "❌ jq не установлен. Установите: brew install jq"
    exit 1
fi

echo "🔍 Поиск сокета Podman machine..."
echo ""

# Получаем имя запущенной машины
MACHINE_NAME=$(podman machine list --format json | jq -r '.[] | select(.Running == true) | .Name' | head -1)

if [ -z "$MACHINE_NAME" ]; then
    echo "❌ Нет запущенных Podman машин"
    echo ""
    echo "Доступные машины:"
    podman machine list
    echo ""
    echo "Запустите машину: podman machine start <имя>"
    exit 1
fi

echo "✅ Найдена запущенная машина: $MACHINE_NAME"
echo ""

# Получаем путь к сокету
SOCKET_PATH=$(podman machine inspect "$MACHINE_NAME" | jq -r '.[0].ConnectionInfo.PodmanSocket.Path')

if [ -z "$SOCKET_PATH" ] || [ "$SOCKET_PATH" = "null" ]; then
    echo "❌ Не удалось получить путь к сокету"
    exit 1
fi

# Проверяем существование сокета
if [ ! -S "$SOCKET_PATH" ]; then
    echo "⚠️  Сокет не найден по пути: $SOCKET_PATH"
    exit 1
fi

echo "✅ Сокет найден!"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "📍 Путь к сокету:"
echo "   $SOCKET_PATH"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "💡 Использование:"
echo ""
echo "   Экспорт для Docker-совместимых инструментов:"
echo "   export DOCKER_HOST=unix://$SOCKET_PATH"
echo ""
echo "   Проверка подключения:"
echo "   curl --unix-socket $SOCKET_PATH http://localhost/v1.41/info"
echo ""
