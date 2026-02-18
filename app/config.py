import configparser
import os
import logging
from pathlib import Path

logger = logging.getLogger('TorrentMediaSorter')

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_FILE = os.environ.get("CONFIG_PATH", str(BASE_DIR / 'config.ini'))

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
        }
        self.config['LOGGING'] = {
            'log_file': 'config/sorter.log',
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
        movies = self.get('PATHS', 'movies_folder', '')
        series = self.get('PATHS', 'series_folder', '')
        
        if 'change/me' in movies.lower() or 'change/me' in series.lower():
            return False, "Movies or Series folder path is not configured. Please check config.ini."
        
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

        # Check if folders exist
        m_path = Path(movies).expanduser()
        s_path = Path(series).expanduser()
        
        if not m_path.exists():
            try:
                m_path.mkdir(parents=True, exist_ok=True)
            except Exception as e:
                return False, f"Could not create movies folder: {e}"
        
        if not os.access(m_path, os.W_OK):
            return False, f"No write permission to movies folder: {m_path}"
                
        if not s_path.exists():
            try:
                s_path.mkdir(parents=True, exist_ok=True)
            except Exception as e:
                return False, f"Could not create series folder: {e}"
        
        if not os.access(s_path, os.W_OK):
            return False, f"No write permission to series folder: {s_path}"
                
        return True, ""

config_manager = ConfigManager(CONFIG_FILE)
