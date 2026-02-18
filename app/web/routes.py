import os
import logging
import shutil
import uuid
from pathlib import Path
from fastapi import APIRouter, Request, Depends, Form, BackgroundTasks, HTTPException
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from typing import List, Optional
from itsdangerous import URLSafeSerializer
from passlib.context import CryptContext

from ..database import get_db, AsyncSessionLocal
from ..models import Download, MediaStatus, MediaType, User
from ..config import config_manager, BASE_DIR, SECRET_KEY
from ..core.operations import file_ops
from ..core.processor import processor
from ..core.logger import sys_logger

router = APIRouter()
templates = Jinja2Templates(directory=str(BASE_DIR / "app/web/templates"))
logger = logging.getLogger('TorrentMediaSorter')

# Auth logic
serializer = URLSafeSerializer(SECRET_KEY)
pwd_context = CryptContext(schemes=["sha256_crypt", "md5_crypt"], deprecated="auto")

async def get_current_user(request: Request, db: AsyncSession = Depends(get_db)):
    session_id = request.cookies.get("session")
    if not session_id:
        return None
    try:
        username = serializer.loads(session_id)
        stmt = select(User).where(User.username == username)
        res = await db.execute(stmt)
        return res.scalar_one_or_none()
    except:
        return None

def auth_required(func):
    async def wrapper(*args, **kwargs):
        request = kwargs.get('request')
        user = await get_current_user(request, kwargs.get('db'))
        if not user:
            return RedirectResponse(url="/login", status_code=303)
        return await func(*args, **kwargs)
    return wrapper

# Routes
@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

@router.post("/login")
async def login(request: Request, username: str = Form(...), password: str = Form(...), db: AsyncSession = Depends(get_db)):
    stmt = select(User).where(User.username == username)
    res = await db.execute(stmt)
    user = res.scalar_one_or_none()
    
    if user and pwd_context.verify(password, user.password_hash):
        await sys_logger.log(3, "USER", f"Пользователь {username} вошел в систему")
        response = RedirectResponse(url="/", status_code=303)
        response.set_cookie(key="session", value=serializer.dumps(username), httponly=True)
        return response
    
    await sys_logger.log(2, "USER", f"Неудачная попытка входа: {username}")
    return templates.TemplateResponse("login.html", {"request": request, "error": "Неверный логин или пароль"})

@router.get("/logout")
async def logout(request: Request):
    await sys_logger.log(3, "USER", "Пользователь вышел из системы")
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie("session")
    return response

@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    if not user: return RedirectResponse(url="/login", status_code=303)
    await sys_logger.log(3, "USER", "Переход на Дашборд")
    stmt = select(Download).order_by(desc(Download.created_at)).limit(50)
    result = await db.execute(stmt)
    downloads = result.scalars().all()
    
    any_pending = any(d.status == MediaStatus.PENDING.value for d in downloads)
    
    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "downloads": downloads,
        "any_pending": any_pending
    })

