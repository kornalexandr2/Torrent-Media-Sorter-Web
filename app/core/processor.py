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

logger = logging.getLogger('TorrentMediaSorter')

class Processor:
    async def process_torrent(self, db: AsyncSession, torrent_id: str = None, torrent_name: str = None, torrent_dir: str = None, override_meta: dict = None, download_id: int = None):
        logger.info(f"--> [PROCESSOR] Processing request: {torrent_name} in {torrent_dir}")
        if not torrent_name or not torrent_dir:
            return

        p = Path(torrent_dir) / torrent_name
        if not p.exists():
            logger.warning(f"--> [PROCESSOR] Path does not exist: {p}")
            return

        download = None
        if download_id:
            stmt = select(Download).where(Download.id == download_id)
            res = await db.execute(stmt)
            download = res.scalar_one_or_none()
        
        if not download:
            # Check for existing path
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
            else:
                download.status = MediaStatus.PENDING.value
                download.detected_title = None
                download.detected_year = None
                download.metadata_source = None
                download.source_id = None
                await db.execute(delete(FileMove).where(FileMove.download_id == download.id))
        
        await db.commit()

        try:
            m_type_raw, target_name = scanner.detect_type(p)
            q_name = scanner.clean_search(target_name)
            
            if override_meta:
                api_data = override_meta
            else:
                api_data = await metadata_manager.resolve(q_name)
            
            # Detect final type
            if api_data and 'type' in api_data:
                m_type = api_data['type']
            else:
                m_type = 'tv' if m_type_raw == 'tv' else 'movie'

            # Map to Enum values
            type_map = {
                'movie': MediaType.MOVIE.value,
                'tv': MediaType.SERIES.value,
                'game': MediaType.GAME.value,
                'software': MediaType.SOFTWARE.value,
                'other': MediaType.OTHER.value
            }
            download.media_type = type_map.get(m_type, MediaType.UNKNOWN.value)
            
            # Destination mapping
            dest_map = {
                'movie': config_manager.get('PATHS', 'movies_folder'),
                'tv': config_manager.get('PATHS', 'series_folder'),
                'game': config_manager.get('PATHS', 'games_folder'),
                'software': config_manager.get('PATHS', 'software_folder'),
                'other': config_manager.get('PATHS', 'other_folder')
            }
            dest_root_str = dest_map.get(m_type, dest_map['other'])
            dest_root = Path(dest_root_str).expanduser()
            
            if not dest_root.exists():
                dest_root.mkdir(parents=True, exist_ok=True)
            
            if api_data:
                download.detected_title = api_data['titles'].get('ru') or api_data['titles'].get('origin')
                download.detected_year = api_data['year']
                download.metadata_source = api_data['source']
                download.source_id = api_data['source_id']
                
                t = download.detected_title
                if m_type in ['movie', 'tv']:
                    folder_name = renamer.sanitize(f"{t} ({api_data['year']})" if api_data['year'] else t)
                else:
                    folder_name = renamer.sanitize(t)
            else:
                folder_name = renamer.sanitize(p.name)

            mode = config_manager.get('RENAMING', 'mode', 'move').lower()
            season_folders = config_manager.getboolean('RENAMING', 'season_folders', True)
            
            video_exts = tuple(x.strip() for x in config_manager.get('SYSTEM', 'video_extensions', fallback='.mkv,.avi,.mp4').split(','))
            
            success_count = 0
            final_dest = dest_root / folder_name

            # LOGIC FOR TRANSFER
            if p.is_dir():
                # For non-video types (Games/Soft), move EVERYTHING
                is_media = m_type in ['movie', 'tv']
                
                for f in list(p.rglob('*')):
                    if not f.is_file(): continue
                    
                    # If it's movie/tv, filter by extension. Otherwise, take everything.
                    if is_media and f.suffix.lower() not in video_exts:
                        continue
                    
                    # Determine target path
                    rel_path = f.relative_to(p)
                    if is_media and season_folders:
                        # Special handling for series folders
                        ep_tag = scanner.get_season_episode(f.name)
                        if ep_tag:
                            m = re.search(r'S(\d{1,2})', ep_tag, re.I)
                            if m:
                                s_num = int(m.group(1))
                                current_folder = final_dest / f"Season {s_num:02d}"
                                target = renamer.get_unique_path(current_folder / renamer.construct_filename(api_data, f))
                            else:
                                target = renamer.get_unique_path(final_dest / rel_path)
                        else:
                            target = renamer.get_unique_path(final_dest / rel_path)
                    else:
                        target = renamer.get_unique_path(final_dest / rel_path)

                    if await file_ops.transfer_file(str(f), str(target), mode):
                        success_count += 1
                        db.add(FileMove(download_id=download.id, src_path=str(f), dst_path=str(target)))
            else:
                # Single file
                new_fname = renamer.construct_filename(api_data, p) if m_type in ['movie', 'tv'] else p.name
                target = renamer.get_unique_path(dest_root / new_fname)
                if await file_ops.transfer_file(str(p), str(target), mode):
                    success_count += 1
                    db.add(FileMove(download_id=download.id, src_path=str(p), dst_path=str(target)))

            if success_count > 0:
                download.status = MediaStatus.SUCCESS.value
                logger.info(f"--> [PROCESSOR] Successfully processed {success_count} files for {torrent_name}")
                try:
                    await notifier.send_telegram({
                        'title': download.detected_title or torrent_name,
                        'year': download.detected_year or '',
                        'status': 'Готово'
                    })
                except: pass
            else:
                logger.warning(f"--> [PROCESSOR] No files were transferred for {torrent_name}")
                download.status = MediaStatus.ERROR.value
            
            await db.commit()

            # Cleanup client
            if download.status == MediaStatus.SUCCESS and torrent_id:
                client = get_client()
                if client:
                    await client.remove_torrent(torrent_id)

        except Exception as e:
            logger.error(f"--> [PROCESSOR] Global error: {e}", exc_info=True)
            download.status = MediaStatus.ERROR.value
            await db.commit()

processor = Processor()
