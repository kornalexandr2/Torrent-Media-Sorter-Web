import os
import shutil
import logging
import re
from pathlib import Path
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from sqlalchemy.exc import SQLAlchemyError
from ..models import Download, FileMove, MediaStatus, MediaType
from ..config import config_manager
from .scanner import scanner
from .metadata import metadata_manager
from .renamer import renamer
from .operations import file_ops
from .notifier import notifier
from .clients import get_client
from .logger import sys_logger

logger = logging.getLogger('TorrentMediaSorter')

class Processor:
    def _add_log(self, download, key, **kwargs):
        from datetime import datetime
        import json
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # Store as JSON string if there are kwargs, otherwise just the key
        if kwargs:
            log_entry = json.dumps({"key": key, "params": kwargs})
        else:
            log_entry = key
            
        message = f"[{timestamp}] {log_entry}"
        if not download.logs:
            download.logs = message
        else:
            download.logs += f"\n{message}"

    async def process_torrent(self, db: AsyncSession, torrent_id: str = None, torrent_name: str = None, torrent_dir: str = None, override_meta: dict = None, download_id: int = None):
        source_type = "USER" if (override_meta or not torrent_id) else "SCRIPT"
        await sys_logger.log(1, source_type, "log_proc_start", details=f"name: {torrent_name}")
        logger.info(f"--> [PROCESSOR] Processing request: {torrent_name} in {torrent_dir}")
        if not torrent_name or not torrent_dir:
            return

        p = Path(torrent_dir) / torrent_name
        p = p.resolve() # Normalize path
        
        if not p.exists():
            logger.warning(f"--> [PROCESSOR] Path does not exist: {p}")
            return

        download = None
        if download_id:
            stmt = select(Download).where(Download.id == download_id)
            res = await db.execute(stmt)
            download = res.scalar_one_or_none()
        
        if not download:
            stmt = select(Download).where(Download.original_path == str(p)).order_by(Download.id.desc()).limit(1)
            res = await db.execute(stmt)
            download = res.scalar_one_or_none()
            
            if not download:
                download = Download(
                    torrent_name=torrent_name,
                    original_path=str(p),
                    status=MediaStatus.PENDING.value
                )
                db.add(download)
                self._add_log(download, "log_obj_discovered")
            else:
                download.status = MediaStatus.PENDING.value
                download.detected_title = None
                download.detected_year = None
                download.metadata_source = None
                download.source_id = None
                self._add_log(download, "log_proc_retry")
                await db.execute(delete(FileMove).where(FileMove.download_id == download.id))
        
        await db.commit()

        try:
            await sys_logger.log(3, "SYSTEM", "log_detect_type", details=f"name: {p.name}")
            
            import json
            scores, target_name = scanner.detect_type(p)
            m_type_raw = max(scores, key=scores.get)
            download.type_scores = json.dumps(scores)
            
            q_name = scanner.clean_search(target_name)
            self._add_log(download, "log_type_detected", type=m_type_raw, query=q_name)
            
            if override_meta:
                api_data = override_meta
                self._add_log(download, "log_manual_meta", source=api_data.get('source', 'manual'))
            else:
                self._add_log(download, "log_api_search")
                await sys_logger.log(3, "SYSTEM", "log_api_search", details=f"query: {q_name}")
                
                if m_type_raw == 'software':
                    # STRICT MODE: If scanner found software indicators (exe, dll), we ONLY use IGDB.
                    self._add_log(download, "log_api_search_igdb_only")
                    api_data = await metadata_manager.resolve(q_name, priority_list=['igdb'])
                elif m_type_raw == 'unknown':
                    # TRY IGDB FIRST for unknown, but allow fallback to others if not found
                    self._add_log(download, "log_api_search_igdb_first")
                    api_data = await metadata_manager.resolve(q_name, priority_list=['igdb'])
                    if not api_data:
                        self._add_log(download, "log_api_search_fallback")
                        api_data = await metadata_manager.resolve(q_name)
                else:
                    # Normal mode for movies/series
                    api_data = await metadata_manager.resolve(q_name)
            
            if api_data and 'type' in api_data:
                m_type = api_data['type']
                self._add_log(download, "log_api_data_received", 
                              source=api_data['source'], 
                              titles=api_data['titles'], 
                              year=api_data['year'], 
                              id=api_data['source_id'])
                await sys_logger.log(3, "SYSTEM", "log_api_meta_found", details=f"source: {api_data['source']}, query: {q_name}")
            else:
                # No meta found - keep what scanner determined
                m_type = m_type_raw
                await sys_logger.log(3, "SYSTEM", f"DEBUG: Meta not found, using scanner: {m_type}")

            type_map = {
                'movie': MediaType.MOVIE.value,
                'tv': MediaType.SERIES.value,
                'game': MediaType.GAME.value,
                'software': MediaType.SOFTWARE.value,
                'other': MediaType.OTHER.value
            }
            download.media_type = type_map.get(m_type, MediaType.UNKNOWN.value)
            
            dest_map = {
                'movie': config_manager.get('PATHS', 'movies_folder'),
                'tv': config_manager.get('PATHS', 'series_folder'),
                'game': config_manager.get('PATHS', 'games_folder'),
                'software': config_manager.get('PATHS', 'software_folder'),
                'other': config_manager.get('PATHS', 'other_folder')
            }
            dest_root = Path(dest_map.get(m_type, dest_map['other'])).expanduser()
            if not dest_root.exists(): dest_root.mkdir(parents=True, exist_ok=True)
            
            if api_data:
                download.detected_title = api_data['titles'].get('ru') or api_data['titles'].get('origin')
                download.detected_year = api_data['year']
                download.metadata_source = api_data['source']
                download.source_id = api_data['source_id']
                self._add_log(download, "log_api_meta_found", source=api_data['source'], title=download.detected_title)
                await sys_logger.log(1, "SYSTEM", "log_api_meta_found", details=f"title: {download.detected_title}")

            if not download.system_media_type:
                download.system_media_type = download.media_type

            download.status = MediaStatus.MANUAL_REQUIRED.value
            self._add_log(download, "log_awaiting_approval")
            await db.commit()

        except Exception as e:
            self._add_log(download, "log_proc_critical", error=str(e))
            await sys_logger.log(2, "SYSTEM", "log_proc_critical", details=f"error: {str(e)}")
            download.status = MediaStatus.ERROR.value
            await db.commit()

    async def execute_transfer(self, db: AsyncSession, download_id: int):
        stmt = select(Download).where(Download.id == download_id)
        res = await db.execute(stmt)
        download = res.scalar_one_or_none()

        if not download or not os.path.exists(download.original_path):
            return False

        p = Path(download.original_path)
        
        m_type_map = {
            MediaType.MOVIE.value: 'movie',
            MediaType.SERIES.value: 'tv',
            MediaType.GAME.value: 'game',
            MediaType.SOFTWARE.value: 'software',
            MediaType.OTHER.value: 'other'
        }
        m_type = m_type_map.get(download.media_type, 'other')
        
        dest_map = {
            'movie': config_manager.get('PATHS', 'movies_folder'),
            'tv': config_manager.get('PATHS', 'series_folder'),
            'game': config_manager.get('PATHS', 'games_folder'),
            'software': config_manager.get('PATHS', 'software_folder'),
            'other': config_manager.get('PATHS', 'other_folder')
        }
        dest_root = Path(dest_map.get(m_type, dest_map['other'])).expanduser()
        if not dest_root.exists(): dest_root.mkdir(parents=True, exist_ok=True)
        
        api_data = None
        if download.detected_title:
            api_data = {
                'titles': {'ru': download.detected_title, 'origin': download.detected_title},
                'year': download.detected_year
            }
            t = download.detected_title
            folder_name = renamer.sanitize(f"{t} ({api_data['year']})" if (api_data['year'] and m_type in ['movie', 'tv']) else t)
        else:
            folder_name = renamer.sanitize(p.name)

        mode = config_manager.get('RENAMING', 'mode', 'move').lower()
        season_folders = config_manager.getboolean('RENAMING', 'season_folders', True)
        video_exts = tuple(x.strip() for x in config_manager.get('SYSTEM', 'video_extensions', fallback='.mkv,.avi,.mp4').split(','))
        
        success_count = 0
        final_dest = dest_root / folder_name
        logger.info(f"--> [TRANSFER_EXEC] Target: {final_dest}, Type: {m_type}")

        items_to_process = []
        if p.is_dir():
            for root, dirs, files in os.walk(str(p)):
                for file in files:
                    items_to_process.append(Path(root) / file)
        else:
            items_to_process.append(p)

        is_media = m_type in ['movie', 'tv']

        try:
            for f in items_to_process:
                if is_media and f.suffix.lower() not in video_exts:
                    continue
                
                rel_path = f.relative_to(p) if p.is_dir() else Path(f.name)
                
                if is_media and season_folders and m_type == 'tv':
                    ep_tag = scanner.get_season_episode(f.name)
                    if ep_tag:
                        m = re.search(r'S(\d{1,2})', ep_tag, re.I)
                        if m:
                            s_num = int(m.group(1))
                            target = renamer.get_unique_path(final_dest / f"Season {s_num:02d}" / renamer.construct_filename(api_data, f))
                        else: target = renamer.get_unique_path(final_dest / rel_path)
                    else: target = renamer.get_unique_path(final_dest / rel_path)
                else:
                    target = renamer.get_unique_path(final_dest / (renamer.construct_filename(api_data, f) if is_media else rel_path))

                logger.info(f"--> [TRANSFER_EXEC] {f.name} -> {target}")
                if await file_ops.transfer_file(str(f), str(target), mode):
                    success_count += 1
                    db.add(FileMove(download_id=download.id, src_path=str(f), dst_path=str(target)))
                    self._add_log(download, "log_transfer_ok", src=f.name, dst=target.name)
                    await sys_logger.log(3, "SYSTEM", "log_move_success", details=f"name: {f.name}")
                else:
                    self._add_log(download, "log_transfer_fail", name=f.name)
                    await sys_logger.log(2, "SYSTEM", "log_transfer_error", details=f"name: {f.name}")

            if success_count > 0:
                download.status = MediaStatus.SUCCESS.value
                self._add_log(download, "log_proc_complete", count=success_count)
                await sys_logger.log(1, "SYSTEM", "done", details=f"name: {download.torrent_name}")
                
                try:
                    await notifier.send_telegram({
                        'title': download.detected_title or download.torrent_name,
                        'year': download.detected_year or '',
                        'status': 'done',
                        'type_name': m_type,
                        'original_name': download.torrent_name
                    })
                except: pass
                
                # Check for removing torrent from client
                torrent_id = None
                # We need a way to get torrent_id if we want to delete it.
                # However, for now we will skip removing torrent from client on manual approval.
                # Actually, wait, previously torrent_id was passed. But we don't save torrent_id. 
                # We might need to keep it, but it's optional.
            else:
                self._add_log(download, "log_proc_no_files")
                download.status = MediaStatus.ERROR.value
            
            await db.commit()
            return True

        except Exception as e:
            self._add_log(download, "log_proc_critical", error=str(e))
            await sys_logger.log(2, "SYSTEM", "log_proc_critical", details=f"error: {str(e)}")
            download.status = MediaStatus.ERROR.value
            await db.commit()
            return False

processor = Processor()
