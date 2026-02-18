import os
import shutil
import logging
from pathlib import Path
from typing import List, Tuple
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from ..models import Download, FileMove, MediaStatus
from ..config import config_manager

logger = logging.getLogger('TorrentMediaSorter')

class FileOperations:
    async def transfer_file(self, src: str, dst: str, mode: str = 'move') -> bool:
        src_path = Path(src)
        dst_path = Path(dst)
        dst_path.parent.mkdir(parents=True, exist_ok=True)
        
        try:
            if mode == 'hardlink':
                try:
                    os.link(src, dst)
                    return True
                except OSError as e:
                    logger.error(f"--> [HARDLINK] Failed, falling back to copy: {e}")
                    mode = 'copy'

            if mode == 'copy':
                shutil.copy2(src, dst)
                return True
            
            if mode == 'move':
                # Shutil move across filesystems can be slow, 
                # but we use it for reliability.
                shutil.move(src, dst)
                return True
                
        except Exception as e:
            logger.error(f"--> [TRANSFER] Error ({mode}): {e}")
            return False
        return False

    async def undo_download(self, download_id: int, db: AsyncSession):
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
