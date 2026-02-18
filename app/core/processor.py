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
    def _add_log(self, download, message):
        from datetime import datetime
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if not download.logs:
            download.logs = f"[{timestamp}] {message}"
        else:
            download.logs += f"\n[{timestamp}] {message}"

    async def process_torrent(self, db: AsyncSession, torrent_id: str = None, torrent_name: str = None, torrent_dir: str = None, override_meta: dict = None, download_id: int = None):
        source_type = "USER" if (override_meta or not torrent_id) else "SCRIPT"
        await sys_logger.log(1, source_type, f"Запуск обработки: {torrent_name}")
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
                self._add_log(download, "Объект обнаружен")
            else:
                download.status = MediaStatus.PENDING.value
                download.detected_title = None
                download.detected_year = None
                download.metadata_source = None
                download.source_id = None
                self._add_log(download, "Повторный запуск обработки")
                await db.execute(delete(FileMove).where(FileMove.download_id == download.id))
        
        await db.commit()

        try:
            await sys_logger.log(3, "SYSTEM", f"Анализ типа контента для {p.name}")
            m_type_raw, target_name = scanner.detect_type(p)
            q_name = scanner.clean_search(target_name)
            self._add_log(download, f"Определен тип: {m_type_raw}, поисковый запрос: {q_name}")
            
            if override_meta:
                api_data = override_meta
                self._add_log(download, f"Использованы ручные метаданные от {api_data.get('source', 'manual')}")
            else:
                self._add_log(download, "Поиск метаданных в API...")
                await sys_logger.log(3, "SYSTEM", f"Поиск метаданных для: {q_name}")
                api_data = await metadata_manager.resolve(q_name)
            
            if api_data and 'type' in api_data:
                m_type = api_data['type']
                await sys_logger.log(3, "SYSTEM", f"Получены данные от {api_data['source']} для {q_name}")
            else:
                m_type = 'tv' if m_type_raw == 'tv' else 'movie'
                await sys_logger.log(3, "SYSTEM", f"Метаданные не найдены, используем детекцию сканера: {m_type}")

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
                self._add_log(download, f"Метаданные найдены ({api_data['source']}): {download.detected_title}")
                await sys_logger.log(1, "SYSTEM", f"Метаданные найдены: {download.detected_title}")
                t = download.detected_title
                folder_name = renamer.sanitize(f"{t} ({api_data['year']})" if (api_data['year'] and m_type in ['movie', 'tv']) else t)
            else:
                folder_name = renamer.sanitize(p.name)

            mode = config_manager.get('RENAMING', 'mode', 'move').lower()
            season_folders = config_manager.getboolean('RENAMING', 'season_folders', True)
            video_exts = tuple(x.strip() for x in config_manager.get('SYSTEM', 'video_extensions', fallback='.mkv,.avi,.mp4').split(','))
            
            success_count = 0
            final_dest = dest_root / folder_name
            logger.info(f"--> [PROCESSOR] Target: {final_dest}, Type: {m_type}")

            # ROBUST FILE LISTING
            items_to_process = []
            if p.is_dir():
                for root, dirs, files in os.walk(str(p)):
                    for file in files:
                        items_to_process.append(Path(root) / file)
            else:
                items_to_process.append(p)

            logger.info(f"--> [PROCESSOR] Found {len(items_to_process)} files to process")
            is_media = m_type in ['movie', 'tv']

            for f in items_to_process:
                if is_media and f.suffix.lower() not in video_exts:
                    continue
                
                rel_path = f.relative_to(p) if p.is_dir() else Path(f.name)
                
                # Series logic
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

                logger.info(f"--> [TRANSFER] {f.name} -> {target}")
                if await file_ops.transfer_file(str(f), str(target), mode):
                    success_count += 1
                    db.add(FileMove(download_id=download.id, src_path=str(f), dst_path=str(target)))
                    self._add_log(download, f"Успешно: {f.name} -> {target.name}")
                    await sys_logger.log(3, "SYSTEM", f"Файл перенесен: {f.name}")
                else:
                    self._add_log(download, f"ОШИБКА: {f.name}")
                    await sys_logger.log(2, "SYSTEM", f"Ошибка переноса: {f.name}")

            if success_count > 0:
                download.status = MediaStatus.SUCCESS.value
                self._add_log(download, f"Завершено. Файлов: {success_count}")
                await sys_logger.log(1, "SYSTEM", f"Успешно обработано: {torrent_name}")
                
                type_ru = "Фильм"
                if m_type == 'tv': type_ru = "Сериал"
                elif m_type == 'game': type_ru = "Игра"
                elif m_type == 'software': type_ru = "Программа"
                elif m_type == 'other': type_ru = "Файл"

                try:
                    await notifier.send_telegram({
                        'title': download.detected_title or torrent_name,
                        'year': download.detected_year or '',
                        'status': 'Готово',
                        'type_name': type_ru,
                        'original_name': torrent_name
                    })
                except: pass
            else:
                self._add_log(download, "Файлы не перенесены (не найдены медиа-файлы или ошибка доступа)")
                download.status = MediaStatus.ERROR.value
            
            await db.commit()
            if download.status == MediaStatus.SUCCESS and torrent_id:
                client = get_client()
                if client: await client.remove_torrent(torrent_id)

        except Exception as e:
            self._add_log(download, f"КРИТИЧЕСКАЯ ОШИБКА: {str(e)}")
            await sys_logger.log(2, "SYSTEM", f"Критическая ошибка: {str(e)}")
            download.status = MediaStatus.ERROR.value
            await db.commit()

processor = Processor()
