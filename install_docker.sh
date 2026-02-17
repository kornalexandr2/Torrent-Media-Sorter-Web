#!/bin/bash

# --- Torrent Media Sorter (Docker Installer) ---
# Проверяет зависимости, запрашивает порт и создает docker-compose.yml

set -e

echo "--------------------------------------------------------"
echo "  🐳 Torrent Media Sorter - Docker Installer"
echo "--------------------------------------------------------"

# 1. Проверка Docker
if ! [ -x "$(command -v docker)" ]; then
  echo "❌ Ошибка: Docker не установлен! Установите Docker и попробуйте снова."
  exit 1
fi

if ! [ -x "$(command -v docker-compose)" ]; then
  echo "⚠️ Ошибка: Docker Compose не найден! Попробуйте установить plugin: sudo apt install docker-compose-plugin"
fi

if ! [ -x "$(command -v curl)" ]; then
  echo "⚠️  Предупреждение: утилита curl не найдена. Определение внешнего IP будет пропущено."
fi

# Проверка наличия файлов проекта (для запуска через curl)
if [ ! -f "Dockerfile" ]; then
    echo "📥 Файлы проекта не найдены. Скачивание из GitHub..."
    if ! [ -x "$(command -v git)" ]; then
        echo "❌ Ошибка: git не установлен! Установите git для загрузки файлов."
        exit 1
    fi
    # Пытаемся клонировать в текущую папку, если не выйдет - создаем подпапку
    git clone https://github.com/kornalexandr2/Torrent-Media-Sorter-Web.git . 2>/dev/null || \
    (git clone https://github.com/kornalexandr2/Torrent-Media-Sorter-Web.git torrent-media-sorter && cd torrent-media-sorter)
fi

# 2. Выбор порта
DEFAULT_PORT=8080
read -p "Введите порт для веб-интерфейса [$DEFAULT_PORT]: " APP_PORT
APP_PORT=${APP_PORT:-$DEFAULT_PORT}

# 3. Проверка порта на занятость
echo "🔍 Проверка порта $APP_PORT..."
if lsof -Pi :$APP_PORT -sTCP:LISTEN -t >/dev/null ; then
    echo "❌ Ошибка: Порт $APP_PORT уже занят другим приложением!"
    exit 1
fi

# 4. Создание папок
mkdir -p config
echo "✅ Создана папка ./config для базы данных и настроек."

# 5. Генерация docker-compose.yml
cat <<EOF > docker-compose.yml
services:
  media-sorter:
    build: .
    container_name: media_sorter
    restart: unless-stopped
    ports:
      - "$APP_PORT:8080"
    volumes:
      - ./config:/app/config
      - /mnt/media:/mnt/media # Укажите путь к вашей медиатеке
    environment:
      - TZ=Europe/Moscow
      - PUID=$(id -u)
      - PGID=$(id -g)
EOF

# 6. Запуск
echo "--------------------------------------------------------"
echo "🚀 Конфигурация создана!"
echo "Запуск контейнеров..."
docker-compose up -d --build

echo "--------------------------------------------------------"
echo "✅ Установка завершена!"

# Определение IP адресов
LAN_IP=$(hostname -I | awk '{print $1}')
if [ -x "$(command -v curl)" ]; then
    WAN_IP=$(curl -s -m 2 ifconfig.me || echo "Не удалось определить")
else
    WAN_IP="Не удалось определить (нет curl)"
fi

echo "🏠 Локальный адрес:  http://${LAN_IP:-localhost}:$APP_PORT"
echo "🌍 Внешний адрес:    http://$WAN_IP:$APP_PORT (если настроен проброс портов)"
echo "--------------------------------------------------------"