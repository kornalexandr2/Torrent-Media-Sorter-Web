import logging
from fastapi import APIRouter, BackgroundTasks, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from ..schemas import WebhookPayload
from ..database import get_db, AsyncSessionLocal
from ..core.processor import processor

router = APIRouter()
logger = logging.getLogger('TorrentMediaSorter')

@router.post("/webhook")
async def webhook(payload: WebhookPayload, background_tasks: BackgroundTasks):
    logger.info(f"--> [WEBHOOK] Received: {payload.torrent_name}")
    
    # Run in background to not block the torrent client
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
