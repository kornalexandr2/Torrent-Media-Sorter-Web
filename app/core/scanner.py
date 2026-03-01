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
        
        # Remove year and everything after it ONLY if it's a 4-digit year starting with 19 or 20
        n = re.sub(r'\s(19|20)\d{2}\b.*', '', n)
        
        # Game specific tags - removed version tags from cutting logic to keep '3' in 'Witcher 3'
        # but added specific version patterns to remove them cleanly
        n = re.sub(r'(?i)\b(v?\d+(\.\d+)+)\b', '', n) # Remove v1.32, 1.32.1 etc
        
        quality_tags = r's\d+|season\s*\d+|сезон\s*\d+|720p|1080p|4k|2160p|480p|576p|bluray|web-dl|web-rip|webrip|hdtv|rip|remux|mhdr|hdr|uhd|hevc|h264|x264|h265|x265|aac|dts|ac3|multi|dub|sub'
        game_tags = r'setup|repack|build|version|update|dlc|gold\s*edition|deluxe\s*edition|complete\s*edition|crack|steam|gog|win'
        
        all_tags = quality_tags + '|' + game_tags
        n = re.sub(r'(?i)\b(' + all_tags + r')\b.*', '', n)
        
        if self.stop_words:
            pattern_str = '|'.join(re.escape(w) for w in self.stop_words)
            n = re.sub(r'(?i)\b(' + pattern_str + r')\b.*', '', n)
            
        result = n.strip(' -()[]')
        return result if len(result) >= 2 else base_cleaned.strip(' -()[]')

    def detect_type(self, path):
        p = Path(path)
        is_series = False
        target_name = p.name
        
        try:
            all_files = [f for f in p.rglob('*') if f.is_file()] if p.is_dir() else [p]
        except Exception as e:
            logger.error(f"--> [SCANNER] Access error for {path}: {e}")
            return 'unknown', target_name

        if not all_files:
            return 'unknown', target_name

        # 1. ABSOLUTE PRIORITY: Check for software/game indicators (exe, dll, iso, etc.)
        # If these exist, it is DEFINITELY NOT a movie or series.
        software_indicators = {'.exe', '.dll', '.iso', '.nsp', '.xci', '.nspro', '.msi', '.apk', '.bin'}
        found_indicators = [f for f in all_files if f.suffix.lower() in software_indicators]
        
        if found_indicators:
            # Try to find the best name (launcher exe or iso name)
            exe_files = [f for f in found_indicators if f.suffix.lower() == '.exe']
            if exe_files:
                exe_files.sort(key=lambda x: len(x.parts)) # Closest to root
                target_name = exe_files[0].name
            else:
                # If no exe, but dll/iso found, use folder name
                target_name = p.name
            return 'software', target_name

        # 2. Check for video files (Media)
        media_files = [f for f in all_files if f.suffix.lower() in self.video_exts]
        # Ignore very small files (trailers/intros)
        significant_media = [f for f in media_files if f.stat().st_size > 100 * 1024 * 1024]
        
        if significant_media:
            for f in significant_media:
                if self.get_season_episode(f.name) or any(m.search(f.name) for m in self.series_masks):
                    is_series = True
                    target_name = f.name
                    break
            if not is_series:
                significant_media.sort(key=lambda x: x.stat().st_size, reverse=True)
                target_name = significant_media[0].name
            return 'tv' if is_series else 'movie', target_name

        # 3. Check for general game/soft extensions from config
        game_files = [f for f in all_files if f.suffix.lower() in self.game_exts]
        if game_files or (p.is_dir() and len(all_files) > 50):
            return 'software', target_name

        # 4. Check for stop extensions
        for f in all_files:
            if f.suffix.lower() in self.stop_exts:
                return 'unknown', target_name

        return 'movie', target_name # Default fallback


scanner = Scanner()
