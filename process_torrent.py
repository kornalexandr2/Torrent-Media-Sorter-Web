#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Transmission Media Sorter
-------------------------
Автоматический сортировщик медиафайлов для Transmission.
Определяет тип контента, скачивает метаданные, переименовывает файлы
с сохранением SxxExx и раскладывает по папкам.
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
from pathlib import Path

# --- НАСТРОЙКИ ---
BASE_DIR = Path(__file__).resolve().parent
CONFIG_FILE = BASE_DIR / 'config.ini'
MOVIES_MASKS_FILE = BASE_DIR / 'masks_movies.txt'
SERIES_MASKS_FILE = BASE_DIR / 'masks_series.txt'
STOP_WORDS_FILE = BASE_DIR / 'stop_words.txt'

config = configparser.ConfigParser()
if not CONFIG_FILE.exists():
    sys.stderr.write(f"Critical: Config file not found at {CONFIG_FILE}\n")
    sys.exit(1)

config.read(CONFIG_FILE, encoding='utf-8')

# Пути
MOVIES_FOLDER = Path(config['PATHS']['movies_folder']).expanduser()
SERIES_FOLDER = Path(config['PATHS']['series_folder']).expanduser()
LOG_FILE = Path(config['LOGGING']['log_file']).expanduser()
VIDEO_EXTS = tuple(x.strip() for x in config.get('SYSTEM', 'video_extensions', fallback='.mkv,.avi,.mp4').split(','))
SUBTITLE_EXTS = ('.srt', '.sub', '.ass', '.vtt')

def load_simple_list(filepath):
    items = []
    if filepath.exists():
        with filepath.open('r', encoding='utf-8') as f:
            for line in f:
                stripped = line.strip()
                if stripped and not stripped.startswith('#'):
                    items.append(stripped)
    return items

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

if not logger.handlers:
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        fh = logging.handlers.RotatingFileHandler(
            LOG_FILE, maxBytes=5*1024*1024, backupCount=5, encoding='utf-8'
        )
        fh.setFormatter(formatter)
        logger.addHandler(fh)
    except Exception as e:
        sys.stderr.write(f"Warning: Could not setup file logging: {e}\n")
    sh = logging.StreamHandler()
    sh.setFormatter(formatter)
    logger.addHandler(sh)

# --- ФУНКЦИИ УТИЛИТЫ ---

def get_season_episode(name):
    m = re.search(r'(?i)(s\d{1,2}e\d{1,2})', name)
    if m: return m.group(1).upper()
    m = re.search(r'(?i)(\d{1,2}x\d{1,2})', name)
    return m.group(1).lower() if m else None

def send_telegram(text):
    if not USE_TELEGRAM or not TG_TOKEN or not TG_CHAT_ID or "YOUR_" in TG_TOKEN: return
    try:
        url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
        data = urllib.parse.urlencode({'chat_id': TG_CHAT_ID, 'text': text, 'parse_mode': 'HTML'}).encode('utf-8')
        urllib.request.urlopen(url, data=data, timeout=5)
    except Exception as e:
        logger.error(f"--> [TELEGRAM] Error: {e}")

def remove_torrent_from_client(torrent_id):
    if not torrent_id: return
    executable = shutil.which('transmission-remote') or 'transmission-remote'
    cmd = [executable, f"{TR_HOST}:{TR_PORT}"]
    if TR_USER and TR_PASS and "YOUR_" not in TR_USER:
        cmd.extend(['--auth', f"{TR_USER}:{TR_PASS}"])
    cmd.extend(['--torrent', str(torrent_id), '--remove'])
    try:
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if result.returncode == 0: logger.info(f"--> [TORRENT] Removed ID {torrent_id}")
    except Exception as e: logger.error(f"--> [TORRENT] Error: {e}")

def sanitize(name):
    if not name: return ""
    name = re.sub(r'[:/\\|]', ' - ', name)
    return re.sub(r'[?"*<>]', '', name).strip()

