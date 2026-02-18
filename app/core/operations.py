import os
import shutil
import logging
from pathlib import Path
from typing import List, Tuple
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from ..models import Download, FileMove, MediaStatus
from ..config import config_manager
from .logger import sys_logger

logger = logging.getLogger('TorrentMediaSorter')

class FileOperations:
    async def transfer_file(self, src: str, dst: str, mode: str = 'move') -> bool:
        src_path = Path(src)
        dst_path = Path(dst)
        dst_path.parent.mkdir(parents=True, exist_ok=True)
        await sys_logger.log(3, "FILE", f"Начало переноса ({mode}): {src_path.name} -> {dst_path.name}")
        
        try:
            if mode == 'hardlink':
                try:
                    os.link(src, dst)
                    await sys_logger.log(3, "FILE", f"Создан хардлинк: {dst_path.name}")
                    return True
                except OSError as e:
                    await sys_logger.log(2, "FILE", f"Ошибка хардлинка, откат к копированию: {e}")
                    logger.error(f"--> [HARDLINK] Failed, falling back to copy: {e}")
                    mode = 'copy'

            if mode == 'copy':
                shutil.copy2(src, dst)
                await sys_logger.log(3, "FILE", f"Файл скопирован: {dst_path.name}")
                return True
            
            if mode == 'move':
                shutil.move(src, dst)
                await sys_logger.log(3, "FILE", f"Файл перемещен: {dst_path.name}")
                return True
                
        except Exception as e:
            await sys_logger.log(2, "FILE", f"Критическая ошибка переноса ({mode}): {e}")
            logger.error(f"--> [TRANSFER] Error ({mode}): {e}")
            return False
        return False

    async def undo_download(self, download_id: int, db: AsyncSession):
        await sys_logger.log(1, "USER", f"Начало отката (Undo) для ID {download_id}")
        stmt = select(Download).where(Download.id == download_id)
        result = await db.execute(stmt)
        download = result.scalar_one_or_none()
        
        if not download or download.status == MediaStatus.REVERTED.value:
            return False, "Download not found or already reverted"

        from .processor import processor
        processor._add_log(download, "Запущен откат (Undo)")

        stmt_moves = select(FileMove).where(FileMove.download_id == download_id)
        res_moves = await db.execute(stmt_moves)
        moves = res_moves.scalars().all()

        success_count = 0
        mode = config_manager.get('RENAMING', 'mode', 'move').lower()

        for move in moves:
            try:
                src, dst = Path(move.src_path), Path(move.dst_path)
                if mode == 'move':
                    if dst.exists():
                        if src.exists():
                            logger.warning(f"--> [UNDO] Source path already exists: {src}. Skipping move back.")
                            processor._add_log(download, f"Откат файла пропущен (оригинал существует): {src.name}")
                        else:
                            src.parent.mkdir(parents=True, exist_ok=True)
                            shutil.move(str(dst), str(src))
                            success_count += 1
                            processor._add_log(download, f"Файл возвращен: {dst.name} -> {src.name}")
                        
                        # Cleanup empty parent of dst
                        if dst.parent.exists() and not any(dst.parent.iterdir()):
                            try:
                                dst.parent.rmdir()
                            except: pass
                else: # copy or hardlink
                    if dst.exists():
                        dst.unlink()
                        success_count += 1
                        processor._add_log(download, f"Файл удален (откат копии): {dst.name}")
                        
                        # Cleanup empty parent of dst
                        if dst.parent.exists() and not any(dst.parent.iterdir()):
                            try:
                                dst.parent.rmdir()
                            except: pass
            except Exception as e:
                logger.error(f"--> [UNDO] Error for {move.dst_path}: {e}")

        download.status = MediaStatus.REVERTED.value
        processor._add_log(download, f"Откат завершен. Обработано файлов: {success_count}")
        await db.commit()
        return True, f"Reverted {success_count} files"

file_ops = FileOperations()
