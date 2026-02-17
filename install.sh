#!/bin/bash

# Функция для запуска команд с sudo, если оно есть и мы не root
run_cmd() {
    if [ "$EUID" -ne 0 ] && [ -x "$(command -v sudo)" ]; then
        sudo "$@"
    else
        "$@"
    fi
}

echo "--------------------------------------------------------"
echo "  📦 Torrent Media Sorter - Мастер установки"
echo "--------------------------------------------------------"
echo "Выберите метод установки:"
echo "1) Docker (Рекомендуется) - Запустит install_docker.sh"
echo "2) Systemd Service (Linux) - Запустит install_service.sh"
echo "--------------------------------------------------------"
read -p "Ваш выбор [1]: " CHOICE < /dev/tty
CHOICE=${CHOICE:-1}

if [ "$CHOICE" -eq "1" ]; then
    bash install_docker.sh
else
    run_cmd bash install_service.sh
fi
