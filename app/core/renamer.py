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
        episode_tag = scanner.get_season_episode(orig_name)
        
        rename_mode = config_manager.get('RENAMING', 'rename_mode', 'ru').lower()
        save_original = config_manager.getboolean('RENAMING', 'save_original_filename', True)

        if rename_mode == 'no_change' or not meta:
            return orig_name

        titles = meta['titles']
        year = meta['year']
        target_title = titles.get(rename_mode) or titles.get('ru') or titles.get('origin') or titles.get('en')
        if not target_title: target_title = p.stem
        
        clean_title = self.sanitize(target_title)
        final_base = f"{clean_title} ({year})" if year else clean_title
        
        if episode_tag:
            final_base = f"{final_base} {episode_tag}"
        
        if save_original:
            return f"{final_base} ({p.stem}){p.suffix}"
        return f"{final_base}{p.suffix}"

renamer = Renamer()
