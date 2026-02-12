# 📂 Transmission Media Sorter

**Transmission Media Sorter** — это продвинутый Python-скрипт для автоматической сортировки, переименования и организации видеофайлов, скачиваемых через торрент-клиент Transmission.

Скрипт анализирует скачанный контент, определяет тип (Фильм или Сериал) используя "умное" сканирование и внешние API (Kinopoisk, TMDB, TVDB), приводит имена файлов к чистому виду и перемещает их в конечные папки (например, для Plex, Jellyfin или Emby).

---

## ✨ Возможности

* **Мульти-API поддержка:** Работает с **Kinopoisk (Unofficial)**, **The Movie Database (TMDB)** и **The TV Database (TVDB v4)**.
* **Каскадный поиск:** Если фильм не найден в первом источнике, скрипт автоматически ищет в следующих (KP → TMDB → TVDB).
* **Гибкая настройка:** Каждый API можно включать и выключать отдельно.
* **Приоритет сериалов (Deep Scan):** Анализирует содержимое папок. Если найдены файлы с маркировкой серий (например, `S01E01`), скрипт обработает их как сериал, даже если API ошибочно определит как фильм.
* **Умное переименование:** Полный контроль над именами файлов — выбор языка (Русский/Английский/Оригинал) и возможность сохранения исходного имени файла в скобках.
* **Уведомления Telegram:** Отправляет отчеты о результатах (можно отключить в настройках).
* **Автоматическая очистка:** Удаляет торрент из клиента и стирает исходные файлы после успешного переноса.

---

## 📋 Требования

* **ОС:** Linux (Debian, Ubuntu, Arch, CentOS и др.)
* **Python:** 3.6 или выше.
* **Transmission:** Daemon или GUI.
* **API Ключи (Опционально):** Для улучшения точности рекомендуется получить бесплатные ключи от Kinopoisk, TMDB или TVDB.

---

## 🛠 Установка

### 1. Подготовка директории
Рекомендуется использовать путь `/opt/mediasorter`.

```bash
sudo mkdir -p /opt/mediasorter
sudo chown -R $USER:$USER /opt/mediasorter
cd /opt/mediasorter
```

### 2. Загрузка файлов
В папке должны находиться 4 файла:
1.  `process_torrent.py` (Скрипт)
2.  `config.ini` (Настройки)
3.  `masks_movies.txt` (Маски для фильмов)
4.  `masks_series.txt` (Маски для сериалов)

### 3. Права доступа
Сделайте скрипт исполняемым:

```bash
chmod +x /opt/mediasorter/process_torrent.py
```

> **Важно:** Пользователь, от имени которого запущен Transmission (обычно `debian-transmission` или `transmission`), должен иметь права на **запись** в папки назначения (`movies`, `tvshows`) и в папку логов.

---

## ⚙️ Настройка (config.ini)

Отредактируйте файл `config.ini`:

### Основные пути
```ini
[PATHS]
movies_folder = /mnt/media/movies
series_folder = /mnt/media/tvshows
```

### Настройка переименования
Настройте, как будут называться ваши файлы после обработки.

```ini
[RENAMING]
; Режим выбора названия (берется из API):
; ru        - Приоритет русского названия
; en        - Приоритет английского названия
; origin    - Приоритет оригинального названия
; no_change - Не менять название (оставить как в торренте)
rename_mode = ru

; Сохранять ли оригинальное имя файла (из торрента) в скобках?
; True  -> "Название фильма (Original.File.Name).mkv"
; False -> "Название фильма.mkv"
save_original_filename = True
```

### Настройка API (Источники данных)
Вы можете включить (`True`) или выключить (`False`) любой из сервисов. Скрипт будет опрашивать их по очереди.

```ini
[API]
; Kinopoisk Unofficial ([https://kinopoiskapiunofficial.tech](https://kinopoiskapiunofficial.tech))
use_kp = True
kp_api_key = ВАШ_API_КЛЮЧ

; TMDB ([https://www.themoviedb.org/settings/api](https://www.themoviedb.org/settings/api))
use_tmdb = True
tmdb_api_key = ВАШ_API_КЛЮЧ

; TVDB ([https://thetvdb.com/api-information](https://thetvdb.com/api-information))
use_tvdb = False
tvdb_api_key = ВАШ_API_КЛЮЧ
```

### Настройка Telegram
```ini
[TELEGRAM]
; Включить уведомления?
use_telegram = True
bot_token = ВАШ_ТОКЕН_БОТА
chat_id = ВАШ_CHAT_ID
```

---

## 🔗 Подключение к Transmission

Чтобы скрипт запускался автоматически после завершения загрузки:

### Способ А: Через `settings.json` (Daemon)
1.  Остановите демон: `sudo service transmission-daemon stop`
2.  Отредактируйте `settings.json` (обычно в `/etc/transmission-daemon/` или `~/.config/transmission-daemon/`):
    ```json
    "script-torrent-done-enabled": true,
    "script-torrent-done-filename": "/opt/mediasorter/process_torrent.py",
    ```
3.  Запустите демон: `sudo service transmission-daemon start`

### Способ Б: Через GUI (Графический интерфейс)
1.  Настройки -> Скрипты (Scripts).
2.  Включите галочку "Call script when torrent is completed".
3.  Выберите файл `/opt/mediasorter/process_torrent.py`.

---

## 🧪 Ручной запуск и Тестирование

Вы можете протестировать работу скрипта вручную, не скачивая торрент заново.

```bash
# Синтаксис: python3 process_torrent.py "ПУТЬ_К_ФАЙЛУ_ИЛИ_ПАПКЕ"
python3 /opt/mediasorter/process_torrent.py "/home/downloads/My.Movie.2024.mkv"
```

Следите за выводом в консоли. Подробный лог пишется в файл, указанный в `config.ini` (по умолчанию `/opt/mediasorter/sorter.log`).

---

## ❓ Решение проблем

1.  **Permission denied / Отказано в доступе:**
    * Проверьте, что пользователь `transmission` имеет права на запись в папку логов и папки куда переносятся фильмы.
    * Команда для исправления (пример): `sudo chown -R debian-transmission:debian-transmission /mnt/media`

2.  **Скрипт не запускается:**
    * Убедитесь, что в первой строке файла `process_torrent.py` стоит `#!/usr/bin/env python3`.
    * Проверьте права на исполнение: `ls -l process_torrent.py` (должно быть `rwxr-xr-x`).

3.  **Неверно определяет фильм/сериал:**
    * Попробуйте изменить порядок или наличие API в конфиге.
    * Если API ошибается, скрипт ориентируется на маски (`masks_*.txt`) и наличие файлов серий внутри папки.

---

## 📄 Лицензия

MIT License. Свободное использование и модификация.