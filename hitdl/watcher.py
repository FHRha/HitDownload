import os
import re
import json
from pathlib import Path
from typing import List, Dict, Set, Tuple

def sanitize_filename(name: str) -> str:
    return re.sub(r'[\\/*?:"<>|]', "", name).strip().rstrip('.')

IGNORE_FILE_NAME = ".hitdl_ignore.json"

def get_ignore_file_path(music_dir: str) -> Path:
    return Path(music_dir) / IGNORE_FILE_NAME

def load_ignore_list(music_dir: str) -> Dict[str, List[str]]:
    """Возвращает словарь { 'artist_name': ['album_id1', 'track_id1', ...] }"""
    path = get_ignore_file_path(music_dir)
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def save_ignore_list(music_dir: str, ignore_list: Dict[str, List[str]]):
    path = get_ignore_file_path(music_dir)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(ignore_list, f, ensure_ascii=False, indent=2)

def add_to_ignore(music_dir: str, artist_name: str, item_id: str):
    ignore_list = load_ignore_list(music_dir)
    if artist_name not in ignore_list:
        ignore_list[artist_name] = []
    if str(item_id) not in ignore_list[artist_name]:
        ignore_list[artist_name].append(str(item_id))
    save_ignore_list(music_dir, ignore_list)

def get_local_artists(music_dir: str) -> List[str]:
    """Получает список всех папок верхнего уровня в директории с музыкой."""
    p = Path(music_dir)
    if not p.exists() or not p.is_dir():
        return []
    
    artists = []
    for entry in p.iterdir():
        if entry.is_dir():
            if not entry.name.startswith("."):
                artists.append(entry.name)
    return sorted(artists)

def fetch_missing_releases(client, music_dir: str, artist_name: str, ignore_list: Dict[str, List[str]], log_cb=None, progress_cb=None) -> List[Dict]:
    """
    Ищет артиста на Я.Музыке, перебирает его релизы и сравнивает с локальными.
    Возвращает список треков (в формате, понятном для download_tracks_list).
    """
    if log_cb:
        log_cb(f"Поиск артиста на Я.Музыке: {artist_name}")
        
    search_result = client.search(artist_name, type_='artist')
    if not search_result or not search_result.artists or not search_result.artists.results:
        if log_cb:
            log_cb(f"[yellow]Артист не найден на Я.Музыке: {artist_name}[/yellow]")
        if progress_cb: progress_cb(1, 1)
        return []
        
    artist_obj = search_result.artists.results[0]
    artist_id = artist_obj.id
    ym_artist_name = artist_obj.name
    
    ignored_items = set(ignore_list.get(artist_name, []))
    
    if log_cb:
        log_cb(f"Получение дискографии: {ym_artist_name}")
        
    try:
        albums_page = client.artists_direct_albums(artist_id, page_size=200)
    except Exception as e:
        if log_cb: log_cb(f"[red]Ошибка получения альбомов: {e}[/red]")
        if progress_cb: progress_cb(1, 1)
        return []
        
    if not albums_page:
        if progress_cb: progress_cb(1, 1)
        return []
        
    missing_tracks_data = []
    total_albums = len(albums_page)
    
    for idx, album in enumerate(albums_page):
        if progress_cb: progress_cb(idx, total_albums)
        
        if str(album.id) in ignored_items:
            continue
            
        album_title_sanitized = sanitize_filename(album.title)
        album_dir = Path(music_dir) / sanitize_filename(artist_name) / album_title_sanitized
        
        # Оптимизация
        if album_dir.exists():
            mp3_files = list(album_dir.glob("*.mp3"))
            if album.track_count and len(mp3_files) >= album.track_count:
                continue
                
        try:
            full_album = client.albums_with_tracks(album.id)
            if not full_album or getattr(full_album, 'error', None):
                continue
                
            for vol in full_album.volumes:
                for track in vol:
                    if str(track.id) in ignored_items:
                        continue
                        
                    track_artist = ", ".join(a.name for a in track.artists) if track.artists else ym_artist_name
                    track_title = sanitize_filename(track.title)
                    track_artist_sanitized = sanitize_filename(track_artist.split(", ")[0])[:50] if track.artists else sanitize_filename(ym_artist_name)
                    
                    file_name = f"{track_artist_sanitized} - {track_title}"[:200] + ".mp3"
                    file_path = album_dir / file_name
                    
                    if not file_path.exists():
                        cover_url = f"https://{track.cover_uri.replace('%%', '400x400')}" if track.cover_uri else None
                        
                        missing_tracks_data.append({
                            "artist": track_artist,
                            "album_artist": ym_artist_name,
                            "title": track.title,
                            "album": full_album.title,
                            "album_id": full_album.id,
                            "track_id": track.id,
                            "mp3_url": f"yandex://{track.id}",
                            "cover_url": cover_url,
                            "track_obj": track,
                            "watcher_album_title": full_album.title,
                            "watcher_artist_name": artist_name,
                            "is_single": full_album.type == 'single'
                        })
        except Exception as e:
            if log_cb: log_cb(f"[red]Ошибка при проверке альбома {album.title}: {e}[/red]")
            continue

    if progress_cb: progress_cb(total_albums, total_albums)
    return missing_tracks_data