def get_unique_path(path):
    p = Path(path)
    if not p.exists(): return p
    counter = 1
    while True:
        new_path = p.parent / f"{p.stem}_copy{counter}{p.suffix}"
        if not new_path.exists(): return new_path
        counter += 1

def clean_search(name):
    n = Path(name).stem.replace('.', ' ').replace('_', ' ').strip()
    base_cleaned = n
    n = re.sub(r'\s(19|20)\d{2}\b.*', '', n)
    quality_tags = r's\d+|season\s*\d+|сезон\s*\d+|720p|1080p|4k|2160p|480p|576p|bluray|web-dl|web-rip|webrip|hdtv|rip|remux|mhdr|hdr|uhd|hevc|h264|x264|h265|x265|aac|dts|ac3|multi|dub|sub'
    n = re.sub(r'(?i)\b(' + quality_tags + r')\b.*', '', n)
    if STOP_WORDS:
        pattern_str = '|'.join(re.escape(w) for w in STOP_WORDS)
        n = re.sub(r'(?i)\b(' + pattern_str + r')\b.*', '', n)
    result = n.strip(' -()[]')
    return result if len(result) >= 2 else base_cleaned.strip(' -()[]')

# --- API FUNCTIONS ---

def check_kp(query):
    if not KP_API_KEY or "YOUR_" in KP_API_KEY: return None
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
    except Exception as e: logger.error(f"--> [API:KP] Error: {e}")
    return None

def check_tmdb(query):
    if not TMDB_API_KEY or "YOUR_" in TMDB_API_KEY: return None
    try:
        q_enc = urllib.parse.quote(query)
        url = f"https://api.themoviedb.org/3/search/multi?api_key={TMDB_API_KEY}&query={q_enc}&language=ru-RU&page=1"
        with urllib.request.urlopen(url, timeout=5) as r:
            data = json.loads(r.read().decode())
            if not data.get('results'): return None
            valid = [x for x in data['results'] if x.get('media_type') in ['movie', 'tv']]
            if not valid: return None
            item = valid[0]
            m_type = item.get('media_type')
            if m_type == 'movie':
                t_ru, t_orig, date = item.get('title'), item.get('original_title'), item.get('release_date', '')
            else:
                t_ru, t_orig, date = item.get('name'), item.get('original_name'), item.get('first_air_date', '')
            titles = {'ru': t_ru, 'en': t_orig, 'origin': t_orig}
            year = date[:4] if date and len(date) >= 4 else ""
            return {'type': m_type, 'titles': titles, 'year': year, 'source': 'TMDB'}
    except Exception as e: logger.error(f"--> [API:TMDB] Error: {e}")
    return None

def check_tvdb(query):
    if not TVDB_API_KEY or "YOUR_" in TVDB_API_KEY: return None
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
            t_ru = item['translations'].get('rus') if item.get('translations') else None
            titles = {'ru': t_ru or t_orig, 'en': t_orig, 'origin': t_orig}
            year = item.get('year') or ""
            return {'type': t, 'titles': titles, 'year': str(year), 'source': 'TVDB'}
    except Exception as e: logger.error(f"--> [API:TVDB] Error: {e}")
    return None

def resolve_metadata(clean_name):
    meta = None
    if USE_KP: meta = check_kp(clean_name)
    if not meta and USE_TMDB: meta = check_tmdb(clean_name)
    if not meta and USE_TVDB: meta = check_tvdb(clean_name)
    return meta

# --- PROCESSING LOGIC ---

def construct_filename(meta, original_file_path):
    orig_name = original_file_path.name
    episode_tag = get_season_episode(orig_name)
    
    if RENAME_MODE == 'no_change' or not meta:
        return orig_name

    titles = meta['titles']
    year = meta['year']
    target_title = titles.get(RENAME_MODE) or titles.get('ru') or titles.get('origin') or titles.get('en')
    if not target_title: target_title = original_file_path.stem
    
    clean_title = sanitize(target_title)
    final_base = f"{clean_title} ({year})" if year else clean_title
    
    # Вставка SxxExx перед расширением
    if episode_tag:
        final_base = f"{final_base} {episode_tag}"
    
    if SAVE_ORIGINAL_FILENAME:
        return f"{final_base} ({original_file_path.stem}){original_file_path.suffix}"
    return f"{final_base}{original_file_path.suffix}"

