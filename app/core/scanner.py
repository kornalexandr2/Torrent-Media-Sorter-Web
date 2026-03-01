import re
import os
import logging
from pathlib import Path
from ..config import config_manager, BASE_DIR

logger = logging.getLogger('TorrentMediaSorter')

class Scanner:
    def __init__(self):
        self.stop_words = self._load_simple_list(BASE_DIR / 'data' / 'stop_words.txt')
        self.series_masks = self._load_masks(BASE_DIR / 'data' / 'masks_series.txt')
        self.movies_masks = self._load_masks(BASE_DIR / 'data' / 'masks_movies.txt')
        self.video_exts = tuple(x.strip().lower() for x in config_manager.get('SYSTEM', 'video_extensions', fallback='.mkv,.avi,.mp4').split(','))
        self.stop_exts = tuple(x.strip().lower() for x in config_manager.get('SYSTEM', 'stop_extensions', fallback='.exe,.iso,.msi,.apk,.dmg').split(','))
        self.game_exts = tuple(x.strip().lower() for x in config_manager.get('SYSTEM', 'game_extensions', fallback='.exe,.iso,.nspro,.xci,.nsp').split(','))

    def _load_simple_list(self, filepath):
        items = []
        if os.path.exists(filepath):
            with open(filepath, 'r', encoding='utf-8') as f:
                for line in f:
                    stripped = line.strip()
                    if stripped and not stripped.startswith('#'):
                        items.append(stripped)
        return items

    def _load_masks(self, fp):
        if not os.path.exists(fp):
            return []
        with open(fp, 'r', encoding='utf-8') as f:
            return [re.compile(line.strip(), re.IGNORECASE) for line in f if line.strip() and not line.startswith('#')]

    def get_season_episode(self, name):
        m = re.search(r'(?i)(s\d{1,2}e\d{1,2})', name)
        if m: return m.group(1).upper()
        m = re.search(r'(?i)(\d{1,2}x\d{1,2})', name)
        return m.group(1).lower() if m else None

    def clean_search(self, name):
        n = Path(name).stem.replace('.', ' ').replace('_', ' ').strip()
        base_cleaned = n
        n = re.sub(r'\s(19|20)\d{2}\b.*', '', n)
        quality_tags = r's\d+|season\s*\d+|сезон\s*\d+|720p|1080p|4k|2160p|480p|576p|bluray|web-dl|web-rip|webrip|hdtv|rip|remux|mhdr|hdr|uhd|hevc|h264|x264|h265|x265|aac|dts|ac3|multi|dub|sub'
        n = re.sub(r'(?i)\b(' + quality_tags + r')\b.*', '', n)
        if self.stop_words:
            pattern_str = '|'.join(re.escape(w) for w in self.stop_words)
            n = re.sub(r'(?i)\b(' + pattern_str + r')\b.*', '', n)
        result = n.strip(' -()[]')
        return result if len(result) >= 2 else base_cleaned.strip(' -()[]')

    def detect_type(self, path):
        p = Path(path)
        is_series = False
        is_game = False
        target_name = p.name
        
        all_files = list(p.rglob('*')) if p.is_dir() else [p]
        
        # 1. Check for video files (Media)
        media_files = [f for f in all_files if f.is_file() and f.suffix.lower() in self.video_exts]
        if media_files:
            for f in media_files:
                if self.get_season_episode(f.name) or any(m.search(f.name) for m in self.series_masks):
                    is_series = True
                    target_name = f.name
                    break
            return 'tv' if is_series else 'movie', target_name

        # 2. Check for potentially executable files (Games or Software)
        game_files = [f for f in all_files if f.is_file() and f.suffix.lower() in self.game_exts]
        if game_files:
            # We mark it as 'software' initially. 
            # The MetadataManager will 'promote' it to 'game' if found in IGDB.
            exe_files = [f for f in game_files if f.suffix.lower() == '.exe']
            if exe_files:
                target_name = exe_files[0].name
            return 'software', target_name

        # 3. Check for stop extensions (Unknown/Software?)
        for f in all_files:
            if f.is_file() and f.suffix.lower() in self.stop_exts:
                logger.info(f"--> [SCANNER] Stop-extension found: {f.suffix}, skipping auto-detection.")
                return 'unknown', target_name

        return 'movie', target_name # Default to movie if nothing found? or unknown?


scanner = Scanner()
