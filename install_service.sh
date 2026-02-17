#!/bin/bash

# --- Torrent Media Sorter (Systemd Service Installer) ---
# Устанавливает приложение как системную службу в /opt/torrent-media-sorter-web

set -e

if [ "$EUID" -ne 0 ]; then
  echo "❌ Пожалуйста, запустите этот скрипт с правами root (sudo bash install_service.sh)"
  exit 1
fi

echo "--------------------------------------------------------"
echo "  ⚙️ Torrent Media Sorter - Service Installer"
echo "--------------------------------------------------------"

INSTALL_DIR="/opt/torrent-media-sorter-web"
REPO_URL="https://github.com/kornalexandr2/Torrent-Media-Sorter-Web.git"
SERVICE_NAME="torrent-media-sorter-web"

# 0. Проверка существующей установки
if systemctl list-units --full -all | grep -Fq "$SERVICE_NAME.service"; then
    echo "⚠️  Служба $SERVICE_NAME уже установлена."
    read -p "Вы хотите обновить её? (Служба будет остановлена) [y/N]: " UPDATE_CHOICE
    if [[ ! "$UPDATE_CHOICE" =~ ^[Yy]$ ]]; then
        echo "❌ Установка отменена."
        exit 0
    fi
    echo "🛑 Остановка службы..."
    systemctl stop "$SERVICE_NAME" || true
fi

# 1. Установка зависимостей
echo "📦 Установка системных зависимостей (git, python3-venv, lsof)..."
if [ -x "$(command -v apt-get)" ]; then
    apt-get update -qq && apt-get install -y git python3-venv python3-pip lsof -qq
elif [ -x "$(command -v yum)" ]; then
    yum install -y git python3 lsof
fi

# 2. Выбор порта с проверкой
DEFAULT_PORT=7887
APP_PORT=$DEFAULT_PORT

while true; do
    read -p "Введите порт для веб-интерфейса [$APP_PORT]: " INPUT_PORT
    APP_PORT=${INPUT_PORT:-$APP_PORT}

    echo "🔍 Проверка порта $APP_PORT..."
    if ! lsof -Pi :$APP_PORT -sTCP:LISTEN -t >/dev/null ; then
        echo "✅ Порт $APP_PORT свободен."
        break
    else
        echo "❌ Ошибка: Порт $APP_PORT уже занят другим приложением!"
        APP_PORT=""
        read -p "Пожалуйста, введите другой порт: " APP_PORT
    fi
done

# 3. Подготовка директории
echo "📂 Подготовка директории $INSTALL_DIR..."
mkdir -p "$INSTALL_DIR"

# Копирование файлов (если запущен из репозитория) или клонирование
if [ -f "requirements.txt" ]; then
    echo "   Копирование файлов из текущей директории..."
    cp -r ./* "$INSTALL_DIR/"
elif [ -d "$INSTALL_DIR/.git" ]; then
    echo "   Папка существует. Обновление репозитория (git pull)..."
    cd "$INSTALL_DIR"
    git pull
    cd - > /dev/null
else
    echo "   Клонирование репозитория..."
    git clone "$REPO_URL" "$INSTALL_DIR"
fi

# 4. Настройка Python окружения
echo "🐍 Создание виртуального окружения..."
cd "$INSTALL_DIR"
python3 -m venv venv
./venv/bin/pip install -r requirements.txt --quiet

# 5. Настройка прав доступа
REAL_USER=${SUDO_USER:-$(whoami)}
echo "👤 Назначение владельца: $REAL_USER"
chown -R "$REAL_USER:$REAL_USER" "$INSTALL_DIR"

# 6. Создание Systemd службы
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
echo "🔧 Создание файла службы $SERVICE_FILE..."

cat <<EOF > $SERVICE_FILE
[Unit]
Description=Torrent Media Sorter Web Service
After=network.target

[Service]
User=$REAL_USER
Group=$REAL_USER
WorkingDirectory=$INSTALL_DIR
ExecStart=$INSTALL_DIR/venv/bin/uvicorn app.main:app --host 0.0.0.0 --port $APP_PORT
Restart=always
Environment=PATH=$INSTALL_DIR/venv/bin:/usr/bin:/usr/local/bin

[Install]
WantedBy=multi-user.target
EOF

# 7. Запуск
echo "🚀 Запуск службы..."
systemctl daemon-reload
systemctl enable "$SERVICE_NAME"
systemctl restart "$SERVICE_NAME"

echo "--------------------------------------------------------"
echo "✅ Установка завершена!"

# Определение IP
LAN_IP=$(hostname -I | awk '{print $1}')
if [ -x "$(command -v curl)" ]; then
    WAN_IP=$(curl -s -m 2 ifconfig.me || echo "Не удалось определить")
else
    WAN_IP="Не удалось определить"
fi

echo "🏠 Адрес интерфейса: http://${LAN_IP:-localhost}:$APP_PORT"
echo "📂 Папка установки:  $INSTALL_DIR"
echo "⚙️ Управление:       sudo systemctl [start|stop|restart] $SERVICE_NAME"
echo "📝 Логи:             journalctl -u $SERVICE_NAME -f"
echo "--------------------------------------------------------"