def safe_transfer_file(src_path, dest_path):
    dest_path = Path(dest_path)
    try:
        shutil.copyfile(src_path, dest_path)
        if dest_path.exists() and src_path.stat().st_size == dest_path.stat().st_size:
            src_path.unlink()
            return True
        return False
    except Exception as e:
        logger.error(f"--> [TRANSFER] Error: {e}")
        return False

def process_folder_content(src_folder, dest_folder, meta):
    cnt = 0
    for f in list(src_folder.rglob('*')):
        if f.is_file() and f.suffix.lower() in VIDEO_EXTS:
            new_name = construct_filename(meta, f)
            target = get_unique_path(dest_folder / new_name)
            if safe_transfer_file(f, target):
                cnt += 1
                for sub_ext in SUBTITLE_EXTS:
                    sub_src = f.with_suffix(sub_ext)
                    if sub_src.exists():
                        safe_transfer_file(sub_src, target.with_suffix(sub_ext))
    try:
        if not any(src_folder.iterdir()): shutil.rmtree(src_folder)
    except: pass
    return cnt

def process_torrent(path):
    p = Path(path)
    if not p.exists(): return
    logger.info("="*50)
    logger.info(f"[START] {p.name}")

    def load_masks(fp):
        if not fp.exists(): return []
        with fp.open('r', encoding='utf-8') as f:
            return [re.compile(line.strip()) for line in f if line.strip() and not line.startswith('#')]

    sp, mp = load_masks(SERIES_MASKS_FILE), load_masks(MOVIES_MASKS_FILE)
    
    is_series = False
    target_for_api = p.name
    if p.is_dir():
        for f in p.rglob('*'):
            if f.is_file() and f.suffix.lower() in VIDEO_EXTS:
                if get_season_episode(f.name) or any(m.search(f.name) for m in sp):
                    is_series = True
                    target_for_api = f.name
                    break

    q_name = clean_search(target_for_api)
    api_data = resolve_metadata(q_name) if len(q_name) > 1 else None
    
    m_type = 'tv' if (is_series or (api_data and api_data['type'] == 'tv')) else 'movie'
    dest_root = SERIES_FOLDER if m_type == 'tv' else MOVIES_FOLDER
    
    if api_data:
        t = api_data['titles'].get(RENAME_MODE) or api_data['titles'].get('ru') or api_data['titles'].get('origin')
        folder_name = sanitize(f"{t} ({api_data['year']})" if api_data['year'] else t)
    else:
        folder_name = sanitize(p.name)

    success = False
    if p.is_dir():
        final_dest = dest_root / folder_name
        final_dest.mkdir(parents=True, exist_ok=True)
        count = process_folder_content(p, final_dest, api_data)
        if count > 0:
            send_telegram(f"{'📺' if m_type=='tv' else '🎬'} <b>Готово:</b> {folder_name} ({count} ф.)")
            success = True
    else:
        new_fname = construct_filename(api_data, p)
        final_path = get_unique_path(dest_root / new_fname)
        if safe_transfer_file(p, final_path):
            send_telegram(f"{'📺' if m_type=='tv' else '🎬'} <b>Готово:</b> {new_fname}")
            success = True

    if success:
        remove_torrent_from_client(os.environ.get('TR_TORRENT_ID'))

if __name__ == "__main__":
    if len(sys.argv) > 1:
        process_torrent(sys.argv[1])
    else:
        d, n = os.environ.get('TR_TORRENT_DIR'), os.environ.get('TR_TORRENT_NAME')
        if d and n: process_torrent(Path(d) / n)