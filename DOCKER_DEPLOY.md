# Инструкция по развертыванию через Docker (Torrent Media Sorter Web)

Использование Docker позволяет запустить систему и торрент-клиент в единой связке за несколько минут.

## 1. Подготовка
Убедитесь, что у вас установлены `docker` и `docker-compose`.

## 2. Структура проекта
Создайте рабочую директорию, например `media-center`:
```bash
mkdir ~/media-center && cd ~/media-center
mkdir -p config
```

## 3. Конфигурационный файл (docker-compose.yml)
Создайте файл `docker-compose.yml` со следующим содержимым.

```yaml
services:
  media-sorter:
    build: .
    container_name: media_sorter
    restart: unless-stopped
    ports:
      - "8080:8080"
    volumes:
      - ./config:/app/config           # База данных и настройки
      - /mnt/media:/mnt/media          # Общая папка с фильмами (должна совпадать с клиентом)
    environment:
      - TZ=Europe/Moscow
      - PUID=1000
      - PGID=1000
```

## 4. Запуск
Выполните команду:
```bash
docker-compose up -d --build
```

## 5. Настройка Webhook в торрент-клиенте
Поскольку Sorter и торрент-клиент могут находиться в разных контейнерах или на разных серверах, взаимодействие происходит через HTTP-запросы.

### Transmission
В настройках Transmission включите вызов скрипта по завершении. Создайте скрипт (например, `/config/notify.sh`) внутри контейнера клиента:
```bash
#!/bin/bash
curl -X POST http://IP_ВАШЕГО_СЕРВЕРА:8080/api/webhook \
     -H "Content-Type: application/json" \
     -d "{\"torrent_name\": \"$TR_TORRENT_NAME\", \"torrent_dir\": \"$TR_TORRENT_DIR\"}"
```

### qBittorrent
В настройках "Выполнить внешнюю программу при завершении" используйте cURL:
```bash
curl -X POST http://IP_ВАШЕГО_СЕРВЕРА:8080/api/webhook -H "Content-Type: application/json" -d '{"torrent_name": "%N", "torrent_dir": "%D"}'
```

## 6. Важные замечания по путям
Чтобы всё работало корректно:
- Путь, куда клиент качает файлы (в примере `/mnt/media`), должен быть примонтирован в оба контейнера.
- В настройках Sorter (`config.ini` или через веб-интерфейс) пути `movies_folder` и `series_folder` должны указывать на подпапки внутри того же монтирования (например, `/mnt/media/Movies`).
