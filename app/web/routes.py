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
    
    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "downloads": downloads
    })

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
                torrent_dir=str(p.parent)
            )

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
    source_id: str = Form(...),
    db: AsyncSession = Depends(get_db)
):
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
    masks_movies_path = BASE_DIR / 'masks_movies.txt'
    masks_series_path = BASE_DIR / 'masks_series.txt'
    
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
        "masks_series": read_file(masks_series_path)
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
    
    with open(BASE_DIR / 'masks_movies.txt', 'w', encoding='utf-8') as f:
        f.write(str(masks_movies))
    with open(BASE_DIR / 'masks_series.txt', 'w', encoding='utf-8') as f:
        f.write(str(masks_series))
        
    config_manager.save()
    if request.headers.get("HX-Request"):
        return Response(headers={"HX-Redirect": "/settings"})
    return RedirectResponse(url="/settings", status_code=303)
