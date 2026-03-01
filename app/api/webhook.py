import logging
import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, Form, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession
from ..schemas import WebhookPayload
from ..database import get_db, AsyncSessionLocal
from ..core.processor import processor
from ..core.logger import sys_logger
from ..core.i18n import translator

router = APIRouter()
logger = logging.getLogger('TorrentMediaSorter')

def get_lang(request: Request):
    return request.cookies.get("lang", "ru")

@router.post("/webhook")
async def webhook(payload: WebhookPayload, background_tasks: BackgroundTasks):
    await sys_logger.log(1, "SCRIPT", "log_proc_start", details=f"name: {payload.torrent_name}")
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
async def test_kp(request: Request, api_key: str = Form(None, alias="API.kp_api_key")):
    lang = get_lang(request)
    if not api_key: return f'<p class="text-xs text-red-500">{translator.translate("key_not_entered", lang=lang)}</p>'
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                "https://kinopoiskapiunofficial.tech/api/v2.2/films/collections?type=TOP_POPULAR_MOVIES&page=1",
                headers={"X-API-KEY": api_key},
                timeout=5.0
            )
            if resp.status_code == 200:
                return f'<p class="text-xs text-green-600">✅ {translator.translate("connection_success", lang=lang)}</p>'
            return f'<p class="text-xs text-red-500">❌ {translator.translate("error_with_code", lang=lang, code=resp.status_code)}</p>'
    except Exception as e:
        return f'<p class="text-xs text-red-500">❌ {str(e)}</p>'

@router.post("/test/tmdb", response_class=HTMLResponse)
async def test_tmdb(request: Request, api_key: str = Form(None, alias="API.tmdb_api_key")):
    lang = get_lang(request)
    if not api_key: return f'<p class="text-xs text-red-500">{translator.translate("key_not_entered", lang=lang)}</p>'
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"https://api.themoviedb.org/3/movie/popular?api_key={api_key}&language=ru-RU&page=1",
                timeout=5.0
            )
            if resp.status_code == 200:
                return f'<p class="text-xs text-green-600">✅ {translator.translate("connection_success", lang=lang)}</p>'
            return f'<p class="text-xs text-red-500">❌ {translator.translate("error_with_code", lang=lang, code=resp.status_code)}</p>'
    except Exception as e:
        return f'<p class="text-xs text-red-500">❌ {str(e)}</p>'

@router.post("/test/tvdb", response_class=HTMLResponse)
async def test_tvdb(request: Request, api_key: str = Form(None, alias="API.tvdb_api_key")):
    lang = get_lang(request)
    if not api_key: return f'<p class="text-xs text-red-500">{translator.translate("key_not_entered", lang=lang)}</p>'
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "https://api4.thetvdb.com/v4/login",
                json={"apikey": api_key},
                timeout=5.0
            )
            if resp.status_code == 200:
                return f'<p class="text-xs text-green-600">✅ {translator.translate("connection_success", lang=lang)}</p>'
            return f'<p class="text-xs text-red-500">❌ {translator.translate("error_with_code", lang=lang, code=resp.status_code)}</p>'
    except Exception as e:
        return f'<p class="text-xs text-red-500">❌ {str(e)}</p>'

@router.post("/test/igdb", response_class=HTMLResponse)
async def test_igdb(
    request: Request, 
    client_id: str = Form(None, alias="API.igdb_client_id"),
    client_secret: str = Form(None, alias="API.igdb_client_secret")
):
    lang = get_lang(request)
    if not client_id or not client_secret: 
        return f'<p class="text-xs text-red-500">{translator.translate("key_not_entered", lang=lang)}</p>'
    try:
        url = f"https://id.twitch.tv/oauth2/token?client_id={client_id}&client_secret={client_secret}&grant_type=client_credentials"
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, timeout=5.0)
            if resp.status_code == 200:
                return f'<p class="text-xs text-green-600">✅ {translator.translate("connection_success", lang=lang)}</p>'
            return f'<p class="text-xs text-red-500">❌ {translator.translate("error_with_code", lang=lang, code=resp.status_code)}</p>'
    except Exception as e:
        return f'<p class="text-xs text-red-500">❌ {str(e)}</p>'

