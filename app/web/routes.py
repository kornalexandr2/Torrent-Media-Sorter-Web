import os
import logging
from pathlib import Path
from fastapi import APIRouter, Request, Depends, Form, BackgroundTasks
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from typing import List, Optional
from ..database import get_db, AsyncSessionLocal
from ..models import Download, MediaStatus, MediaType
from ..config import config_manager, BASE_DIR
from ..core.operations import file_ops
from ..core.processor import processor

router = APIRouter()
templates = Jinja2Templates(directory=str(BASE_DIR / "app/web/templates"))
logger = logging.getLogger('TorrentMediaSorter')

@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, db: AsyncSession = Depends(get_db)):
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
async def refresh_dashboard(request: Request, db: AsyncSession = Depends(get_db)):
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
async def undo_download(download_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    success, msg = await file_ops.undo_download(download_id, db)
    
    if request.headers.get("HX-Request"):
        return Response(headers={"HX-Redirect": "/"})
    return RedirectResponse(url="/", status_code=303)

@router.post("/retry/{download_id}")
async def retry_download(download_id: int, request: Request, background_tasks: BackgroundTasks, db: AsyncSession = Depends(get_db)):
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
async def download_info(download_id: int, request: Request, db: AsyncSession = Depends(get_db)):
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
        "moves": moves
    })

@router.get("/fix-match/{download_id}", response_class=HTMLResponse)
async def fix_match_form(download_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    stmt = select(Download).where(Download.id == download_id)
    res = await db.execute(stmt)
    download = res.scalar_one_or_none()
    return templates.TemplateResponse("fix_match_modal.html", {"request": request, "download": download})

@router.post("/fix-match/{download_id}")
async def fix_match_apply(
    download_id: int, 
    background_tasks: BackgroundTasks,
    request: Request,
    media_type: str = Form(...),
    source: str = Form(...),
    source_id: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db)
):
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
async def settings(request: Request):
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
        "app_port": os.environ.get("APP_PORT", "7887")
    })

@router.post("/settings/save")
async def save_settings(request: Request):
    form_data = await request.form()
    
    # List of expected checkboxes to handle "off" state
    checkboxes = [
        ('RENAMING', 'save_original_filename'),
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

@router.get("/scan", response_class=HTMLResponse)
async def scan_form(request: Request):
    from ..core.clients import get_client
    client = get_client()
    default_path = ""
    if client:
        try:
            default_path = await client.get_default_download_dir() or ""
        except:
            pass
            
    return f"""
    <div id="modal-container" class="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
        <div class="bg-white rounded-xl shadow-xl w-full max-w-md p-6 relative">
            <h3 class="text-xl font-bold mb-4">Ручное сканирование</h3>
            <form hx-post="/scan" hx-target="#scan-btn" hx-swap="outerHTML">
                <div class="mb-4">
                    <label class="block text-sm font-medium text-gray-700 mb-1">Путь к папке</label>
                    <input type="text" name="path" value="{default_path}" placeholder="/mnt/downloads/..." required
                           class="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500">
                </div>
                <div class="flex justify-end gap-3">
                    <button type="button" onclick="document.getElementById('modal-container').remove()" 
                            class="px-4 py-2 bg-gray-100 hover:bg-gray-200 rounded-lg text-gray-700 transition">
                        Отмена
                    </button>
                    <button type="submit" id="scan-btn" class="px-6 py-2 bg-blue-600 hover:bg-blue-700 text-white font-bold rounded-lg transition">
                        Запустить сканирование
                    </button>
                </div>
            </form>
        </div>
    </div>
    """

@router.post("/scan")
async def run_manual_scan(request: Request, background_tasks: BackgroundTasks, path: str = Form(...)):
    if not os.path.exists(path):
        return f'<button class="px-6 py-2 bg-red-100 text-red-700 font-bold rounded-lg w-full">Путь не найден!</button>'
    
    background_tasks.add_task(perform_manual_scan, path)
    
    # Return a response that closes the modal and refreshes the page via HTMX headers
    response = Response(status_code=204) # No content
    response.headers["HX-Trigger"] = "scan-started"
    response.headers["HX-Refresh"] = "true"
    return response

async def perform_manual_scan(scan_path: str):
    path = Path(scan_path).resolve()
    logger.info(f"--> [SCAN] Starting manual scan of: {path}")
    
    if not path.exists():
        logger.error(f"--> [SCAN] Path does not exist: {path}")
        return

    async with AsyncSessionLocal() as db:
        try:
            # If it's a directory, we can scan top-level items
            if path.is_dir():
                items = list(path.iterdir())
                logger.info(f"--> [SCAN] Found {len(items)} items in directory")
                for item in items:
                    # Process only directories or video files
                    if item.is_dir() or item.suffix.lower() in ('.mkv', '.avi', '.mp4'):
                        logger.info(f"--> [SCAN] Processing item: {item.name}")
                        await processor.process_torrent(
                            db,
                            torrent_name=item.name,
                            torrent_dir=str(item.parent)
                        )
            else:
                # Single file scan
                logger.info(f"--> [SCAN] Processing single file: {path.name}")
                await processor.process_torrent(
                    db,
                    torrent_name=path.name,
                    torrent_dir=str(path.parent)
                )
            logger.info(f"--> [SCAN] Manual scan completed")
        except Exception as e:
            logger.error(f"--> [SCAN] Error during manual scan: {e}", exc_info=True)
