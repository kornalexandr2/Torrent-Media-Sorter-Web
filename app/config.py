import configparser
import os
import logging
from pathlib import Path

logger = logging.getLogger('TorrentMediaSorter')

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_FILE = os.environ.get("CONFIG_PATH", str(BASE_DIR / 'data' / 'config.ini'))

class ConfigManager:
    def __init__(self, config_path):
        self.config_path = config_path
        self.config = configparser.ConfigParser()
        self.load()

    def load(self):
        if os.path.exists(self.config_path):
            self.config.read(self.config_path, encoding='utf-8')
        else:
            self._create_default()

    def _create_default(self):
        self.config['PATHS'] = {
            'movies_folder': '~/media/Movies',
            'series_folder': '~/media/Series',
            'games_folder': '~/media/Games',
            'software_folder': '~/media/Software',
            'other_folder': '~/media/Other',
        }
        self.config['LOGGING'] = {
            'log_file': str(BASE_DIR / 'data' / 'sorter.log'),
            'level': 'INFO'
        }
        self.config['SYSTEM'] = {
            'video_extensions': '.mkv,.avi,.mp4',
            'web_password': ''
        }
        self.config['RENAMING'] = {
            'mode': 'move',
            'rename_mode': 'ru',
            'save_original_filename': 'True',
            'hardlinks': 'False',
            'season_folders': 'True'
        }
        self.config['API'] = {
            'use_kp': 'False',
            'kp_api_key': '',
            'use_tmdb': 'False',
            'tmdb_api_key': '',
            'use_tvdb': 'False',
            'tvdb_api_key': '',
            'priority': 'kp,tmdb,tvdb'
        }
        self.config['TELEGRAM'] = {
            'use_telegram': 'False',
            'bot_token': '',
            'chat_id': '',
            'template': '{{ title }} ({{ year }}) - {{ status }}'
        }
        self.config['CLIENT'] = {
            'type': 'transmission',
            'host': 'localhost',
            'port': '9091',
            'username': '',
            'password': ''
        }
        self.save()

    def save(self):
        os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
        with open(self.config_path, 'w', encoding='utf-8') as f:
            self.config.write(f)

    def get(self, section, key, fallback=None):
        return self.config.get(section, key, fallback=fallback)

    def getboolean(self, section, key, fallback=False):
        return self.config.getboolean(section, key, fallback=fallback)

    def set(self, section, key, value):
        if section not in self.config:
            self.config[section] = {}
        self.config[section][key] = str(value)
        self.save()

    def validate(self):
        """Check if crucial settings are still using placeholders."""
        paths_to_check = [
            ('PATHS', 'movies_folder'),
            ('PATHS', 'series_folder'),
            ('PATHS', 'games_folder'),
            ('PATHS', 'software_folder'),
            ('PATHS', 'other_folder'),
        ]
        
        for section, key in paths_to_check:
            val = self.get(section, key, '')
            if not val: continue
            
            p = Path(val).expanduser()
            if not p.exists():
                try:
                    p.mkdir(parents=True, exist_ok=True)
                except Exception as e:
                    logger.error(f"Could not create folder {val}: {e}")
        
        # Check API keys for placeholders
        api_keys = [
            ('API', 'kp_api_key'),
            ('API', 'tmdb_api_key'),
            ('API', 'tvdb_api_key')
        ]
        for section, key in api_keys:
            val = self.get(section, key, '')
            if val and "YOUR_" in val:
                logger.warning(f"API key {key} is still using placeholder value.")

        return True, ""

config_manager = ConfigManager(CONFIG_FILE)
