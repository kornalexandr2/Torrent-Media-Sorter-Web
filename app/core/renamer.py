import re
from pathlib import Path
from ..config import config_manager
from .scanner import scanner

class Renamer:
    def sanitize(self, name):
        if not name: return ""
        name = re.sub(r'[:/\\|]', ' - ', name)
        return re.sub(r'[?"*<>]', '', name).strip()

    def get_unique_path(self, path):
        p = Path(path)
        if not p.exists(): return p
        counter = 1
        while True:
            new_path = p.parent / f"{p.stem}_copy{counter}{p.suffix}"
            if not new_path.exists(): return new_path
            counter += 1

    def construct_filename(self, meta, original_file_path):
        p = Path(original_file_path)
        orig_name = p.name
        episode_tag = scanner.get_season_episode(orig_name) or ""
        
        rename_mode = config_manager.get('RENAMING', 'rename_mode', 'ru').lower()
        template = config_manager.get('RENAMING', 'filename_template', '[name_lang] ([year]) ([torrent])').lower()

        if rename_mode == 'no_change' or not meta:
            return orig_name

        titles = meta.get('titles', {})
        year = str(meta.get('year', ''))
        
        # Resolve names
        name_lang = titles.get(rename_mode) or titles.get('ru') or titles.get('origin') or titles.get('en') or p.stem
        name_orig = titles.get('origin') or titles.get('en') or titles.get('ru') or p.stem

        # Map for template replacement
        mapping = {
            '[name_lang]': self.sanitize(name_lang),
            '[name_orig]': self.sanitize(name_orig),
            '[year]': year,
            '[torrent]': p.stem,
            '[tag]': episode_tag
        }

        # Build result based on template string
        # Template is a string like "[name_lang] ([year]) - [torrent]"
        res = template
        for key, val in mapping.items():
            res = res.replace(key, val)

        # Cleanup resulting string (double spaces, trailing dashes etc)
        res = re.sub(r'\s+', ' ', res).strip(' -')
        # Ensure parentheses aren't empty like "()"
        res = res.replace('()', '').replace('( )', '').replace('[]', '').replace('[ ]', '').strip()
        
        # If it's a series and we don't have a tag in template, append it
        if episode_tag and '[tag]' not in template:
            res = f"{res} {episode_tag}"

        return f"{res}{p.suffix}"

renamer = Renamer()
