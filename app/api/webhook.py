import logging
import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, Form
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession
from ..schemas import WebhookPayload
from ..database import get_db, AsyncSessionLocal
from ..core.processor import processor
from ..core.logger import sys_logger

router = APIRouter()
logger = logging.getLogger('TorrentMediaSorter')

@router.post("/webhook")
async def webhook(payload: WebhookPayload, background_tasks: BackgroundTasks):
    await sys_logger.log(1, "SCRIPT", f"Получен вебхук для торрента: {payload.torrent_name}")
    logger.info(f"--> [WEBHOOK] Received: {payload.torrent_name}")
    
    # Запуск в фоне, чтобы не блокировать клиент
    background_tasks.add_task(run_processing, payload)
    
    return {"status": "queued"}

async def run_processing(payload: WebhookPayload):
    async with AsyncSessionLocal() as db:
        await processor.process_torrent(
            db, 
            torrent_id=payload.torrent_id, 
            torrent_name=payload.torrent_name, 
            torrent_dir=payload.torrent_dir
        )

# --- API Test Endpoints ---

@router.post("/test/kinopoisk", response_class=HTMLResponse)
async def test_kp(api_key: str = Form(None, alias="API.kp_api_key")):
    if not api_key: return '<p class="text-xs text-red-500">Ключ не введен</p>'
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                "https://kinopoiskapiunofficial.tech/api/v2.2/films/collections?type=TOP_POPULAR_MOVIES&page=1",
                headers={"X-API-KEY": api_key},
                timeout=5.0
            )
            if resp.status_code == 200:
                return '<p class="text-xs text-green-600">✅ Соединение успешно</p>'
            return f'<p class="text-xs text-red-500">❌ Ошибка {resp.status_code}</p>'
    except Exception as e:
        return f'<p class="text-xs text-red-500">❌ {str(e)}</p>'

@router.post("/test/tmdb", response_class=HTMLResponse)
async def test_tmdb(api_key: str = Form(None, alias="API.tmdb_api_key")):
    if not api_key: return '<p class="text-xs text-red-500">Ключ не введен</p>'
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"https://api.themoviedb.org/3/movie/popular?api_key={api_key}&language=ru-RU&page=1",
                timeout=5.0
            )
            if resp.status_code == 200:
                return '<p class="text-xs text-green-600">✅ Соединение успешно</p>'
            return f'<p class="text-xs text-red-500">❌ Ошибка {resp.status_code}</p>'
    except Exception as e:
        return f'<p class="text-xs text-red-500">❌ {str(e)}</p>'

@router.post("/test/tvdb", response_class=HTMLResponse)
async def test_tvdb(api_key: str = Form(None, alias="API.tvdb_api_key")):
    if not api_key: return '<p class="text-xs text-red-500">Ключ не введен</p>'
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "https://api4.thetvdb.com/v4/login",
                json={"apikey": api_key},
                timeout=5.0
            )
            if resp.status_code == 200:
                return '<p class="text-xs text-green-600">✅ Соединение успешно</p>'
            return f'<p class="text-xs text-red-500">❌ Ошибка {resp.status_code}</p>'
    except Exception as e:
        return f'<p class="text-xs text-red-500">❌ {str(e)}</p>'

@router.post("/test/telegram", response_class=HTMLResponse)
async def test_telegram(
    token: str = Form(None, alias="TELEGRAM.bot_token"),
    chat_id: str = Form(None, alias="TELEGRAM.chat_id")
):
    if not token or not chat_id: return '<p class="text-sm text-red-500">Введите Token и Chat ID</p>'
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": "🔔 Тестовое сообщение от Torrent Media Sorter. Настройки верны!"},
                timeout=5.0
            )
            if resp.status_code == 200:
                return '<div class="p-2 bg-green-50 border border-green-200 rounded text-sm text-green-700">✅ Тестовое сообщение отправлено!</div>'
            return f'<div class="p-2 bg-red-50 border border-red-200 rounded text-sm text-red-700">❌ Ошибка TG: {resp.text}</div>'
    except Exception as e:
        return f'<div class="p-2 bg-red-50 border border-red-200 rounded text-sm text-red-700">❌ Ошибка: {str(e)}</div>'

@router.post("/test/client", response_class=HTMLResponse)
async def test_client(
    client_type: str = Form(..., alias="CLIENT.type"),
    host: str = Form(..., alias="CLIENT.host"),
    port: str = Form(..., alias="CLIENT.port"),
    username: str = Form(None, alias="CLIENT.username"),
    password: str = Form(None, alias="CLIENT.password")
):
    try:
        if client_type == "transmission":
            auth = None
            if username and password:
                import base64
                encoded_auth = base64.b64encode(f"{username}:{password}".encode()).decode()
                auth = {"Authorization": f"Base {encoded_auth}"}
            
            async with httpx.AsyncClient() as client:
                # First try to get session ID
                resp = await client.post(f"http://{host}:{port}/transmission/rpc", headers=auth, timeout=5.0)
                if resp.status_code == 409:
                    session_id = resp.headers.get("X-Transmission-Session-Id")
                    headers = auth or {}
                    headers["X-Transmission-Session-Id"] = session_id
                    resp = await client.post(
                        f"http://{host}:{port}/transmission/rpc", 
                        json={"method": "session-get"}, 
                        headers=headers, 
                        timeout=5.0
                    )
                
                if resp.status_code == 200:
                    return '<p class="text-xs text-green-600">✅ Transmission: Соединение успешно</p>'
                return f'<p class="text-xs text-red-500">❌ Ошибка {resp.status_code}</p>'

        elif client_type == "qbittorrent":
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    f"http://{host}:{port}/api/v2/auth/login",
                    data={"username": username, "password": password},
                    timeout=5.0
                )
                if resp.status_code == 200 and "Ok" in resp.text:
                    return '<p class="text-xs text-green-600">✅ qBittorrent: Авторизация успешна</p>'
                return f'<p class="text-xs text-red-500">❌ Ошибка {resp.status_code}: {resp.text}</p>'
        
        return '<p class="text-xs text-gray-500">Тест не поддерживается для этого клиента</p>'
    except Exception as e:
        return f'<p class="text-xs text-red-500">❌ Ошибка: {str(e)}</p>'

@router.get("/client/path", response_class=HTMLResponse)
async def get_client_path():
    from ..core.clients import get_client
    from ..config import config_manager
    client = get_client()
    if not client:
        return '<button type="button" disabled class="px-4 py-2 bg-gray-100 text-gray-400 text-xs font-bold rounded-lg cursor-not-allowed">Загрузки (нет клиента)</button>'
    
    try:
        path = await client.get_default_download_dir()
        if path:
            # Return a button that uses a simple JS to fill the input
            return f"""
            <button type="button" 
                    onclick="document.getElementById('downloads_folder_input').value = '{path}'"
                    class="px-4 py-2 bg-indigo-100 text-indigo-700 hover:bg-indigo-200 text-xs font-bold rounded-lg transition">
                Загрузки {config_manager.get('CLIENT', 'type', '').capitalize()}
            </button>
            """
    except: pass
    
    return '<button type="button" disabled class="px-4 py-2 bg-gray-100 text-gray-400 text-xs font-bold rounded-lg cursor-not-allowed">Загрузки (ошибка связи)</button>'
