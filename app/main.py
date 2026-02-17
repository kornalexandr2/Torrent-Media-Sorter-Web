import logging
import sys
import os
from fastapi import FastAPI, Request, BackgroundTasks, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
from contextlib import asynccontextmanager
from sqlalchemy.ext.asyncio import AsyncSession
from .database import init_db, get_db
from .api.webhook import router as webhook_router
from .web.routes import router as web_router
from .config import BASE_DIR, config_manager

# Configure logging
log_file = config_manager.get('LOGGING', 'log_file', 'config/sorter.log')
log_level = config_manager.get('LOGGING', 'level', 'INFO').upper()
os.makedirs(os.path.dirname(BASE_DIR / log_file), exist_ok=True)

logging.basicConfig(
    level=getattr(logging, log_level),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(str(BASE_DIR / log_file)),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger('TorrentMediaSorter')

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup validation
    is_valid, error_msg = config_manager.validate()
    if not is_valid:
        logger.critical(f"Configuration error: {error_msg}")
        # We don't exit here to allow user to access settings page and fix the issue.
    
    try:
        await init_db()
        logger.info("Database initialized successfully.")
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")
        # In a real app, you might want to stop startup here
        
    yield
    # Shutdown
    pass

app = FastAPI(
    title="Torrent Media Sorter Web",
    version="0.1",
    lifespan=lifespan
)

# Static files and templates
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

# Include routers
app.include_router(webhook_router, prefix="/api")
app.include_router(web_router)

@app.get("/health")
async def health():
    return {"status": "ok"}
