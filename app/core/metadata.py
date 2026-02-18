import httpx
import json
import urllib.parse
import logging
from typing import Optional, Dict, Any, List
from ..config import config_manager
from .logger import sys_logger

logger = logging.getLogger('TorrentMediaSorter')

class MetadataProvider:
    async def get_metadata(self, query: str) -> Optional[Dict[str, Any]]:
        raise NotImplementedError

    async def get_by_id(self, source_id: str, media_type: Optional[str] = None) -> Optional[Dict[str, Any]]:
        raise NotImplementedError

class KinopoiskProvider(MetadataProvider):
    async def get_metadata(self, query: str) -> Optional[Dict[str, Any]]:
        await sys_logger.log(3, "API:KP", f"Запрос: {query}")
        api_key = config_manager.get('API', 'kp_api_key')
        if not api_key or not isinstance(api_key, str) or "YOUR_" in api_key:
            return None
        
        try:
            q_enc = urllib.parse.quote(query)
            url = f"https://kinopoiskapiunofficial.tech/api/v2.1/films/search-by-keyword?keyword={q_enc}"
            headers = {
                'X-API-KEY': api_key,
                'Content-Type': 'application/json'
            }
            async with httpx.AsyncClient() as client:
                response = await client.get(url, headers=headers, timeout=10.0)
                if response.status_code != 200:
                    return None
                data = response.json()
                if not data.get('films'):
                    return None
                
                item = data['films'][0]
                k_type = item.get('type')
                titles = {
                    'ru': item.get('nameRu'),
                    'en': item.get('nameEn'),
                    'origin': item.get('nameOriginal') or item.get('nameEn')
                }
                year = str(item.get('year') or '')
                t = 'movie' if k_type == 'FILM' else ('tv' if k_type in ['TV_SERIES', 'MINI_SERIES', 'TV_SHOW'] else None)
                if t:
                    return {
                        'type': t,
                        'titles': titles,
                        'year': year,
                        'source': 'KP',
                        'source_id': str(item.get('filmId'))
                    }
        except Exception as e:
            logger.error(f"--> [API:KP] Error: {e}")
        return None

    async def get_by_id(self, source_id: str, media_type: Optional[str] = None) -> Optional[Dict[str, Any]]:
        api_key = config_manager.get('API', 'kp_api_key')
        if not api_key or not isinstance(api_key, str) or "YOUR_" in api_key:
            return None
        
        try:
            url = f"https://kinopoiskapiunofficial.tech/api/v2.2/films/{source_id}"
            headers = {
                'X-API-KEY': api_key,
                'Content-Type': 'application/json'
            }
            async with httpx.AsyncClient() as client:
                response = await client.get(url, headers=headers, timeout=10.0)
                if response.status_code != 200:
                    return None
                item = response.json()
                
                k_type = item.get('type')
                titles = {
                    'ru': item.get('nameRu'),
                    'en': item.get('nameEn'),
                    'origin': item.get('nameOriginal') or item.get('nameEn')
                }
                year = str(item.get('year') or '')
                t = 'movie' if k_type == 'FILM' else ('tv' if k_type in ['TV_SERIES', 'MINI_SERIES', 'TV_SHOW'] else None)
                if t:
                    return {
                        'type': t,
                        'titles': titles,
                        'year': year,
                        'source': 'KP',
                        'source_id': str(item.get('kinopoiskId'))
                    }
        except Exception as e:
            logger.error(f"--> [API:KP] ID Error: {e}")
        return None

class TMDBProvider(MetadataProvider):
    async def get_metadata(self, query: str) -> Optional[Dict[str, Any]]:
        await sys_logger.log(3, "API:TMDB", f"Запрос: {query}")
        api_key = config_manager.get('API', 'tmdb_api_key')
        if not api_key or not isinstance(api_key, str) or "YOUR_" in api_key:
            return None
        
        try:
            q_enc = urllib.parse.quote(query)
            url = f"https://api.themoviedb.org/3/search/multi?api_key={api_key}&query={q_enc}&language=ru-RU&page=1"
            async with httpx.AsyncClient() as client:
                response = await client.get(url, timeout=10.0)
                if response.status_code != 200:
                    return None
                data = response.json()
                if not data.get('results'):
                    return None
                
                valid = [x for x in data['results'] if x.get('media_type') in ['movie', 'tv']]
                if not valid:
                    return None
                
                item = valid[0]
                m_type = item.get('media_type')
                if m_type == 'movie':
                    t_ru, t_orig, date = item.get('title'), item.get('original_title'), item.get('release_date', '')
                else:
                    t_ru, t_orig, date = item.get('name'), item.get('original_name'), item.get('first_air_date', '')
                
                titles = {'ru': t_ru, 'en': t_orig, 'origin': t_orig}
                year = date[:4] if date and len(date) >= 4 else ""
                return {
                    'type': m_type,
                    'titles': titles,
                    'year': year,
                    'source': 'TMDB',
                    'source_id': str(item.get('id'))
                }
        except Exception as e:
            logger.error(f"--> [API:TMDB] Error: {e}")
        return None

    async def get_by_id(self, source_id: str, media_type: Optional[str] = 'movie') -> Optional[Dict[str, Any]]:
        api_key = config_manager.get('API', 'tmdb_api_key')
        if not api_key or not isinstance(api_key, str) or "YOUR_" in api_key:
            return None
        
        try:
            m_type = media_type if media_type in ['movie', 'tv'] else 'movie'
            url = f"https://api.themoviedb.org/3/{m_type}/{source_id}?api_key={api_key}&language=ru-RU"
            async with httpx.AsyncClient() as client:
                response = await client.get(url, timeout=10.0)
                if response.status_code != 200:
                    return None
                item = response.json()
                
                if m_type == 'movie':
                    t_ru, t_orig, date = item.get('title'), item.get('original_title'), item.get('release_date', '')
                else:
                    t_ru, t_orig, date = item.get('name'), item.get('original_name'), item.get('first_air_date', '')
                
                titles = {'ru': t_ru, 'en': t_orig, 'origin': t_orig}
                year = date[:4] if date and len(date) >= 4 else ""
                return {
                    'type': m_type,
                    'titles': titles,
                    'year': year,
                    'source': 'TMDB',
                    'source_id': str(item.get('id'))
                }
        except Exception as e:
            logger.error(f"--> [API:TMDB] ID Error: {e}")
        return None

