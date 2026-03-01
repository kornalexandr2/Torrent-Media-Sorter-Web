import httpx
import jinja2
import logging
from typing import Dict, Any
from ..config import config_manager
from .i18n import translator

logger = logging.getLogger('TorrentMediaSorter')

class Notifier:
    def __init__(self):
        self.jinja_env = jinja2.Environment()

    async def send_telegram(self, data: Dict[str, Any]):
        use_tg = config_manager.getboolean('TELEGRAM', 'use_telegram', False)
        token = config_manager.get('TELEGRAM', 'bot_token')
        chat_id = config_manager.get('TELEGRAM', 'chat_id')
        template_str = config_manager.get('TELEGRAM', 'template', '{{ title }} ({{ year }}) - {{ status }}')

        if not use_tg or not token or not chat_id or "YOUR_" in token or "YOUR_" in chat_id:
            return

        try:
            # Get current lang from config or default to ru
            lang = config_manager.get('RENAMING', 'rename_mode', 'ru')
            if lang not in ['ru', 'en']: lang = 'ru'

            # Translate type_name if it's a known key
            if 'type_name' in data:
                # Map technical 'tv' to 'series' for translation consistency if needed
                t_key = data['type_name']
                if t_key == 'tv': t_key = 'series'
                data['type_name'] = translator.translate(t_key, lang=lang)

            # Translate status if it's a known key
            if 'status' in data:
                data['status'] = translator.translate(data['status'], lang=lang)

            template = self.jinja_env.from_string(template_str)
            text = template.render(**data)
            
            url = f"https://api.telegram.org/bot{token}/sendMessage"
            payload = {
                'chat_id': chat_id,
                'text': text,
                'parse_mode': 'HTML'
            }
            async with httpx.AsyncClient() as client:
                await client.post(url, json=payload, timeout=10.0)
        except Exception as e:
            logger.error(f"--> [TELEGRAM] Error: {e}")

notifier = Notifier()
