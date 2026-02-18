import httpx
import logging
import base64
from typing import Optional
from ..config import config_manager

logger = logging.getLogger('TorrentMediaSorter')

class TorrentClient:
    async def remove_torrent(self, torrent_id: str) -> bool:
        raise NotImplementedError

    async def get_default_download_dir(self) -> Optional[str]:
        raise NotImplementedError

class TransmissionClient(TorrentClient):
    def __init__(self):
        self.host = config_manager.get('CLIENT', 'host', 'localhost')
        self.port = config_manager.get('CLIENT', 'port', '9091')
        self.username = config_manager.get('CLIENT', 'username', '')
        self.password = config_manager.get('CLIENT', 'password', '')
        self.url = f"http://{self.host}:{self.port}/transmission/rpc"
        self.session_id = ""

    async def _get_headers(self):
        headers = {"X-Transmission-Session-Id": self.session_id}
        if self.username and self.password:
            auth = base64.b64encode(f"{self.username}:{self.password}".encode()).decode()
            headers["Authorization"] = f"Basic {auth}"
        return headers

    async def remove_torrent(self, torrent_id: str) -> bool:
        if not torrent_id:
            return False
        
        payload = {
            "method": "torrent-remove",
            "arguments": {
                "ids": [int(torrent_id) if torrent_id.isdigit() else torrent_id],
                "delete-local-data": False
            }
        }

        async with httpx.AsyncClient() as client:
            for _ in range(2): # Retry once if session-id is invalid
                headers = await self._get_headers()
                try:
                    resp = await client.post(self.url, json=payload, headers=headers, timeout=10.0)
                    if resp.status_code == 409:
                        self.session_id = resp.headers.get("X-Transmission-Session-Id", "")
                        continue
                    if resp.status_code == 200:
                        data = resp.json()
                        return data.get("result") == "success"
                    return False
                except Exception as e:
                    logger.error(f"--> [TRANSMISSION] Request error: {e}")
                    return False
        return False

    async def get_default_download_dir(self) -> Optional[str]:
        payload = {"method": "session-get"}
        async with httpx.AsyncClient() as client:
            for _ in range(2):
                headers = await self._get_headers()
                try:
                    resp = await client.post(self.url, json=payload, headers=headers, timeout=10.0)
                    if resp.status_code == 409:
                        self.session_id = resp.headers.get("X-Transmission-Session-Id", "")
                        continue
                    if resp.status_code == 200:
                        data = resp.json()
                        return data.get("arguments", {}).get("download-dir")
                except:
                    pass
        return None

class QBittorrentClient(TorrentClient):
    def __init__(self):
        self.host = config_manager.get('CLIENT', 'host', 'localhost')
        self.port = config_manager.get('CLIENT', 'port', '8080')
        self.username = config_manager.get('CLIENT', 'username', '')
        self.password = config_manager.get('CLIENT', 'password', '')
        self.base_url = f"http://{self.host}:{self.port}/api/v2"
        self.cookies = None

    async def _login(self, client: httpx.AsyncClient) -> bool:
        try:
            resp = await client.post(
                f"{self.base_url}/auth/login",
                data={"username": self.username, "password": self.password},
                timeout=10.0
            )
            if resp.status_code == 200 and "Ok" in resp.text:
                self.cookies = resp.cookies
                return True
            return False
        except Exception as e:
            logger.error(f"--> [QBITTORRENT] Login error: {e}")
            return False

    async def remove_torrent(self, torrent_id: str) -> bool:
        if not torrent_id:
            return False

        async with httpx.AsyncClient() as client:
            if not self.cookies:
                if not await self._login(client):
                    return False
            
            try:
                # delete-local-data=false is default in qBittorrent delete API
                resp = await client.post(
                    f"{self.base_url}/torrents/delete",
                    params={"hashes": torrent_id, "deleteFiles": "false"},
                    cookies=self.cookies,
                    timeout=10.0
                )
                return resp.status_code == 200
            except Exception as e:
                logger.error(f"--> [QBITTORRENT] Remove error: {e}")
                return False

    async def get_default_download_dir(self) -> Optional[str]:
        async with httpx.AsyncClient() as client:
            if not self.cookies:
                if not await self._login(client):
                    return None
            try:
                resp = await client.get(f"{self.base_url}/app/preferences", cookies=self.cookies, timeout=10.0)
                if resp.status_code == 200:
                    return resp.json().get("save_path")
            except:
                pass
        return None

def get_client() -> Optional[TorrentClient]:
    c_type = config_manager.get('CLIENT', 'type', 'none').lower()
    if c_type == 'transmission':
        return TransmissionClient()
    elif c_type == 'qbittorrent':
        return QBittorrentClient()
    return None
