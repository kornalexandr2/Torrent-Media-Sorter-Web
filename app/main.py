import logging
import os
import asyncio
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from passlib.context import CryptContext
from sqlalchemy import select

from .database import engine, Base, AsyncSessionLocal
from .models import User
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

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

app = FastAPI(title="Torrent Media Sorter")

async def log_cleanup_task():
    while True:
        try:
            await sys_logger.cleanup()
            logger.info("Executed periodic log cleanup")
        except Exception as e:
            logger.error(f"Error in log cleanup task: {e}")
        await asyncio.sleep(12 * 3600) # Every 12 hours

# Создание таблиц и начальных данных при старте
@app.on_event("startup")
async def startup():
    # 1. Create tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    # 2. Create default admin if not exists
    async with AsyncSessionLocal() as db:
        try:
            stmt = select(User).where(User.username == "admin")
            res = await db.execute(stmt)
            if not res.scalar_one_or_none():
                admin = User(
                    username="admin",
                    password_hash=pwd_context.hash("adminadmin1"),
                    is_admin=True
                )
                db.add(admin)
                await db.commit()
                logger.info("Default admin user created")
        except Exception as e:
            logger.error(f"Error creating default user: {e}")

    # 3. Start background tasks
    asyncio.create_task(log_cleanup_task())

# Подключение роутов
app.include_router(web_router)
app.include_router(webhook_router, prefix="/api")

# Статика (если есть)
static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")
