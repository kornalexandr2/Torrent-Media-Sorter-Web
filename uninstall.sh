#!/bin/bash

# --- Torrent Media Sorter (Uninstaller) ---
# Удаляет контейнеры, службу и файлы проекта

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
echo "  🗑️ Torrent Media Sorter - Деинсталляция"
echo "--------------------------------------------------------"

# 1. Подтверждение
read -p "Вы уверены, что хотите ПОЛНОСТЬЮ удалить Torrent Media Sorter? [y/N]: " CONFIRM < /dev/tty
if [[ ! "$CONFIRM" =~ ^[Yy]$ ]]; then
    echo "❌ Удаление отменена."
    exit 0
fi

# 2. Остановка и удаление Docker контейнеров
if [ -f "docker-compose.yml" ]; then
    echo "🐳 Остановка и удаление Docker контейнеров..."
    docker-compose down --rmi local --volumes --remove-orphans || true
fi

# 3. Остановка и удаление Systemd службы
SERVICE_NAME="torrent-media-sorter-web"
if [ -x "$(command -v systemctl)" ] && systemctl list-units --full -all | grep -Fq "$SERVICE_NAME.service"; then
    echo "⚙️ Удаление Systemd службы..."
    run_cmd systemctl stop "$SERVICE_NAME" || true
    run_cmd systemctl disable "$SERVICE_NAME" || true
    run_cmd rm -f "/etc/systemd/system/$SERVICE_NAME.service"
    run_cmd systemctl daemon-reload
fi

# 4. Удаление файлов (с подтверждением)
INSTALL_DIR="/opt/torrent-media-sorter-web"
echo "--------------------------------------------------------"
echo "⚠️  ВНИМАНИЕ: Сейчас будут удалены все файлы приложения,"
echo "включая базу данных и настройки в $INSTALL_DIR"
read -p "Удалить каталог $INSTALL_DIR? [y/N]: " RM_FILES < /dev/tty

if [[ "$RM_FILES" =~ ^[Yy]$ ]]; then
    echo "📂 Удаление файлов..."
    if [ -d "$INSTALL_DIR" ]; then
        run_cmd rm -rf "$INSTALL_DIR"
    fi
    # Если мы запускали скрипт из текущей папки и она не /opt/...
    if [[ "$(pwd)" != "$INSTALL_DIR" ]] && [[ -f "process_torrent.py" ]]; then
        read -p "Удалить файлы проекта из текущей папки ($(pwd))? [y/N]: " RM_CUR < /dev/tty
        if [[ "$RM_CUR" =~ ^[Yy]$ ]]; then
            rm -rf app config venv docker-compose.yml Dockerfile install*.sh readme.md requirements.txt process_torrent.py models.py database.py main.py schemas.py 2>/dev/null || true
        fi
    fi
    echo "✅ Все файлы удалены."
else
    echo "📂 Файлы сохранены в $INSTALL_DIR"
fi

echo "--------------------------------------------------------"
echo "✅ Деинсталляция завершена!"
echo "--------------------------------------------------------"
