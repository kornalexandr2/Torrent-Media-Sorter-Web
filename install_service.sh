#!/bin/bash

# --- Torrent Media Sorter (Systemd Service Installer) ---
# Устанавливает приложение как системную службу в /opt/torrent-media-sorter-web

set -e

# Функция для запуска команд с sudo, если оно есть и мы не root
run_cmd() {
    if [ "$EUID" -ne 0 ] && [ -x "$(command -v sudo)" ]; then
        sudo "$@"
    else
        "$@"
    fi
}

echo "--------------------------------------------------------"
echo "  ⚙️ Torrent Media Sorter - Service Installer"
echo "--------------------------------------------------------"

INSTALL_DIR="/opt/torrent-media-sorter-web"
REPO_URL="https://github.com/kornalexandr2/Torrent-Media-Sorter-Web.git"
SERVICE_NAME="torrent-media-sorter-web"

# 0. Проверка существующей установки
if [ -x "$(command -v systemctl)" ] && systemctl list-units --full -all | grep -Fq "$SERVICE_NAME.service"; then
    echo "⚠️  Служба $SERVICE_NAME уже установлена."
    read -p "Вы хотите обновить её? (Служба будет остановлена) [y/N]: " UPDATE_CHOICE < /dev/tty
    if [[ ! "$UPDATE_CHOICE" =~ ^[Yy]$ ]]; then
        echo "❌ Установка отменена."
        exit 0
    fi
    echo "🛑 Остановка службы..."
    run_cmd systemctl stop "$SERVICE_NAME" || true
fi

# 1. Установка зависимостей
echo "📦 Установка системных зависимостей (git, python3-venv, lsof)..."
if [ -x "$(command -v apt-get)" ]; then
    run_cmd apt-get update -qq && run_cmd apt-get install -y git python3-venv python3-pip lsof -qq
elif [ -x "$(command -v yum)" ]; then
    run_cmd yum install -y git python3 lsof
fi

# 2. Выбор порта с проверкой
DEFAULT_PORT=7887
APP_PORT=$DEFAULT_PORT

while true; do
    read -p "Введите порт для веб-интерфейса [$APP_PORT]: " INPUT_PORT < /dev/tty
    APP_PORT=${INPUT_PORT:-$APP_PORT}

    echo "🔍 Проверка порта $APP_PORT..."
    if ! lsof -Pi :$APP_PORT -sTCP:LISTEN -t >/dev/null ; then
        echo "✅ Порт $APP_PORT свободен."
        break
    else
        echo "❌ Ошибка: Порт $APP_PORT уже занят другим приложением!"
        APP_PORT=""
        read -p "Пожалуйста, введите другой порт: " APP_PORT < /dev/tty
    fi
done

# 3. Подготовка директории
echo "📂 Подготовка директории $INSTALL_DIR..."
run_cmd mkdir -p "$INSTALL_DIR"

# Копирование файлов или клонирование
if [ -d "$INSTALL_DIR/.git" ]; then
    echo "   Обновление существующего репозитория..."
    cd "$INSTALL_DIR"
    run_cmd git pull
elif [ -f "requirements.txt" ] && [ "$(pwd)" != "$INSTALL_DIR" ]; then
    echo "   Копирование файлов из текущей директории..."
    run_cmd cp -r ./* "$INSTALL_DIR/"
elif [ ! -f "$INSTALL_DIR/requirements.txt" ]; then
    echo "   Клонирование репозитория..."
    # Клонируем во временную папку, чтобы избежать ошибки "directory not empty"
    TMP_DIR=$(mktemp -d)
    git clone "$REPO_URL" "$TMP_DIR"
    run_cmd cp -r "$TMP_DIR"/. "$INSTALL_DIR/"
    rm -rf "$TMP_DIR"
fi

# 4. Настройка Python окружения
echo "🐍 Создание виртуального окружения..."
cd "$INSTALL_DIR"
run_cmd python3 -m venv venv
run_cmd ./venv/bin/pip install -r requirements.txt --quiet

# 5. Настройка прав доступа
REAL_USER=${SUDO_USER:-$(whoami)}
echo "👤 Назначение владельца: $REAL_USER"
run_cmd chown -R "$REAL_USER:$REAL_USER" "$INSTALL_DIR"

# 6. Создание Systemd службы
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
echo "🔧 Создание файла службы $SERVICE_FILE..."

cat <<EOF | run_cmd tee $SERVICE_FILE > /dev/null
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
Environment=APP_PORT=$APP_PORT

[Install]
WantedBy=multi-user.target
EOF

# 7. Запуск
echo "🚀 Запуск службы..."
run_cmd systemctl daemon-reload
run_cmd systemctl enable "$SERVICE_NAME"
run_cmd systemctl restart "$SERVICE_NAME"

# 8. Проверка запуска
echo "🔍 Проверка статуса..."
sleep 2
if run_cmd systemctl is-active --quiet "$SERVICE_NAME"; then
    echo "✅ Служба успешно запущена!"
else
    echo "❌ Ошибка: Служба не смогла запуститься."
    echo "📄 Последние логи (journalctl -u $SERVICE_NAME -n 20):"
    run_cmd journalctl -u "$SERVICE_NAME" -n 20 --no-pager
    exit 1
fi

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
--------------------------------------------------------
