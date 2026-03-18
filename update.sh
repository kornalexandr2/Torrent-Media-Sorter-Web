#!/bin/bash

# Цвета для вывода
GREEN='\03rd[0;32m'
RED='\03rd[0;31m'
YELLOW='\03rd[1;33m'
NC='\03rd[0m' # No Color

echo -e "${GREEN}Начинаем обновление Torrent Media Sorter Web...${NC}"

# Переходим в директорию со скриптом
cd "$(dirname "$0")"

# 1. Получение последних изменений из Git
echo -e "${YELLOW}Получение последних изменений из GitHub...${NC}"
git pull origin main
if [ $? -ne 0 ]; then
    echo -e "${RED}Ошибка при получении изменений из Git.${NC}"
    exit 1
fi

# 2. Обновление зависимостей, если используется виртуальное окружение
if [ -d "venv" ]; then
    echo -e "${YELLOW}Обновление зависимостей Python...${NC}"
    source venv/bin/activate
    pip install -r requirements.txt
    if [ $? -ne 0 ]; then
        echo -e "${RED}Ошибка при установке зависимостей.${NC}"
    fi
else
    echo -e "${YELLOW}Виртуальное окружение 'venv' не найдено. Пропуск обновления зависимостей.${NC}"
fi

# 3. Обновление базы данных (добавление колонки system_media_type, если ее нет)
DB_PATH="data/database.db"
if [ -f "$DB_PATH" ]; then
    echo -e "${YELLOW}Проверка и обновление структуры базы данных...${NC}"
    
    # Python скрипт для безопасного обновления БД
    python3 - <<EOF
import sqlite3
import sys

db_path = "$DB_PATH"
try:
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Получаем информацию о колонках таблицы downloads
    cursor.execute("PRAGMA table_info(downloads)")
    columns = [info[1] for info in cursor.fetchall()]
    
    # Проверяем наличие новой колонки
    if 'system_media_type' not in columns:
        print("Добавление колонки system_media_type в таблицу downloads...")
        cursor.execute("ALTER TABLE downloads ADD COLUMN system_media_type VARCHAR(50)")
        conn.commit()
        print("База данных успешно обновлена.")
    else:
        print("Структура базы данных актуальна.")
        
except Exception as e:
    print(f"Ошибка при обновлении базы данных: {e}", file=sys.stderr)
finally:
    if 'conn' in locals():
        conn.close()
EOF
else:
    echo -e "${YELLOW}Файл базы данных не найден по пути $DB_PATH. Будет создана новая БД при запуске.${NC}"
fi

# 4. Перезапуск сервиса (если используется systemd)
# Проверяем, запущен ли сервис через systemd
if systemctl is-active --quiet torrent-sorter.service 2>/dev/null; then
    echo -e "${YELLOW}Перезапуск сервиса torrent-sorter...${NC}"
    sudo systemctl restart torrent-sorter.service
    if [ $? -eq 0 ]; then
        echo -e "${GREEN}Сервис успешно перезапущен.${NC}"
    else
        echo -e "${RED}Не удалось перезапустить сервис.${NC}"
    fi
else
    # Проверка для Docker
    if [ -f "docker-compose.yml" ] && command -v docker-compose &> /dev/null; then
        echo -e "${YELLOW}Обновление и перезапуск контейнеров Docker...${NC}"
        docker-compose down
        docker-compose build
        docker-compose up -d
        echo -e "${GREEN}Docker контейнеры обновлены и запущены.${NC}"
    else
        echo -e "${YELLOW}Служба torrent-sorter.service не найдена и Docker не используется.${NC}"
        echo -e "${YELLOW}Пожалуйста, перезапустите приложение вручную.${NC}"
    fi
fi

echo -e "${GREEN}Обновление завершено!${NC}"
