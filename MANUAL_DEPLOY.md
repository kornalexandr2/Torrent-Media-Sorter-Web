# Инструкция по ручному развертыванию (Manual Deployment)

Эта инструкция поможет вам установить сервис непосредственно на сервер без использования Docker.

## 1. Системные требования
- Python 3.11 или выше.
- Доступ к интернету (для API запросов).
- Права на запись в папки медиатеки.

## 2. Подготовка структуры папок
Рекомендуется создать отдельную директорию для проекта:

```bash
mkdir -p /opt/torrentmediasorter/config
cd /opt/torrentmediasorter
```

## 3. Установка проекта
1. Склонируйте репозиторий или скопируйте файлы в `/opt/torrentmediasorter`.
2. Создайте виртуальное окружение и установите зависимости:
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```

## 4. Настройка конфигурации
Отредактируйте файл `config.ini`:
- Укажите пути в секции `[PATHS]`:
  ```ini
  movies_folder = /path/to/your/Movies
  series_folder = /path/to/your/Series
  ```
- Укажите API ключи в секции `[API]`.

## 5. Запуск сервиса
Для постоянной работы рекомендуется использовать `systemd` (в Linux).

**Создайте файл сервиса `/etc/systemd/system/torrentmediasorter.service`:**
```ini
[Unit]
Description=Torrent Media Sorter Web Service
After=network.target

[Service]
User=ваша-учетка
Group=ваша-группа
WorkingDirectory=/opt/torrentmediasorter
ExecStart=/opt/torrentmediasorter/venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8080
Restart=always

[Install]
WantedBy=multi-user.target
```

**Активируйте и запустите:**
```bash
sudo systemctl daemon-reload
sudo systemctl enable torrentmediasorter
sudo systemctl start torrentmediasorter
```

## 6. Связка с торрент-клиентом
После установки сервис будет ожидать уведомлений на эндпоинт `/api/webhook`.

### Transmission
В настройках Transmission укажите путь к скрипту `process_torrent.py` в параметре `script-torrent-done-filename`.

### qBittorrent
В настройках "Выполнить внешнюю программу при завершении" укажите:
`python3 /opt/torrentmediasorter/process_torrent.py "%N" "%D" "%I"`

### Другие клиенты
Вы можете отправить POST запрос на `http://localhost:8080/api/webhook` со следующим JSON:
```json
{
  "torrent_id": "ID_торрента",
  "torrent_name": "Имя_торрента",
  "torrent_dir": "Путь_к_папке_загрузки"
}
```
