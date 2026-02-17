# Torrent Media Sorter (Web Service) 📦🎬

Интеллектуальный помощник для автоматической сортировки, переименования и управления медиатекой. Сервис принимает уведомления от торрент-клиентов (Transmission, qBittorrent и др.) по завершении закачки, находит метаданные в популярных базах (Кинопоиск, TMDB, TVDB) и раскладывает файлы по папкам.

## 🚀 Основные возможности
- **Автоматизация 24/7**: Работает как демон, заменяя разовые скрипты.
- **Универсальность**: Поддержка Transmission, qBittorrent, Deluge и других клиентов через Webhook.
- **Умное распознавание**: Отработанные алгоритмы очистки названий торрентов от лишнего мусора (720p, Rip, HEVC...).
- **Каскад метаданных (Chain of Responsibility)**: Если фильм не найден в одном источнике, система автоматически спросит в следующем.
- **Режимы файлов**: 
  - **Move (Перемещение)**: Удаляет оригинал из папки закачек.
  - **Copy (Копирование)**: Оставляет оригинал.
  - **Hardlink (Жесткая ссылка)**: Файл "появляется" в медиатеке мгновенно без занимания лишнего места на диске, оригинал остается на раздаче.
- **Интуитивный UI**: Dashboard на HTMX для быстрого отката (Undo), исправления распознавания (Fix Match) или повторной обработки (Retry).
- **Docker-native**: Полная изоляция и легкий запуск.

---

## 🛠 Установка

Рекомендуется устанавливать приложение в каталог `/opt/torrent-media-sorter-web`. Выберите наиболее подходящий вариант установки:

### 1. Docker
Автоматическая установка и запуск в Docker. Скрипт проверит зависимости и настроит порт.
```bash
sudo mkdir -p /opt/torrent-media-sorter-web && cd /opt/torrent-media-sorter-web
curl -sSL https://raw.githubusercontent.com/kornalexandr2/Torrent-Media-Sorter-Web/main/install_docker.sh | sudo bash
```

### 2. Docker Compose
Установка через Docker Compose с использованием интерактивного мастера.
```bash
sudo mkdir -p /opt/torrent-media-sorter-web && cd /opt/torrent-media-sorter-web
curl -sSL https://raw.githubusercontent.com/kornalexandr2/Torrent-Media-Sorter-Web/main/install.sh | sudo bash
```

### 3. В качестве службы (Systemd)
Установка приложения напрямую в систему Linux как фоновый процесс.
```bash
sudo mkdir -p /opt/torrent-media-sorter-web && cd /opt/torrent-media-sorter-web
curl -sSL https://raw.githubusercontent.com/kornalexandr2/Torrent-Media-Sorter-Web/main/install_service.sh | sudo bash
```

---

## 🏗 Режимы развертывания

### Вариант А: Вместе с торрент-клиентом (Один контейнер/Связка)
Если вы хотите, чтобы всё жило в одном `docker-compose.yml`:
Добавьте сервис торрент-клиента в тот же файл и пробросьте общие `volumes` для медиафайлов, чтобы пути внутри контейнеров совпадали (напр. `/mnt/media`).

### Вариант Б: Отдельный сервер
Вы можете поставить Sorter на отдельный сервер. В этом случае убедитесь, что Sorter имеет доступ к папке, куда клиент скачивает файлы (через NFS/SMB или монтирование дисков).

---

## ⚙️ Настройка торрент-клиента
Чтобы Torrent Media Sorter узнал о завершении закачки, настройте вызов вебхука. **Все необходимые команды и параметры для настройки вашего торрент-клиента будут доступны в веб-интерфейсе приложения после установки.**

### Краткие примеры:

#### Transmission
В настройках Transmission (или в скрипте `script-torrent-done-filename`):
`"script-torrent-done-filename": "/opt/torrent-media-sorter-web/process_torrent.py"`

#### qBittorrent
В настройках "Выполнить внешнюю программу при завершении":
`python3 /opt/torrent-media-sorter-web/process_torrent.py "%N" "%D" "%I"`

---

## 🔑 Где взять API Ключи?
1. **Kinopoisk Unofficial**: [kinopoiskapiunofficial.tech](https://kinopoiskapiunofficial.tech) (Бесплатно до 500 запросов/день).
2. **TMDB**: [themoviedb.org/settings/api](https://www.themoviedb.org/settings/api).
3. **TVDB v4**: [thetvdb.com/api-information](https://thetvdb.com/api-information).

---

## 💡 Решение проблем (Troubleshooting)
- **Логи**: `docker logs -f media_sorter` — здесь можно увидеть, почему фильм не распознался.
- **Права доступа**: Если файлы не перемещаются, убедитесь, что PUID/PGID в `docker-compose.yml` соответствуют владельцу папок с медиа.
- **Порты**: Если порт 7887 занят, скрипты установки автоматически предложат вам выбрать другой порт.

---

## 🗑 Удаление
Если вы хотите полностью удалить проект, выполните команду ниже:
```bash
curl -sSL https://raw.githubusercontent.com/kornalexandr2/Torrent-Media-Sorter-Web/main/uninstall.sh | sudo bash
```
Скрипт спросит подтверждение на удаление Docker-контейнеров, Systemd-служб и файлов приложения.

---

## 📝 Лицензия
Данный проект распространяется под лицензией MIT. Разрабатывался как замена сложным и тяжелым решениям (Radarr/Sonarr) для тех, кто любит простоту и контроль.
