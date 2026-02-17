#!/bin/bash

# --- Torrent Media Sorter (Auto Installer) ---
# Проверяет зависимости, запрашивает порт и создает docker-compose.yml

set -e

echo "--------------------------------------------------------"
echo "  📦 Torrent Media Sorter (Web) - Установщик"
echo "--------------------------------------------------------"

# 1. Проверка Docker
if ! [ -x "$(command -v docker)" ]; then
  echo "❌ Ошибка: Docker не установлен! Установите Docker и попробуйте снова."
  exit 1
fi

if ! [ -x "$(command -v docker-compose)" ]; then
  echo "⚠️ Ошибка: Docker Compose не найден! Попробуйте установить plugin: sudo apt install docker-compose-plugin"
  # exit 1 (некоторые системы используют 'docker compose' вместо 'docker-compose')
fi

# 2. Выбор порта
DEFAULT_PORT=8080
read -p "Введите порт для веб-интерфейса [$DEFAULT_PORT]: " APP_PORT
APP_PORT=${APP_PORT:-$DEFAULT_PORT}

# 3. Проверка порта на занятость
echo "🔍 Проверка порта $APP_PORT..."
if lsof -Pi :$APP_PORT -sTCP:LISTEN -t >/dev/null ; then
    echo "❌ Ошибка: Порт $APP_PORT уже занят другим приложением!"
    read -p "Попробовать другой порт? (y/n): " RETRY
    if [[ $RETRY =~ ^[Yy]$ ]]; then
        exit 1 # Перезапуск установщика
    else
        exit 1
    fi
fi

# 4. Режим установки
echo "🏗 Выберите режим установки:"
echo "1) Автономный (Только Torrent Media Sorter)"
echo "2) В связке с Transmission (Добавит Transmission в один docker-compose)"
read -p "Ваш выбор [1]: " INSTALL_MODE
INSTALL_MODE=${INSTALL_MODE:-1}

# 5. Создание папок
mkdir -p config
echo "✅ Создана папка ./config для базы данных и настроек."

# 6. Генерация docker-compose.yml
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

if [ "$INSTALL_MODE" -eq "2" ]; then
cat <<EOF >> docker-compose.yml

  transmission:
    image: lscr.io/linuxserver/transmission:latest
    container_name: transmission
    environment:
      - PUID=$(id -u)
      - PGID=$(id -g)
      - TZ=Europe/Moscow
      - USER=admin
      - PASS=admin
    volumes:
      - ./transmission/config:/config
      - /mnt/media:/downloads # Тот же путь, что и у sorter
    ports:
      - 9091:9091
      - 51413:51413
      - 51413:51413/udp
    restart: unless-stopped
EOF
echo "✅ Добавлен сервис Transmission (логин: admin / пароль: admin)."
fi

# 7. Запуск
echo "--------------------------------------------------------"
echo "🚀 Установка завершена!"
echo "Для запуска выполните: docker-compose up -d"
echo "Веб-интерфейс будет доступен по адресу: http://$(hostname -I | awk '{print $1}'):$APP_PORT"
echo "--------------------------------------------------------"
