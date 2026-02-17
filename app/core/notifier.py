import httpx
import jinja2
import logging
from typing import Dict, Any
from ..config import config_manager

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