class TVDBProvider(MetadataProvider):
    async def get_metadata(self, query: str) -> Optional[Dict[str, Any]]:
        await sys_logger.log(3, "API:TVDB", f"Запрос: {query}")
        api_key = config_manager.get('API', 'tvdb_api_key')
        if not api_key or not isinstance(api_key, str) or "YOUR_" in api_key:
            return None
            
        try:
            async with httpx.AsyncClient() as client:
                login_url = "https://api4.thetvdb.com/v4/login"
                login_data = {"apikey": api_key}
                login_res = await client.post(login_url, json=login_data, timeout=10.0)
                if login_res.status_code != 200:
                    return None
                token = login_res.json().get('data', {}).get('token')
                if not token:
                    return None
                
                q_enc = urllib.parse.quote(query)
                search_url = f"https://api4.thetvdb.com/v4/search?query={q_enc}"
                headers = {'Authorization': f'Bearer {token}'}
                search_res = await client.get(search_url, headers=headers, timeout=10.0)
                if search_res.status_code != 200:
                    return None
                data = search_res.json()
                if not data.get('data'):
                    return None
                
                item = data['data'][0]
                raw_type = item.get('type', 'series')
                t = 'movie' if raw_type == 'movie' else 'tv'
                t_orig = item.get('name')
                t_ru = item.get('translations', {}).get('rus') if item.get('translations') else None
                titles = {'ru': t_ru or t_orig, 'en': t_orig, 'origin': t_orig}
                year = str(item.get('year') or "")
                return {
                    'type': t,
                    'titles': titles,
                    'year': year,
                    'source': 'TVDB',
                    'source_id': str(item.get('tvdb_id'))
                }
        except Exception as e:
            logger.error(f"--> [API:TVDB] Error: {e}")
        return None

    async def get_by_id(self, source_id: str, media_type: Optional[str] = None) -> Optional[Dict[str, Any]]:
        api_key = config_manager.get('API', 'tvdb_api_key')
        if not api_key or not isinstance(api_key, str) or "YOUR_" in api_key:
            return None
            
        try:
            async with httpx.AsyncClient() as client:
                login_url = "https://api4.thetvdb.com/v4/login"
                login_res = await client.post(login_url, json={"apikey": api_key}, timeout=10.0)
                token = login_res.json().get('data', {}).get('token')
                if not token: return None
                
                # In TVDB v4, we use /series/{id} or /movies/{id}
                is_movie = media_type == 'movie'
                url = f"https://api4.thetvdb.com/v4/{'movies' if is_movie else 'series'}/{source_id}/extended"
                headers = {'Authorization': f'Bearer {token}'}
                res = await client.get(url, headers=headers, timeout=10.0)
                if res.status_code != 200: return None
                data = res.json().get('data', {})
                
                t_orig = data.get('name')
                # TVDB translations are complex, but let's simplify
                t_ru = None
                if 'translations' in data and data['translations'].get('nameTranslations'):
                    for trans in data['translations']['nameTranslations']:
                        if trans.get('language') == 'rus':
                            t_ru = trans.get('name')
                            break

                titles = {'ru': t_ru or t_orig, 'en': t_orig, 'origin': t_orig}
                year = str(data.get('year') or "")
                return {
                    'type': 'movie' if is_movie else 'tv',
                    'titles': titles,
                    'year': year,
                    'source': 'TVDB',
                    'source_id': str(data.get('id'))
                }
        except Exception as e:
            logger.error(f"--> [API:TVDB] ID Error: {e}")
        return None

class MetadataManager:
    def __init__(self):
        self.providers = {
            'kp': KinopoiskProvider(),
            'tmdb': TMDBProvider(),
            'tvdb': TVDBProvider()
        }

    async def resolve(self, query: str, priority_list: List[str] = None) -> Optional[Dict[str, Any]]:
        manual_override = priority_list is not None
        if not manual_override:
            priority_str = config_manager.get('API', 'priority', 'kp,tmdb,tvdb')
            priority_list = [p.strip() for p in priority_str.split(',')]
            
        for p_name in priority_list:
            if p_name in self.providers:
                use_flag = config_manager.getboolean('API', f'use_{p_name}', False)
                if manual_override or use_flag:
                    meta = await self.providers[p_name].get_metadata(query)
                    if meta:
                        return meta
        return None

    async def resolve_by_id(self, source: str, source_id: str, media_type: str = None) -> Optional[Dict[str, Any]]:
        p_name = source.lower()
        if p_name in self.providers:
            return await self.providers[p_name].get_by_id(source_id, media_type)
        return None

metadata_manager = MetadataManager()
