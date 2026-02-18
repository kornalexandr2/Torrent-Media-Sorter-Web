import logging
from datetime import datetime, timedelta
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession
from ..models import SystemLog
from ..config import config_manager
from ..database import AsyncSessionLocal

class SystemLogger:
    # 0: Off, 1: Operations (OP), 2: Errors (ERROR), 3: Full Debug (ALL)
    
    async def log(self, level: int, source: str, message: str, details: str = None):
        try:
            target_level = int(config_manager.get('LOGGING', 'system_log_level', '1'))
        except:
            target_level = 1
            
        # Mapping level to names
        levels = {1: "OP", 2: "ERROR", 3: "DEBUG", 4: "INFO"}
        
        # Logic for filtering
        if target_level == 0: 
            return
            
        if target_level == 1 and level != 1: 
            return
            
        if target_level == 2 and level != 2: 
            return
            
        # Level 3 (Full) allows everything
        
        async with AsyncSessionLocal() as db:
            new_log = SystemLog(
                level=levels.get(level, "INFO"),
                source=source,
                message=message,
                details=details
            )
            db.add(new_log)
            await db.commit()

    async def cleanup(self):
        hours = int(config_manager.get('LOGGING', 'log_retention_hours', '24'))
        cutoff = datetime.now() - timedelta(hours=hours)
        async with AsyncSessionLocal() as db:
            await db.execute(delete(SystemLog).where(SystemLog.timestamp < cutoff))
            await db.commit()

sys_logger = SystemLogger()
