#!/bin/bash

echo "--------------------------------------------------------"
echo "  📦 Torrent Media Sorter - Мастер установки"
echo "--------------------------------------------------------"
echo "Выберите метод установки:"
echo "1) Docker (Рекомендуется) - Запустит install_docker.sh"
echo "2) Systemd Service (Linux) - Запустит install_service.sh"
echo "--------------------------------------------------------"
read -p "Ваш выбор [1]: " CHOICE
CHOICE=${CHOICE:-1}

if [ "$CHOICE" -eq "1" ]; then
    bash install_docker.sh
else
    sudo bash install_service.sh
fi