@router.post("/test/telegram", response_class=HTMLResponse)
async def test_telegram(
    request: Request,
    token: str = Form(None, alias="TELEGRAM.bot_token"),
    chat_id: str = Form(None, alias="TELEGRAM.chat_id")
):
    lang = get_lang(request)
    if not token or not chat_id: return f'<p class="text-sm text-red-500">{translator.translate("enter_token_chatid", lang=lang)}</p>'
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": translator.translate("test_msg_content", lang=lang)},
                timeout=5.0
            )
            if resp.status_code == 200:
                return f'<div class="p-2 bg-green-50 border border-green-200 rounded text-sm text-green-700">✅ {translator.translate("test_msg_sent", lang=lang)}</div>'
            return f'<div class="p-2 bg-red-50 border border-red-200 rounded text-sm text-red-700">❌ Error TG: {resp.text}</div>'
    except Exception as e:
        return f'<div class="p-2 bg-red-50 border border-red-200 rounded text-sm text-red-700">❌ Error: {str(e)}</div>'

@router.post("/test/client", response_class=HTMLResponse)
async def test_client(
    request: Request,
    client_type: str = Form(..., alias="CLIENT.type"),
    host: str = Form(..., alias="CLIENT.host"),
    port: str = Form(..., alias="CLIENT.port"),
    username: str = Form(None, alias="CLIENT.username"),
    password: str = Form(None, alias="CLIENT.password")
):
    lang = get_lang(request)
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
                    return f'<p class="text-xs text-green-600">✅ Transmission: {translator.translate("connection_success", lang=lang)}</p>'
                return f'<p class="text-xs text-red-500">❌ {translator.translate("error_with_code", lang=lang, code=resp.status_code)}</p>'

        elif client_type == "qbittorrent":
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    f"http://{host}:{port}/api/v2/auth/login",
                    data={"username": username, "password": password},
                    timeout=5.0
                )
                if resp.status_code == 200 and "Ok" in resp.text:
                    return f'<p class="text-xs text-green-600">✅ qBittorrent: {translator.translate("auth_success", lang=lang)}</p>'
                return f'<p class="text-xs text-red-500">❌ {translator.translate("error_with_code", lang=lang, code=resp.status_code)}: {resp.text}</p>'
        
        return f'<p class="text-xs text-gray-500">{translator.translate("test_not_supported", lang=lang)}</p>'
    except Exception as e:
        return f'<p class="text-xs text-red-500">❌ Error: {str(e)}</p>'

@router.get("/client/path", response_class=HTMLResponse)
async def get_client_path(request: Request):
    from ..core.clients import get_client
    from ..config import config_manager
    lang = get_lang(request)
    client = get_client()
    if not client:
        return f'<button type="button" disabled class="px-4 py-2 bg-gray-100 text-gray-400 text-xs font-bold rounded-lg cursor-not-allowed">{translator.translate("no_client_error", lang=lang)}</button>'
    
    try:
        path = await client.get_default_download_dir()
        if path:
            # Return a button that uses a simple JS to fill the input
            return f"""
            <button type="button" 
                    onclick="document.getElementById('downloads_folder_input').value = '{path}'"
                    class="px-4 py-2 bg-indigo-100 text-indigo-700 hover:bg-indigo-200 text-xs font-bold rounded-lg transition">
                {translator.translate("dashboard", lang=lang)} {config_manager.get('CLIENT', 'type', '').capitalize()}
            </button>
            """
    except: pass
    
    return f'<button type="button" disabled class="px-4 py-2 bg-gray-100 text-gray-400 text-xs font-bold rounded-lg cursor-not-allowed">{translator.translate("comm_error", lang=lang)}</button>'
