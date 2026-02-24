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
        await sys_logger.log(3, "FILE", "log_transfer_start", details=f"mode: {mode}, src: {src_path.name}, dst: {dst_path.name}")
        
        try:
            if mode == 'hardlink':
                try:
                    os.link(src, dst)
                    await sys_logger.log(3, "FILE", "log_hardlink_success", details=f"name: {dst_path.name}")
                    return True
                except OSError as e:
                    await sys_logger.log(2, "FILE", "log_hardlink_error", details=f"error: {e}")
                    logger.error(f"--> [HARDLINK] Failed, falling back to copy: {e}")
                    mode = 'copy'

            if mode == 'copy':
                shutil.copy2(src, dst)
                await sys_logger.log(3, "FILE", "log_copy_success", details=f"name: {dst_path.name}")
                return True
            
            if mode == 'move':
                shutil.move(src, dst)
                await sys_logger.log(3, "FILE", "log_move_success", details=f"name: {dst_path.name}")
                return True
                
        except Exception as e:
            await sys_logger.log(2, "FILE", "log_transfer_error", details=f"mode: {mode}, error: {e}")
            logger.error(f"--> [TRANSFER] Error ({mode}): {e}")
            return False
        return False

    async def undo_download(self, download_id: int, db: AsyncSession):
        await sys_logger.log(1, "USER", "log_undo_start", details=f"id: {download_id}")
        stmt = select(Download).where(Download.id == download_id)
        result = await db.execute(stmt)
        download = result.scalar_one_or_none()
        
        if not download or download.status == MediaStatus.REVERTED.value:
            return False, "Download not found or already reverted"

        from .processor import processor
        processor._add_log(download, "log_undo_run")

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
                            processor._add_log(download, "log_undo_skip_exists", name=src.name)
                        else:
                            src.parent.mkdir(parents=True, exist_ok=True)
                            shutil.move(str(dst), str(src))
                            success_count += 1
                            processor._add_log(download, "log_undo_ok", dst=dst.name, src=src.name)
                        
                        # Cleanup empty parent of dst
                        if dst.parent.exists() and not any(dst.parent.iterdir()):
                            try:
                                dst.parent.rmdir()
                            except: pass
                else: # copy or hardlink
                    if dst.exists():
                        dst.unlink()
                        success_count += 1
                        processor._add_log(download, "log_undo_del_copy", name=dst.name)
                        
                        # Cleanup empty parent of dst
                        if dst.parent.exists() and not any(dst.parent.iterdir()):
                            try:
                                dst.parent.rmdir()
                            except: pass
            except Exception as e:
                logger.error(f"--> [UNDO] Error for {move.dst_path}: {e}")

        download.status = MediaStatus.REVERTED.value
        processor._add_log(download, "log_undo_complete", count=success_count)
        await db.commit()
        return True, f"Reverted {success_count} files"

file_ops = FileOperations()
