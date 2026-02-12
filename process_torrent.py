#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Transmission Media Sorter
-------------------------
Repository: https://github.com/kornalexandr2/Transmission-Media-Sorter
License: MIT
"""

import os
import shutil
import logging
import logging.handlers
import re
import configparser
import sys
import json
import urllib.request
import urllib.parse
import subprocess
import platform
from pathlib import Path

# --- НАСТРОЙКИ ---
BASE_DIR = Path(__file__).resolve().parent
CONFIG_FILE = BASE_DIR / 'config.ini'
MOVIES_MASKS_FILE = BASE_DIR / 'masks_movies.txt'
SERIES_MASKS_FILE = BASE_DIR / 'masks_series.txt'
STOP_WORDS_FILE = BASE_DIR / 'stop_words.txt'

config = configparser.ConfigParser()
if not CONFIG_FILE.exists():
    # Логгер еще не настроен, выводим в stderr
    sys.stderr.write(f"Critical: Config file not found at {CONFIG_FILE}\n")
    sys.exit(1)

config.read(CONFIG_FILE, encoding='utf-8')

# Исправление путей: раскрываем ~ (home directory) для кросс-платформенности
# Используем pathlib для expanduser
MOVIES_FOLDER = Path(config['PATHS']['movies_folder']).expanduser()
SERIES_FOLDER = Path(config['PATHS']['series_folder']).expanduser()

LOG_FILE = Path(config['LOGGING']['log_file']).expanduser()
VIDEO_EXTS = tuple(x.strip() for x in config.get('SYSTEM', 'video_extensions', fallback='.mkv,.avi,.mp4').split(','))

def load_simple_list(filepath):
    items = []
    if filepath.exists():
        with filepath.open('r', encoding='utf-8') as f:
            for line in f:
                stripped = line.strip()
                if stripped and not stripped.startswith('#'):
                    items.append(stripped)
    return items

# SEARCH CONFIG
STOP_WORDS = load_simple_list(STOP_WORDS_FILE)

# RENAMING CONFIG
RENAME_MODE = config.get('RENAMING', 'rename_mode', fallback='ru').lower()
SAVE_ORIGINAL_FILENAME = config.getboolean('RENAMING', 'save_original_filename', fallback=True)

# API CONFIG
USE_KP = config.getboolean('API', 'use_kp', fallback=False)
KP_API_KEY = config.get('API', 'kp_api_key', fallback=None)

USE_TMDB = config.getboolean('API', 'use_tmdb', fallback=False)
TMDB_API_KEY = config.get('API', 'tmdb_api_key', fallback=None)

USE_TVDB = config.getboolean('API', 'use_tvdb', fallback=False)
TVDB_API_KEY = config.get('API', 'tvdb_api_key', fallback=None)

# TELEGRAM CONFIG
USE_TELEGRAM = config.getboolean('TELEGRAM', 'use_telegram', fallback=False)
TG_TOKEN = config.get('TELEGRAM', 'bot_token', fallback=None)
TG_CHAT_ID = config.get('TELEGRAM', 'chat_id', fallback=None)

# TRANSMISSION CONFIG
TR_HOST = config.get('TRANSMISSION', 'host', fallback='localhost')
TR_PORT = config.get('TRANSMISSION', 'port', fallback='9091')
TR_USER = config.get('TRANSMISSION', 'username', fallback='')
TR_PASS = config.get('TRANSMISSION', 'password', fallback='')

# --- ЛОГИРОВАНИЕ ---
logger = logging.getLogger('MediaSorter')
log_level_str = config.get('LOGGING', 'level', fallback='INFO').upper()
logger.setLevel(getattr(logging, log_level_str, logging.INFO))

# FIX: Проверяем наличие хендлеров перед добавлением, чтобы избежать дублирования
if not logger.handlers:
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    
    # Файл (RotatingFileHandler)
    try:
        # Убедимся, что директория логов существует
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        
        # 5 MB max size, 5 backups
        fh = logging.handlers.RotatingFileHandler(
            LOG_FILE, maxBytes=5*1024*1024, backupCount=5, encoding='utf-8'
        )
        fh.setFormatter(formatter)
        logger.addHandler(fh)
    except Exception as e:
        sys.stderr.write(f"Warning: Could not setup file logging: {e}\n")

    # Консоль
    sh = logging.StreamHandler()
    sh.setFormatter(formatter)
    logger.addHandler(sh)

# --- ФУНКЦИИ ---

def send_telegram(text):
    if not USE_TELEGRAM or not TG_TOKEN or not TG_CHAT_ID or "YOUR_" in TG_TOKEN:
        return
    try:
        logger.info("--> [TELEGRAM] Sending notification...")
        url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
        data = urllib.parse.urlencode({'chat_id': TG_CHAT_ID, 'text': text, 'parse_mode': 'HTML'}).encode('utf-8')
        urllib.request.urlopen(url, data=data, timeout=5)
        logger.info("--> [TELEGRAM] Sent successfully.")
    except Exception as e:
        logger.error(f"--> [TELEGRAM] Error: {e}")

def remove_torrent_from_client(torrent_id):
    if not torrent_id: return
    
    # FIX: Проверка наличия утилиты transmission-remote (Issue process_torrent.py:95)
    executable = shutil.which('transmission-remote')
    if not executable:
        # Если это Windows, transmission-remote может не быть в PATH.
        # Можно попробовать указать полный путь, если он известен, или вывести ошибку.
        logger.warning(f"--> [TORRENT] 'transmission-remote' executable not found in PATH. Cannot remove torrent ID {torrent_id}.")
        logger.warning("--> [TORRENT] If you are on Windows, ensure transmission-remote-gui or cli tools are installed and in PATH.")
        return

    cmd = [executable, f"{TR_HOST}:{TR_PORT}", '--torrent', str(torrent_id), '--remove']
    if TR_USER and TR_PASS and "YOUR_" not in TR_USER:
        cmd.insert(1, '--auth')
        cmd.insert(2, f"{TR_USER}:{TR_PASS}")
    try:
        logger.info(f"--> [TORRENT] Removing ID {torrent_id} from client...")
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if result.returncode == 0:
            logger.info("--> [TORRENT] Removed successfully.")
        else:
            logger.error(f"--> [TORRENT] Remove failed: {result.stderr}")
    except Exception as e:
        logger.error(f"--> [TORRENT] Error executing command: {e}")

def load_masks(filepath):
    masks = []
    # filepath is already a Path object from config setup
    if filepath.exists():
        with filepath.open('r', encoding='utf-8') as f:
            for line in f:
                stripped = line.strip()
                if stripped and not stripped.startswith('#'):
                    try: 
                        masks.append(re.compile(stripped))
                    except re.error as e:
                        logger.warning(f"Invalid mask pattern '{stripped}' in {filepath.name}: {e}")
    return masks

def check_match(name, patterns):
    for p in patterns:
        if p.search(name): return True
    return False

def sanitize(name):
    if not name: return ""
    name = re.sub(r'[:/\\|]', ' - ', name)
    return re.sub(r'[?"*<>]', '', name).strip()

def get_unique_path(path):
    # path is expected to be a Path object
    p = path
    if not p.exists(): return p
    counter = 1
    while True:
        new_path = p.parent / f"{p.stem}_copy{counter}{p.suffix}"
        if not new_path.exists(): return new_path
        counter += 1

def clean_search(name):
    # Get stem and replace separators
    stem = Path(name).stem
    n = stem.replace('.', ' ').replace('_', ' ').strip()
    
    # Store a base version for fallback (just basic cleanup)
    base_cleaned = n
    
    # Fix: Require space before year to avoid breaking titles like "1917"
    # By stripping before this step, we ensure "1917 2019" remains "1917"
    n = re.sub(r'\s(19|20)\d{2}\b.*', '', n)
    
    # Expanded quality and technical tags
    quality_tags = r's\d+|season\s*\d+|сезон\s*\d+|720p|1080p|4k|2160p|480p|576p|bluray|web-dl|web-rip|webrip|hdtv|rip|remux|mhdr|hdr|uhd|hevc|h264|x264|h265|x265|aac|dts|ac3|multi|dub|sub|itunes|amzn|nf|dsnp|hmax|repack|proper|internal'
    n = re.sub(r'(?i)\b(' + quality_tags + r')\b.*', '', n)
    
    # Use STOP_WORDS from config/file
    if STOP_WORDS:
        pattern_str = '|'.join(re.escape(w) for w in STOP_WORDS)
        n = re.sub(r'(?i)\b(' + pattern_str + r')\b.*', '', n)

    n = re.sub(r'\s\d+$', '', n)
    result = n.strip(' -()[]')
    
    # Safety: If cleaning was too aggressive and result is too short, 
    # but the base version was longer, return the base version.
    if len(result) < 2 and len(base_cleaned) >= 2:
        return base_cleaned.strip(' -()[]')
        
    return result

# --- API FUNCTIONS (KP, TMDB, TVDB) --- 
# (Код API функций оставлен без изменений для краткости, так как замечаний не было)
def check_kp(query):
    if not KP_API_KEY or "YOUR_" in KP_API_KEY: return None
    logger.info(f"--> [API:KP] Searching Kinopoisk for: '{query}'")
    try:
        q_enc = urllib.parse.quote(query)
        url = f"https://kinopoiskapiunofficial.tech/api/v2.1/films/search-by-keyword?keyword={q_enc}"
        req = urllib.request.Request(url)
        req.add_header('X-API-KEY', KP_API_KEY) 
        req.add_header('Content-Type', 'application/json')
        with urllib.request.urlopen(req, timeout=5) as r:
            data = json.loads(r.read().decode())
            if not data.get('films'): return None
            item = data['films'][0]
            k_type = item.get('type')
            titles = {'ru': item.get('nameRu'), 'en': item.get('nameEn'), 'origin': item.get('nameOriginal') or item.get('nameEn')}
            year = str(item.get('year') or '')
            t = 'movie' if k_type == 'FILM' else ('tv' if k_type in ['TV_SERIES', 'MINI_SERIES', 'TV_SHOW'] else None)
            if t: return {'type': t, 'titles': titles, 'year': year, 'source': 'KP'}
    except Exception as e:
        logger.error(f"--> [API:KP] Error: {e}")
    return None

def check_tmdb(query):
    if not TMDB_API_KEY or "YOUR_" in TMDB_API_KEY: return None
    logger.info(f"--> [API:TMDB] Searching TMDB for: '{query}'")
    try:
        q_enc = urllib.parse.quote(query)
        url = f"https://api.themoviedb.org/3/search/multi?api_key={TMDB_API_KEY}&query={q_enc}&language=ru-RU&page=1"
        with urllib.request.urlopen(url, timeout=5) as r:
            data = json.loads(r.read().decode())
            if not data.get('results'): return None
            valid_results = [x for x in data['results'] if x.get('media_type') in ['movie', 'tv']]
            if not valid_results: return None
            item = valid_results[0]
            media_type = item.get('media_type')
            if media_type == 'movie':
                t_ru, t_orig, date = item.get('title'), item.get('original_title'), item.get('release_date', '')
            else:
                t_ru, t_orig, date = item.get('name'), item.get('original_name'), item.get('first_air_date', '')
            titles = {'ru': t_ru, 'en': t_orig, 'origin': t_orig}
            year = date[:4] if date and len(date) >= 4 else ""
            return {'type': media_type, 'titles': titles, 'year': year, 'source': 'TMDB'}
    except Exception as e:
        logger.error(f"--> [API:TMDB] Error: {e}")
    return None

def check_tvdb(query):
    if not TVDB_API_KEY or "YOUR_" in TVDB_API_KEY: return None
    logger.info(f"--> [API:TVDB] Searching TVDB for: '{query}'")
    try:
        login_url = "https://api4.thetvdb.com/v4/login"
        login_data = json.dumps({"apikey": TVDB_API_KEY}).encode('utf-8')
        req = urllib.request.Request(login_url, data=login_data, method='POST')
        req.add_header('Content-Type', 'application/json')
        with urllib.request.urlopen(req, timeout=5) as r:
            token = json.loads(r.read().decode()).get('data', {}).get('token')
            if not token: return None
        q_enc = urllib.parse.quote(query)
        search_url = f"https://api4.thetvdb.com/v4/search?query={q_enc}"
        req_s = urllib.request.Request(search_url)
        req_s.add_header('Authorization', f'Bearer {token}')
        with urllib.request.urlopen(req_s, timeout=5) as r:
            data = json.loads(r.read().decode())
            if not data.get('data'): return None
            item = data['data'][0]
            raw_type = item.get('type', 'series')
            t = 'movie' if raw_type == 'movie' else 'tv'
            t_orig = item.get('name')
            t_ru = item['translations']['rus'] if item.get('translations') and item['translations'].get('rus') else None
            titles = {'ru': t_ru or t_orig, 'en': t_orig, 'origin': t_orig}
            year = item.get('year') or ""
            return {'type': t, 'titles': titles, 'year': str(year), 'source': 'TVDB'}
    except Exception as e:
        logger.error(f"--> [API:TVDB] Error: {e}")
    return None

def resolve_metadata(clean_name):
    meta = None
    if USE_KP: meta = check_kp(clean_name)
    if not meta and USE_TMDB: meta = check_tmdb(clean_name)
    if not meta and USE_TVDB: meta = check_tvdb(clean_name)
    return meta

def construct_filename(meta, original_file_path):
    if RENAME_MODE == 'no_change' or not meta: return original_file_path.name
    titles = meta['titles']
    year = meta['year']
    target_title = None
    if RENAME_MODE == 'ru': target_title = titles.get('ru')
    elif RENAME_MODE == 'en': target_title = titles.get('en')
    elif RENAME_MODE == 'origin': target_title = titles.get('origin')
    if not target_title: target_title = titles.get('ru') or titles.get('origin') or titles.get('en')
    if not target_title: target_title = original_file_path.stem
    clean_title = sanitize(target_title)
    final_base = f"{clean_title} ({year})" if year else clean_title
    if original_file_path.suffix: 
        if SAVE_ORIGINAL_FILENAME: return f"{final_base} ({original_file_path.stem}){original_file_path.suffix}"
        else: return f"{final_base}{original_file_path.suffix}"
    return final_base

def safe_transfer_file(src_path, dest_path):
    # Ensure dest_path is a Path object
    dest_path = Path(dest_path)
    logger.info(f"--> [COPY] Starting copy: {src_path.name} -> {dest_path}")
    try:
        shutil.copyfile(src_path, dest_path)
        if not dest_path.exists():
            logger.error("--> [COPY] Failed: Destination file not found after copy.")
            return False
        
        s_size = src_path.stat().st_size
        d_size = dest_path.stat().st_size
        
        if s_size == d_size:
            logger.info(f"--> [COPY] Success. Verified size: {s_size} bytes.")
            logger.info(f"--> [DELETE] Deleting source file: {src_path.name}")
            try:
                src_path.unlink()
                return True
            except Exception as del_err:
                logger.warning(f"--> [DELETE] Failed to delete source file: {del_err}")
                return True 
        else:
            logger.error(f"--> [COPY] CRITICAL SIZE MISMATCH! Source: {s_size}, Dest: {d_size}")
            logger.error("--> [COPY] The destination file is likely corrupted. Deleting destination file to prevent issues.")
            if dest_path.exists(): 
                dest_path.unlink()
            return False
            
    except Exception as e:
        logger.error(f"--> [COPY] Critical Exception: {e}")
        if dest_path.exists(): 
            try: dest_path.unlink()
            except: pass
        return False

def get_season_episode(name):
    m = re.search(r'(?i)(s\d{1,2}e\d{1,2})', name)
    if m: return m.group(1).upper()
    m = re.search(r'(?i)(\d{1,2}x\d{1,2})', name)
    return m.group(1).lower() if m else None

def process_folder_content(src_folder, dest_folder, meta):
    cnt = 0
    errors = 0
    logger.info(f"--> [FOLDER] Processing folder: {src_folder.name}")
    for f in src_folder.rglob('*'):
        if f.is_file() and f.suffix.lower() in VIDEO_EXTS:
            if meta: nf = construct_filename(meta, f)
            else: nf = f.name
            target = dest_folder / nf
            final = get_unique_path(target)
            if safe_transfer_file(f, final): cnt += 1
            else: errors += 1
    logger.info(f"--> [FOLDER] Processed {cnt} files. Errors: {errors}.")
    if cnt > 0 and errors == 0:
        try:
            logger.info(f"--> [DELETE] Removing source folder: {src_folder}")
            shutil.rmtree(src_folder)
        except Exception as e:
            logger.warning(f"--> [DELETE] Failed to remove folder: {e}")
    return cnt

def process_torrent(path):
    p = Path(path)
    logger.info("="*50)
    logger.info(f"[START] Processing: {p}")
    
    if not p.exists():
        logger.error(f"Path not found: {path}")
        return

    sp = load_masks(SERIES_MASKS_FILE)
    mp = load_masks(MOVIES_MASKS_FILE)
    
    m_v = None
    target_name_for_api = p.name
    force_series = False 
    
    if p.is_dir():
        logger.info("--> [SCAN] Directory detected. Scanning content...")
        for subfile in p.rglob('*'):
            if subfile.is_file() and subfile.suffix.lower() in VIDEO_EXTS:
                if get_season_episode(subfile.name):
                    logger.info(f"--> [SCAN] Found explicit series episode tag: {subfile.name}")
                    force_series = True
                    target_name_for_api = subfile.name 
                    break
                if check_match(subfile.name, sp):
                    logger.info(f"--> [SCAN] Found series match by mask: {subfile.name}")
                    force_series = True
                    target_name_for_api = subfile.name 
                    break
    
    if force_series:
        m_v = 'tv'
        logger.info("--> [SCAN] Force Series Mode activated.")

    if not m_v:
        logger.info("--> [MASK] Checking against masks...")
        m_v = 'tv' if check_match(p.name, sp) else ('movie' if check_match(p.name, mp) else None)
        logger.info(f"--> [MASK] Verdict: {m_v}")
    
    api_data = None
    q_name = clean_search(target_name_for_api)
    if len(q_name) >= 2: api_data = resolve_metadata(q_name)
    else: logger.warning(f"--> [API] Query too short ('{q_name}'). Skipping API checks.")

    if api_data: 
        api_type = api_data['type']
        source = api_data.get('source', 'UNK')
        logger.info(f"--> [DECISION] API ({source}) found type: {api_type}")
        if force_series and api_type != 'tv':
            logger.warning(f"--> [OVERRIDE] API says {api_type}, but files contain series patterns. Forcing TV.")
            m_v = 'tv'
        else: m_v = api_type
    else: 
        logger.info("--> [DECISION] All APIs failed or disabled. Falling back to Regex.")

    if not m_v:
        if force_series: m_v = 'tv'
        else:
            logger.error("--> [DECISION] Could not determine type. Stopping.")
            return

    if api_data:
        titles = api_data['titles']
        t_base = titles.get(RENAME_MODE) or titles.get('ru') or titles.get('origin') or titles.get('en') or p.name
        t_clean = sanitize(t_base)
        year = api_data['year']
        base = f"{t_clean} ({year})" if year else t_clean
    else:
        base = sanitize(p.name)
    
    success = False
    
    if m_v == 'tv' and p.is_dir():
        dest = SERIES_FOLDER / base
        dest.mkdir(parents=True, exist_ok=True)
        cnt = process_folder_content(p, dest, api_data)
        if cnt: 
            send_telegram(f"📺 <b>Сериал готов</b>\n{base}\nФайлов: {cnt}")
            success = True

    elif m_v == 'movie' and p.is_dir():
        dest = MOVIES_FOLDER / base
        dest.mkdir(parents=True, exist_ok=True)
        cnt = process_folder_content(p, dest, api_data)
        if cnt: 
            send_telegram(f"🎬 <b>Фильм готов</b>\n{base}")
            success = True

    elif p.is_file():
        dest_root = MOVIES_FOLDER if m_v == 'movie' else SERIES_FOLDER
        if api_data: fname = construct_filename(api_data, p)
        else: fname = p.name
        final = get_unique_path(dest_root / fname)
        if safe_transfer_file(p, final):
            icon = "🎬" if m_v == 'movie' else "📺"
            send_telegram(f"{icon} <b>Готово</b>\n{final.name}")
            success = True

    # 4. REMOVE TORRENT
    if success:
        tr_id = os.environ.get('TR_TORRENT_ID')
        if tr_id:
            logger.info(f"--> [TORRENT] Cleaning up torrent ID: {tr_id}")
            remove_torrent_from_client(tr_id)
        else:
            # FIX: Более понятное сообщение (Issue process_torrent.py:442)
            logger.info("--> [TORRENT] Environment variable TR_TORRENT_ID not found.")
            logger.info("--> [TORRENT] If you are running this manually, torrent removal is skipped.")
            logger.info("--> [TORRENT] If run by Transmission, check settings to ensure it passes environment variables.")
            
    logger.info("[DONE] Processing finished.")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        # sys.argv[1] is a string, process_torrent converts it to Path
        process_torrent(sys.argv[1])
    else:
        tr_dir = os.environ.get('TR_TORRENT_DIR')
        tr_name = os.environ.get('TR_TORRENT_NAME')
        if tr_dir and tr_name:
            try:
                # Use pathlib to join paths
                full_path = Path(tr_dir) / tr_name
                process_torrent(full_path)
            except Exception as e:
                logger.error(f"Critical error: {e}")
                send_telegram(f"⚠️ Ошибка скрипта: {e}")
        else:
            logger.error("No arguments provided.")