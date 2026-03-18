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
        
        # 1. Remove version numbers like 1.32, v1.32, 1.32.1
        n = re.sub(r'(?i)\b(v?\d+(\.\d+)+)\b', '', n)
        
        # 2. Remove year and everything after it ONLY if it's a 4-digit year starting with 19 or 20
        n = re.sub(r'\s(19|20)\d{2}\b.*', '', n)
        
        # 3. Specific cleaning for GOG/Steam suffixes often found in games
        n = re.sub(r'(?i)\b(win|gog|steam|repack|setup|build|version|update|dlc|gold|deluxe|complete|crack)\b.*', '', n)
        
        # 4. Standard quality tags
        quality_tags = r's\d+|season\s*\d+|сезон\s*\d+|720p|1080p|4k|2160p|480p|576p|bluray|web-dl|web-rip|webrip|hdtv|rip|remux|mhdr|hdr|uhd|hevc|h264|x264|h265|x265|aac|dts|ac3|multi|dub|sub'
        n = re.sub(r'(?i)\b(' + quality_tags + r')\b.*', '', n)
        
        if self.stop_words:
            pattern_str = '|'.join(re.escape(w) for w in self.stop_words)
            n = re.sub(r'(?i)\b(' + pattern_str + r')\b.*', '', n)
            
        result = n.strip(' -()[]')
        # If we cleaned too much, return base
        return result if len(result) >= 2 else base_cleaned.strip(' -()[]')

    def detect_type(self, path):
        p = Path(path)
        target_name = p.name
        
        try:
            all_files = [f for f in p.rglob('*') if f.is_file()] if p.is_dir() else [p]
        except Exception as e:
            logger.error(f"--> [SCANNER] Access error for {path}: {e}")
            return {'movie': 0, 'tv': 0, 'game': 0, 'software': 0, 'other': 0}, target_name

        if not all_files:
            return {'movie': 0, 'tv': 0, 'game': 0, 'software': 0, 'other': 0}, target_name

        scores = {'movie': 0, 'tv': 0, 'game': 0, 'software': 0, 'other': 0}
        
        # Factor 1: Executables / Software indicators
        software_indicators = {'.exe', '.dll', '.msi', '.apk', '.bin', '.bat', '.cmd'}
        has_soft_ind = any(f.suffix.lower() in software_indicators for f in all_files)
        if has_soft_ind:
            scores['software'] += 80
            scores['game'] += 80
            scores['movie'] -= 90
            scores['tv'] -= 90

            exe_files = [f for f in all_files if f.suffix.lower() == '.exe']
            if exe_files:
                exe_files.sort(key=lambda x: len(x.parts))
                target_name = exe_files[0].name
                scores['software'] += 10
            else:
                target_name = p.name

        # Factor 2: ISO / Disk Images
        iso_indicators = {'.iso', '.mds', '.mdf', '.nrg'}
        has_iso = any(f.suffix.lower() in iso_indicators for f in all_files)
        if has_iso:
            scores['game'] += 60
            scores['software'] += 50
            scores['movie'] += 20 # Could be DVD/BD image
            scores['tv'] += 10
            
        # Factor 3: Console game indicators
        console_indicators = {'.nsp', '.xci', '.nspro', '.vpk'}
        if any(f.suffix.lower() in console_indicators for f in all_files):
            scores['game'] += 90
            scores['movie'] -= 90
            scores['tv'] -= 90

        # Factor 4: Videos
        video_files = [f for f in all_files if f.suffix.lower() in self.video_exts]
        big_videos = [f for f in video_files if f.stat().st_size > 50 * 1024 * 1024]
        
        if big_videos:
            scores['movie'] += 40
            scores['tv'] += 40
            
            has_series_pattern = False
            for f in big_videos:
                if self.get_season_episode(f.name) or any(m.search(f.name) for m in self.series_masks):
                    has_series_pattern = True
                    target_name = f.name
                    break
                    
            if has_series_pattern:
                scores['tv'] += 50
                scores['movie'] -= 30
            else:
                if len(big_videos) == 1:
                    scores['movie'] += 40
                    scores['tv'] -= 10
                elif len(big_videos) > 1:
                    scores['tv'] += 30
                    scores['movie'] += 10
                
                big_videos.sort(key=lambda x: x.stat().st_size, reverse=True)
                if not has_series_pattern:
                    target_name = big_videos[0].name
        elif video_files:
            # Small video files
            scores['movie'] += 10
            scores['tv'] += 10

        # Factor 5: Stop extensions
        for f in all_files:
            if f.suffix.lower() in self.stop_exts:
                scores['other'] += 50
                scores['movie'] -= 50
                scores['tv'] -= 50

        # Factor 6: File counts
        if len(all_files) > 100 and not big_videos:
            scores['software'] += 30
            scores['game'] += 30
            
        # Clamp scores between 0 and 100
        for k in scores:
            scores[k] = max(0, min(100, scores[k]))
            
        # If everything is 0, give 'other' some score
        if max(scores.values()) == 0:
            scores['other'] = 50
            
        return scores, target_name


scanner = Scanner()