@router.post("/refresh")
async def refresh_dashboard(request: Request, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    if not user: return RedirectResponse(url="/login", status_code=303)
    await sys_logger.log(1, "USER", "Запущена синхронизация дашборда")
    from ..core.clients import get_client
    from ..models import FileMove
    from sqlalchemy import delete
    
    # 1. Get default download dir
    client = get_client()
    download_dir = ""
    if client:
        try:
            download_dir = await client.get_default_download_dir()
        except: pass
    
    # 2. Get all downloads from DB
    stmt = select(Download)
    res = await db.execute(stmt)
    downloads = res.scalars().all()
    
    seen_paths = set()
    to_delete_ids = []
    
    for d in downloads:
        # 3. Check if path exists
        if not os.path.exists(d.original_path):
            logger.info(f"--> [REFRESH] Path not found, marking for deletion: {d.original_path}")
            to_delete_ids.append(d.id)
            continue
            
        # 4. Check for duplicates
        if d.original_path in seen_paths:
            logger.info(f"--> [REFRESH] Duplicate found, marking for deletion: {d.original_path}")
            to_delete_ids.append(d.id)
            continue
        
        seen_paths.add(d.original_path)
    
    # 5. Perform deletion
    if to_delete_ids:
        # Delete related file moves first
        await db.execute(delete(FileMove).where(FileMove.download_id.in_(to_delete_ids)))
        # Delete downloads
        await db.execute(delete(Download).where(Download.id.in_(to_delete_ids)))
        await db.commit()
        logger.info(f"--> [REFRESH] Deleted {len(to_delete_ids)} orphaned/duplicate records")

    # 6. Scan for new items in download folder if it exists
    if download_dir and os.path.exists(download_dir):
        path = Path(download_dir)
        for item in path.iterdir():
            if item.is_dir() or item.suffix.lower() in ('.mkv', '.avi', '.mp4'):
                if str(item) not in seen_paths:
                    logger.info(f"--> [REFRESH] New item found, adding: {item.name}")
                    new_dl = Download(
                        torrent_name=item.name,
                        original_path=str(item),
                        status=MediaStatus.PENDING.value
                    )
                    db.add(new_dl)
                    seen_paths.add(str(item))
        await db.commit()

    if request.headers.get("HX-Request"):
        # Redirect or refresh via HTMX
        return Response(headers={"HX-Refresh": "true"})
    return RedirectResponse(url="/", status_code=303)


@router.post("/undo/{download_id}")
async def undo_download(download_id: int, request: Request, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    if not user: return RedirectResponse(url="/login", status_code=303)
    await sys_logger.log(1, "USER", f"Запрошен откат объекта {download_id}")
    success, msg = await file_ops.undo_download(download_id, db)
    
    if request.headers.get("HX-Request"):
        return Response(headers={"HX-Redirect": "/"})
    return RedirectResponse(url="/", status_code=303)

@router.post("/retry/{download_id}")
async def retry_download(download_id: int, request: Request, background_tasks: BackgroundTasks, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    if not user: return RedirectResponse(url="/login", status_code=303)
    await sys_logger.log(1, "USER", f"Запрошен перезапуск объекта {download_id}")
    stmt = select(Download).where(Download.id == download_id)
    res = await db.execute(stmt)
    download = res.scalar_one_or_none()
    
    if download:
        # Check if original path exists
        if os.path.exists(download.original_path):
            download.status = MediaStatus.PENDING.value
            await db.commit()
            
            background_tasks.add_task(run_retry_task, download.id)
            if request.headers.get("HX-Request"):
                return Response(headers={"HX-Redirect": "/"})
            return RedirectResponse(url="/", status_code=303)
            
    if request.headers.get("HX-Request"):
        return Response(headers={"HX-Redirect": "/"})
    return RedirectResponse(url="/", status_code=303)

async def run_retry_task(download_id: int):
    async with AsyncSessionLocal() as db:
        stmt = select(Download).where(Download.id == download_id)
        res = await db.execute(stmt)
        download = res.scalar_one_or_none()
        if download:
            # Re-process from original path
            p = Path(download.original_path)
            await processor.process_torrent(
                db, 
                torrent_name=p.name, 
                torrent_dir=str(p.parent),
                download_id=download.id
            )

@router.get("/info/{download_id}", response_class=HTMLResponse)
async def download_info(download_id: int, request: Request, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    if not user: return Response("Unauthorized", status_code=401)
    await sys_logger.log(3, "USER", f"Просмотр информации об объекте {download_id}")
    from ..models import FileMove
    stmt = select(Download).where(Download.id == download_id)
    res = await db.execute(stmt)
    download = res.scalar_one_or_none()
    
    if not download:
        return "Not found"
        
    stmt_moves = select(FileMove).where(FileMove.download_id == download_id)
    res_moves = await db.execute(stmt_moves)
    moves = res_moves.scalars().all()
    
    return templates.TemplateResponse("info_modal.html", {
        "request": request, 
        "download": download,
        "moves": moves,
        "user": user
    })

@router.get("/fix-match/{download_id}", response_class=HTMLResponse)
async def fix_match_form(download_id: int, request: Request, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    if not user: return Response("Unauthorized", status_code=401)
    await sys_logger.log(3, "USER", f"Открытие формы исправления сопоставления {download_id}")
    stmt = select(Download).where(Download.id == download_id)
    res = await db.execute(stmt)
    download = res.scalar_one_or_none()
    return templates.TemplateResponse("fix_match_modal.html", {"request": request, "download": download, "user": user})

@router.post("/fix-match/{download_id}")
async def fix_match_apply(
    download_id: int, 
    background_tasks: BackgroundTasks,
    request: Request,
    media_type: str = Form(...),
    source: str = Form(...),
    source_id: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user)
):
    if not user: return Response("Unauthorized", status_code=401)
    await sys_logger.log(1, "USER", f"Применено ручное исправление для {download_id}")
    # Set pending status immediately for UI feedback
    stmt = select(Download).where(Download.id == download_id)
    res = await db.execute(stmt)
    download = res.scalar_one_or_none()
    if download:
        download.status = MediaStatus.PENDING.value
        await db.commit()

    background_tasks.add_task(run_fix_match_task, download_id, media_type, source, source_id)
    if request.headers.get("HX-Request"):
        return Response(headers={"HX-Redirect": "/"})
    return RedirectResponse(url="/", status_code=303)

async def run_fix_match_task(download_id: int, media_type: str, source: str, source_id: str):
    async with AsyncSessionLocal() as db:
        # 1. Undo previous if successful/failed
        await file_ops.undo_download(download_id, db)
        
        # 2. Get the download record again
        stmt = select(Download).where(Download.id == download_id)
        res = await db.execute(stmt)
        download = res.scalar_one_or_none()
        
        if download and os.path.exists(download.original_path):
            # 3. Resolve new metadata
            from ..core.metadata import metadata_manager
            
            if source == "none":
                # Manual mode
                api_data = {
                    'title': source_id or Path(download.original_path).name,
                    'titles': {'origin': source_id or Path(download.original_path).name},
                    'year': '',
                    'type': media_type,
                    'source': 'manual',
                    'source_id': ''
                }
            else:
                api_data = await metadata_manager.resolve_by_id(source, source_id, media_type)
            
            if api_data:
                p = Path(download.original_path)
                await processor.process_torrent(
                    db, 
                    torrent_name=p.name, 
                    torrent_dir=str(p.parent),
                    override_meta=api_data,
                    download_id=download_id
                )

@router.get("/settings", response_class=HTMLResponse)
async def settings(request: Request, user: User = Depends(get_current_user)):
    if not user: return RedirectResponse(url="/login", status_code=303)
    await sys_logger.log(3, "USER", "Переход в настройки")
    sections = config_manager.config.sections()
    config_data = {}
    for s in sections:
        config_data[s] = dict(config_manager.config[s])
    
    # Load masks
    masks_movies_path = BASE_DIR / 'data' / 'masks_movies.txt'
    masks_series_path = BASE_DIR / 'data' / 'masks_series.txt'
    
    # Ensure nested dictionary access for templates
    formatted_config = {}
    for section in config_manager.config.sections():
        formatted_config[section] = dict(config_manager.config[section])
    
    def read_file(p):
        if os.path.exists(p):
            with open(p, 'r', encoding='utf-8') as f:
                return f.read()
        return ""
        
    return templates.TemplateResponse("settings.html", {
        "request": request,
        "config": formatted_config,
        "masks_movies": read_file(masks_movies_path),
        "masks_series": read_file(masks_series_path),
        "base_dir": str(BASE_DIR),
        "app_port": os.environ.get("APP_PORT", "7887"),
        "user": user
    })

@router.get("/logs", response_class=HTMLResponse)
async def view_logs(request: Request, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    if not user: return RedirectResponse(url="/login", status_code=303)
    await sys_logger.log(3, "USER", "Просмотр системных логов")
    from ..models import SystemLog
    from sqlalchemy import select, desc
    stmt = select(SystemLog).order_by(desc(SystemLog.timestamp)).limit(200)
    res = await db.execute(stmt)
    logs = res.scalars().all()
    return templates.TemplateResponse("logs_view.html", {"request": request, "logs": logs, "user": user})

@router.post("/settings/save")
async def save_settings(request: Request, user: User = Depends(get_current_user)):
    if not user: return RedirectResponse(url="/login", status_code=303)
    await sys_logger.log(1, "USER", "Сохранение настроек")
    form_data = await request.form()
    
    # List of expected checkboxes to handle "off" state
    checkboxes = [
        ('RENAMING', 'season_folders'),
        ('API', 'use_kp'),
        ('API', 'use_tmdb'),
        ('API', 'use_tvdb'),
        ('TELEGRAM', 'use_telegram'),
    ]
    
    # Reset all checkboxes first or just handle them
    for section, key in checkboxes:
        full_key = f"{section}.{key}"
        if full_key in form_data:
            config_manager.set(section, key, "True")
        else:
            config_manager.set(section, key, "False")

    # Update other fields
    for key, value in form_data.items():
        if '.' in key:
            section, k = key.split('.', 1)
            # Skip if it's a checkbox we already handled
            if (section, k) in checkboxes:
                continue
            
            old_val = config_manager.get(section, k)
            if str(old_val) != str(value):
                await sys_logger.log(3, "USER", f"Изменен параметр {section}.{k}: {old_val} -> {value}")
            
            config_manager.set(section, k, value)
            
    # Save masks
    masks_movies = form_data.get('masks_movies', '')
    masks_series = form_data.get('masks_series', '')
    
    with open(BASE_DIR / 'data' / 'masks_movies.txt', 'w', encoding='utf-8') as f:
        f.write(str(masks_movies))
    with open(BASE_DIR / 'data' / 'masks_series.txt', 'w', encoding='utf-8') as f:
        f.write(str(masks_series))
        
    config_manager.save()
    if request.headers.get("HX-Request"):
        return Response(headers={"HX-Redirect": "/settings"})
    return RedirectResponse(url="/settings", status_code=303)

@router.post("/settings/password")
async def change_password(
    request: Request, 
    old_password: str = Form(...), 
    new_password: str = Form(...), 
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user)
):
    if not user: return Response("Unauthorized", status_code=401)
    
    if not pwd_context.verify(old_password, user.password_hash):
        return f'<div class="p-4 bg-red-50 border border-red-100 rounded-xl text-red-700 text-sm">❌ Старый пароль неверен</div>'
    
    user.password_hash = pwd_context.hash(new_password)
    await db.commit()
    await sys_logger.log(1, "USER", f"Пользователь {user.username} изменил пароль")
    
    return f'<div class="p-4 bg-green-50 border border-green-100 rounded-xl text-green-700 text-sm">✅ Пароль успешно изменен</div>'

@router.get("/scan", response_class=HTMLResponse)
async def scan_form(request: Request, user: User = Depends(get_current_user)):
    if not user: return Response("Unauthorized", status_code=401)
    await sys_logger.log(3, "USER", "Открытие формы сканирования")
    download_dir = config_manager.get('PATHS', 'downloads_folder')
    return f"""
    <div id="modal-container" class="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
        <div class="bg-white rounded-2xl shadow-xl w-full max-w-lg overflow-hidden flex flex-col">
            <div class="px-6 py-4 bg-gray-50 border-b border-gray-200 flex justify-between items-center">
                <h3 class="text-xl font-bold text-gray-800">Ручное сканирование</h3>
                <button onclick="document.getElementById('modal-container').remove()" class="text-gray-400 hover:text-gray-600">&times;</button>
            </div>
            
            <div id="scan-content" class="p-6">
                <p class="text-sm text-gray-600 mb-4 font-mono bg-gray-50 p-2 rounded">Папка: {download_dir}</p>
                <div class="space-y-4">
                    <p class="text-sm text-gray-700">Начать поиск новых файлов и поиск пустых папок в настроенной директории?</p>
                    <div class="flex justify-end gap-3">
                        <button type="button" onclick="document.getElementById('modal-container').remove()" 
                                class="px-4 py-2 bg-gray-100 hover:bg-gray-200 rounded-xl text-gray-700 transition">
                            Отмена
                        </button>
                        <button hx-post="/scan" 
                                hx-target="#scan-content" 
                                class="px-6 py-2 bg-indigo-600 hover:bg-indigo-700 text-white font-bold rounded-xl transition">
                            Начать поиск
                        </button>
                    </div>
                </div>
            </div>
        </div>
    </div>
    """

@router.post("/scan", response_class=HTMLResponse)
async def run_manual_scan(request: Request, user: User = Depends(get_current_user)):
    if not user: return Response("Unauthorized", status_code=401)
    await sys_logger.log(1, "USER", "Запущено ручное сканирование папки")
    path = config_manager.get('PATHS', 'downloads_folder')
    if not path or not os.path.exists(path):
        return f'<div class="text-red-500 font-bold p-4">Ошибка: Папка {path} не найдена</div>'
    
    # Return loading state that immediately triggers the actual scan
    return f"""
    <div class="flex flex-col items-center justify-center py-12 space-y-4" 
         hx-get="/scan/perform" 
         hx-trigger="load" 
         hx-target="#scan-content">
        <div class="animate-spin rounded-full h-12 w-12 border-b-2 border-indigo-600"></div>
        <p class="text-indigo-600 font-bold">Идет сканирование...</p>
        <p class="text-xs text-gray-400">Пожалуйста, не закрывайте окно</p>
    </div>
    """

def is_folder_empty_recursive(path: Path):
    if not path.is_dir(): return False
    for item in path.iterdir():
        if item.is_file(): return False
        if not is_folder_empty_recursive(item): return False
    return True

@router.get("/scan/perform", response_class=HTMLResponse)
async def perform_scan_and_return_results(request: Request, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    if not user: return Response("Unauthorized", status_code=401)
    scan_path = config_manager.get('PATHS', 'downloads_folder')
    path = Path(scan_path).resolve()
    
    results = {"processed": [], "empty_folders": []}
    
    # 1. Process items
    try:
        items = list(path.iterdir())
        for item in items:
            if item.is_dir() or item.suffix.lower() in ('.mkv', '.avi', '.mp4'):
                await processor.process_torrent(db, torrent_name=item.name, torrent_dir=str(item.parent))
                results["processed"].append(item.name)
        
        # 2. Find empty folders (Top-level only)
        for item in path.iterdir():
            if item.is_dir() and is_folder_empty_recursive(item):
                results["empty_folders"].append(str(item))
                
    except Exception as e:
        logger.error(f"Scan error: {e}")
        return f'<div class="text-red-500">Ошибка при сканировании: {e}</div>'

    # 3. Render Results
    processed_list = "".join([f'<li class="truncate text-gray-600">• {n}</li>' for n in results["processed"][:10]])
    if len(results["processed"]) > 10: processed_list += f'<li class="text-gray-400 italic">...и еще {len(results["processed"])-10}</li>'
    
    empty_folders_section = ""
    if results["empty_folders"]:
        folders_json = ",".join([f'"{f}"' for f in results["empty_folders"]])
        empty_folders_section = f"""
        <div class="mt-6 p-4 bg-amber-50 border border-amber-100 rounded-xl">
            <h4 class="text-sm font-bold text-amber-800 mb-2">Найдено пустых папок: {len(results["empty_folders"])}</h4>
            <div class="max-h-32 overflow-y-auto mb-4 text-xs font-mono text-amber-700 space-y-1">
                {"".join([f'<div>{Path(f).name}/</div>' for f in results["empty_folders"]])}
            </div>
            <button hx-post="/scan/cleanup" 
                    hx-vals='{{"folders": [{folders_json}]}}'
                    hx-target="closest div"
                    hx-confirm="Вы уверены, что хотите удалить эти папки?"
                    class="w-full py-2 bg-amber-600 hover:bg-amber-700 text-white text-xs font-bold rounded-lg transition">
                🗑 Удалить пустые папки
            </button>
        </div>
        """

    return f"""
    <div class="space-y-4">
        <div class="p-4 bg-green-50 border border-green-100 rounded-xl">
            <h4 class="text-sm font-bold text-green-800 mb-2">✅ Сканирование завершено</h4>
            <p class="text-xs text-green-700 mb-2">Обработано объектов: {len(results["processed"])}</p>
            <ul class="text-[10px] space-y-1">
                {processed_list or '<li class="text-gray-400">Новых объектов не найдено</li>'}
            </ul>
        </div>
        {empty_folders_section}
        <button onclick="window.location.reload()" class="w-full py-3 bg-gray-800 text-white font-bold rounded-xl hover:bg-black transition">
            Закрыть и обновить список
        </button>
    </div>
    """

@router.post("/scan/cleanup", response_class=HTMLResponse)
async def cleanup_folders(request: Request, user: User = Depends(get_current_user)):
    if not user: return Response("Unauthorized", status_code=401)
    form_data = await request.form()
    folders = form_data.getlist("folders")
    await sys_logger.log(1, "USER", f"Удаление пустых папок ({len(folders)} шт)")
    
    deleted = 0
    errors = 0
    
    logger.info(f"--> [CLEANUP] Starting cleanup of {len(folders)} folders")
    
    for folder in folders:
        try:
            p = Path(folder).resolve()
            if p.exists() and p.is_dir():
                shutil.rmtree(p)
                deleted += 1
                logger.info(f"--> [CLEANUP] Deleted: {p}")
            else:
                logger.warning(f"--> [CLEANUP] Skip (not a dir or missing): {p}")
                errors += 1
        except Exception as e:
            logger.error(f"--> [CLEANUP] Error deleting {folder}: {e}")
            errors += 1
            
    return f"""
    <div class="p-4 bg-blue-50 border border-blue-100 rounded-xl text-center">
        <p class="text-sm font-bold text-blue-800">🗑 Очистка завершена</p>
        <p class="text-xs text-blue-600">Удалено папок: {deleted} {"(Ошибок: "+str(errors)+")" if errors else ""}</p>
    </div>
    """
