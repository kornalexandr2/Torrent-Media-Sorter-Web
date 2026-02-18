import os
import shutil
import logging
import re
from pathlib import Path
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
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
        if not torrent_name or not torrent_dir:
            return

        p = Path(torrent_dir) / torrent_name
        if not p.exists():
            return

        if download_id:
            stmt = select(Download).where(Download.id == download_id)
            res = await db.execute(stmt)
            download = res.scalar_one_or_none()
            if download:
                download.status = MediaStatus.PENDING
        else:
            download = None

        if not download:
            # Create initial DB record
            download = Download(
                torrent_name=torrent_name,
                original_path=str(p),
                status=MediaStatus.PENDING
            )
            db.add(download)
            await db.flush()
            
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
                m_type = api_data['type'] # movie, tv, game, software, other
            else:
                m_type = 'tv' if m_type_raw == 'tv' else 'movie'

            # Map to Enum
            type_map = {
                'movie': MediaType.MOVIE,
                'tv': MediaType.SERIES,
                'game': MediaType.GAME,
                'software': MediaType.SOFTWARE,
                'other': MediaType.OTHER
            }
            download.media_type = type_map.get(m_type, MediaType.UNKNOWN)
            
            # Destination mapping
            dest_map = {
                'movie': config_manager.get('PATHS', 'movies_folder'),
                'tv': config_manager.get('PATHS', 'series_folder'),
                'game': config_manager.get('PATHS', 'games_folder'),
                'software': config_manager.get('PATHS', 'software_folder'),
                'other': config_manager.get('PATHS', 'other_folder')
            }
            dest_root = Path(dest_map.get(m_type, dest_map['other'])).expanduser()
            
            if not dest_root.exists():
                try:
                    dest_root.mkdir(parents=True, exist_ok=True)
                except Exception as e:
                    logger.error(f"--> [PROCESSOR] Could not create destination folder {dest_root}: {e}")
                    download.status = MediaStatus.ERROR
                    await db.commit()
                    return
            
            if api_data:
                download.detected_title = api_data['titles'].get('ru') or api_data['titles'].get('origin')
                download.detected_year = api_data['year']
                download.metadata_source = api_data['source']
                download.source_id = api_data['source_id']
                
                t = download.detected_title
                if m_type in ['movie', 'tv']:
                    folder_name = renamer.sanitize(f"{t} ({api_data['year']})" if api_data['year'] else t)
                else:
                    folder_name = renamer.sanitize(t) # Games/Software usually don't need year in folder name
            else:
                folder_name = renamer.sanitize(p.name)
            
            mode = config_manager.get('RENAMING', 'mode', 'move').lower()
            season_folders = config_manager.getboolean('RENAMING', 'season_folders', True)
            
            success_count = 0
            
            video_exts = tuple(x.strip() for x in config_manager.get('SYSTEM', 'video_extensions', fallback='.mkv,.avi,.mp4').split(','))
            subtitle_exts = ('.srt', '.sub', '.ass', '.vtt')

            if p.is_dir():
                final_dest = dest_root / folder_name
                
                for f in list(p.rglob('*')):
                    if f.is_file() and f.suffix.lower() in video_exts:
                        # For series, optionally create Season XX folders
                        current_dest = final_dest
                        if m_type == 'tv' and season_folders:
                            ep_tag = scanner.get_season_episode(f.name)
                            if ep_tag:
                                m = re.search(r'S(\d{1,2})', ep_tag, re.I)
                                if m:
                                    s_num = int(m.group(1))
                                    current_dest = final_dest / f"Season {s_num:02d}"
                        
                        new_name = renamer.construct_filename(api_data, f)
                        target = renamer.get_unique_path(current_dest / new_name)
                        
                        if await file_ops.transfer_file(str(f), str(target), mode):
                            success_count += 1
                            db.add(FileMove(download_id=download.id, src_path=str(f), dst_path=str(target)))
                            # Check subtitles
                            for sub_ext in subtitle_exts:
                                sub_src = f.with_suffix(sub_ext)
                                if sub_src.exists():
                                    await file_ops.transfer_file(str(sub_src), str(target.with_suffix(sub_ext)), mode)
                                    db.add(FileMove(download_id=download.id, src_path=str(sub_src), dst_path=str(target.with_suffix(sub_ext))))
            else:
                new_fname = renamer.construct_filename(api_data, p)
                target = renamer.get_unique_path(dest_root / new_fname)
                if await file_ops.transfer_file(str(p), str(target), mode):
                    success_count += 1
                    db.add(FileMove(download_id=download.id, src_path=str(p), dst_path=str(target)))

            if success_count > 0:
                download.status = MediaStatus.SUCCESS
                try:
                    await notifier.send_telegram({
                        'title': download.detected_title or torrent_name,
                        'year': download.detected_year or '',
                        'status': 'Готово'
                    })
                except Exception as notify_err:
                    logger.error(f"--> [PROCESSOR] Notification error: {notify_err}")
            else:
                download.status = MediaStatus.ERROR
            
            await db.commit()
            
            # Remove from client if successful
            if download.status == MediaStatus.SUCCESS and torrent_id:
                client = get_client()
                if client:
                    try:
                        removed = await client.remove_torrent(torrent_id)
                        if removed:
                            logger.info(f"--> [PROCESSOR] Torrent {torrent_id} removed from client.")
                        else:
                            logger.warning(f"--> [PROCESSOR] Failed to remove torrent {torrent_id} from client.")
                    except Exception as e:
                        logger.error(f"--> [PROCESSOR] Error removing torrent: {e}")

        except SQLAlchemyError as sae:
            logger.error(f"--> [PROCESSOR] Database error: {sae}")
            # If we fail here, we can't update status in DB
        except Exception as e:
            logger.error(f"--> [PROCESSOR] Global error during processing: {e}", exc_info=True)
            try:
                download.status = MediaStatus.ERROR
                await db.commit()
            except:
                pass

processor = Processor()
