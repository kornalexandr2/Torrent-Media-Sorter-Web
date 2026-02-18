import logging
import os
import asyncio
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from .database import engine, Base
from .web.routes import router as web_router
from .api.webhook import router as webhook_router
from .core.logger import sys_logger

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger('TorrentMediaSorter')

app = FastAPI(title="Torrent Media Sorter")

async def log_cleanup_task():
    while True:
        try:
            await sys_logger.cleanup()
            logger.info("Executed periodic log cleanup")
        except Exception as e:
            logger.error(f"Error in log cleanup task: {e}")
        await asyncio.sleep(12 * 3600) # Every 12 hours

# Создание таблиц при старте
@app.on_event("startup")
async def startup():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    asyncio.create_task(log_cleanup_task())

# Подключение роутов
app.include_router(web_router)
app.include_router(webhook_router, prefix="/api")

# Статика (если есть)
static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")
