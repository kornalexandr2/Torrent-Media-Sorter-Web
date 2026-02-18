import re
import os
from pathlib import Path
from ..config import config_manager, BASE_DIR

class Scanner:
    def __init__(self):
        self.stop_words = self._load_simple_list(BASE_DIR / 'stop_words.txt')
        self.series_masks = self._load_masks(BASE_DIR / 'masks_series.txt')
        self.movies_masks = self._load_masks(BASE_DIR / 'masks_movies.txt')
        self.video_exts = tuple(x.strip() for x in config_manager.get('SYSTEM', 'video_extensions', fallback='.mkv,.avi,.mp4').split(','))

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
        target_name = p.name
        
        if p.is_dir():
            for f in p.rglob('*'):
                if f.is_file() and f.suffix.lower() in self.video_exts:
                    if self.get_season_episode(f.name) or any(m.search(f.name) for m in self.series_masks):
                        is_series = True
                        target_name = f.name
                        break
        else:
            if self.get_season_episode(p.name) or any(m.search(p.name) for m in self.series_masks):
                is_series = True

        return 'tv' if is_series else 'movie', target_name

scanner = Scanner()
