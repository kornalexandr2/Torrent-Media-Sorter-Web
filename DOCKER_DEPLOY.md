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
Создайте файл `docker-compose.yml` со следующим содержимым. Этот пример включает и Sorter, и Transmission в одной сети.

```yaml
version: '3.8'

services:
  # Наш сервис сортировщика
  media-sorter:
    image: alexandrkisa/media-sorter:latest # Пример названия образа
    container_name: media_sorter
    restart: unless-stopped
    ports:
      - "8080:8080"
    volumes:
      - ./config:/app/config           # База данных и настройки
      - /mnt/media:/mnt/media         # Общая папка с фильмами (должна совпадать с клиентом)
    environment:
      - TZ=Europe/Moscow
      - PUID=1000 # ID вашего пользователя в Linux
      - PGID=1000
      - CONFIG_PATH=/app/config/config.ini

  # Торрент-клиент (Пример: Transmission)
  transmission:
    image: lscr.io/linuxserver/transmission:latest
    container_name: transmission
    restart: unless-stopped
    ports:
      - "9091:9091" # Веб-интерфейс
    environment:
      - PUID=1000
      - PGID=1000
      - TZ=Europe/Moscow
    volumes:
      - ./transmission-config:/config
      - /mnt/media:/downloads # Загрузки попадают в ту же папку, что видит Sorter
```

## 4. Запуск
Выполните команду:
```bash
docker-compose up -d --build
```

## 5. Настройка Webhook в торрент-клиенте
Так как оба сервиса находятся в одной Docker-сети, клиент может обращаться к Sorter по имени сервиса.

### Transmission
В настройках Transmission (или в скрипте `script-torrent-done-filename`):
`"script-torrent-done-filename": "/app/process_torrent.py"`
(Убедитесь, что файл `process_torrent.py` доступен внутри контейнера Transmission).

### qBittorrent
В настройках "Выполнить внешнюю программу при завершении":
`python3 /app/process_torrent.py "%N" "%D" "%I"`

## 6. Важные замечания по путям
Чтобы всё работало корректно:
- Путь, куда клиент качает файлы (в примере `/mnt/media`), должен быть примонтирован в оба контейнера.
- В настройках Sorter (`config.ini` или через веб-интерфейс) пути `movies_folder` и `series_folder` должны указывать на подпапки внутри того же монтирования (например, `/mnt/media/Movies`).
