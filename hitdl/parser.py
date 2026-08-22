import re
import urllib.parse
from typing import List, Dict

def parse_url(url: str, log_cb=None) -> List[Dict]:
    if "hitmotop.com" in url or "hitmo" in url:
        return parse_hitmo_playlist(url, log_cb)
    elif "music.yandex.ru" in url:
        return parse_yandex_music(url, log_cb)
    else:
        raise ValueError("Unsupported URL format")

def parse_hitmo_playlist(page_url: str, log_cb=None) -> List[Dict[str, str]]:
    import requests
    from bs4 import BeautifulSoup
    
    HEADERS = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    }

    KNOWN_MIRRORS = [
        "rus.hitmos.fm",
        "hitmos.fm", 
        "ru.hitmoz.org",
        "hitmoz.org", 
        "hitmotop.com",
        "hitmo.me"
    ]
    
    if "search?q=" not in page_url:
        page_url = page_url.split("?")[0]

    match = re.match(r"(https?://)([^/]+)(.*)", page_url)
    if not match:
        raise ValueError("Неверный формат URL")
        
    scheme = match.group(1)
    original_domain = match.group(2)
    path = match.group(3)

    mirrors = [m for m in KNOWN_MIRRORS if m != original_domain]
    mirrors.insert(0, original_domain)

    html = ""
    domain_used = ""
    last_error = None

    for domain in mirrors:
        test_url = f"{scheme}{domain}{path}"
        try:
            if log_cb and domain != original_domain:
                log_cb(f"[yellow]Пробуем зеркало:[/yellow] {domain}")
                
            response = requests.get(test_url, headers=HEADERS, timeout=10)
            response.raise_for_status()
            html = response.text
            domain_used = domain
            if log_cb and domain != original_domain:
                log_cb(f"[green]Зеркало {domain} успешно ответило![/green]")
            break
        except Exception as e:
            if log_cb:
                log_cb(f"[red]Зеркало {domain} недоступно:[/red] {e}")
            last_error = e
            continue

    if not html:
        raise Exception(f"Все зеркала недоступны. Последняя ошибка: {last_error}")

    soup = BeautifulSoup(html, "html.parser")
    tracks = []
    base_url = scheme + domain_used

    album_title_elem = soup.select_one(".album-title, .playlist-title, h1, meta[property='og:title']")
    album_title = album_title_elem.get("content") if album_title_elem and album_title_elem.name == "meta" else (album_title_elem.get_text(strip=True) if album_title_elem else "Single")

    unescaped_html = html.replace('\\"', '"')
    
    track_pattern = re.compile(
        r'\{"id":\d+,"artist":"([^"]+)","title":"([^"]+)"(?:(?!\{"id":).)*?"download":"([^"]+)"(?:(?!\{"id":).)*?"imageUrl":"([^"]+)"'
    )
    matches = track_pattern.findall(unescaped_html)
    
    if matches:
        seen = set()
        for artist, title, download, image in matches:
            if download in seen:
                continue
            seen.add(download)
            tracks.append({
                "artist": artist.encode('utf-8').decode('unicode_escape') if '\\u' in artist else artist,
                "title": title.encode('utf-8').decode('unicode_escape') if '\\u' in title else title,
                "album": album_title,
                "mp3_url": download.replace('\\/', '/'),
                "cover_url": image.replace('\\/', '/')
            })
        return tracks

    track_items = soup.select(".track__item, .mustrack, .track, .tracks__item")
    if not track_items:
        track_items = [soup]

    for item in track_items:
        artist_elem = item.select_one(".track__desc, .artist, .track__artist")
        title_elem = item.select_one(".track__title, .title, .track__name")
        download_btn = item.select_one("a.track__download-btn, a.download, [data-url]")
        cover_elem = item.select_one(".track__img, img")

        if not download_btn:
            continue

        mp3_url = download_btn.get("data-url") or download_btn.get("href")
        if mp3_url and not mp3_url.startswith("http"):
            mp3_url = base_url + mp3_url

        artist = artist_elem.get_text(strip=True) if artist_elem else "Unknown Artist"
        title = title_elem.get_text(strip=True) if title_elem else "Unknown Title"
        
        cover_url = None
        if cover_elem:
            cover_src = cover_elem.get("src") or cover_elem.get("data-src")
            if cover_src:
                cover_url = cover_src if cover_src.startswith("http") else base_url + cover_src

        tracks.append({
            "artist": artist,
            "title": title,
            "album": album_title,
            "mp3_url": mp3_url,
            "cover_url": cover_url
        })
        
    return tracks

def parse_yandex_music(page_url: str, log_cb=None) -> List[Dict]:
    from yandex_music import Client
    import requests
    from .config import get_yandex_token

    if log_cb:
        log_cb("[cyan]Парсинг Yandex Music...[/cyan]")
        
    token = get_yandex_token()
    if token:
        client = Client(token).init()
    else:
        client = Client().init()
        if log_cb:
            log_cb("[yellow]Внимание: Вы не указали Yandex Music токен. Персональные плейлисты (lk.) могут скачиваться не полностью или анонимно.[/yellow]")

    match = re.search(r"music\.yandex\.ru/playlists?/([A-Za-z0-9\-\.]+)", page_url)
    if not match:
        raise Exception("Invalid Yandex Music playlist URL")
        
    playlist_id = match.group(1)
    
    if playlist_id.startswith("lk."):
        try:
            resp = requests.get(page_url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=30)
            html = resp.text
            
            count_match = re.search(r'"tracksCount":(\d+)', html)
            if count_match and log_cb:
                log_cb(f"Треков в плейлисте: {count_match.group(1)}")
                
            ids = re.findall(r'\{"id":"(\d+)","albumId":', html)
            if not ids:
                ids = re.findall(r'/album/\d+/track/(\d+)', html)
                
            unique_ids = []
            for tid in ids:
                if tid not in unique_ids:
                    unique_ids.append(tid)
                    
            if not unique_ids:
                raise Exception("No tracks found in the HTML of the personal playlist.")
                
            playlist_tracks = client.tracks(unique_ids)
            tracks_data = playlist_tracks
            
        except Exception as e:
            if log_cb: log_cb(f"[red]Failed to scrape personal playlist: {e}[/red]")
            return []
    else:
        playlist_id_parts = playlist_id.split(':')
        if len(playlist_id_parts) == 1:
            playlist = client.users_playlists(playlist_id)
        else:
            playlist = client.users_playlists(kind=playlist_id_parts[1], user_id=playlist_id_parts[0])
            
        if not playlist:
            raise Exception("Playlist not found")
            
        playlist_tracks = playlist.tracks
        if playlist_tracks and not hasattr(playlist_tracks[0], 'track') and hasattr(playlist_tracks[0], 'id'):
            playlist_tracks = playlist.fetch_tracks()
            
        tracks_data = [p.track for p in playlist_tracks if p.track]

    tracks = []
    for t in tracks_data:
        artist = ", ".join(a.name for a in t.artists) if t.artists else "Unknown Artist"
        album = t.albums[0] if t.albums else None
        album_title = album.title if album else "Unknown Album"
        album_artist = album.artists[0].name if album and album.artists else t.artists[0].name if t.artists else "Unknown Artist"
        cover_url = f"https://{t.cover_uri.replace('%%', '400x400')}" if t.cover_uri else None
        
        tracks.append({
            "artist": artist,
            "album_artist": album_artist,
            "title": t.title,
            "album": album_title,
            "album_id": album.id if album else None,
            "track_id": t.id,
            "mp3_url": f"yandex://{t.id}",
            "cover_url": cover_url,
            "track_obj": t
        })
        
    return tracks

def search_hitmo(artist: str, title: str, log_cb=None) -> str:
    query = f"{artist} {title}"
    url = f"https://rus.hitmos.fm/search?q={urllib.parse.quote(query)}"
    
    if log_cb:
        log_cb(f"[cyan]Поиск на hitmo: {query}[/cyan]")
        
    try:
        tracks = parse_url(url, log_cb)
    except Exception as e:
        if log_cb: log_cb(f"[yellow]Ошибка поиска hitmo: {e}[/yellow]")
        return None
        
    if not tracks:
        if log_cb: log_cb(f"[yellow]На hitmo ничего не найдено: {query}[/yellow]")
        return None
        
    import difflib
    def similarity(s1, s2):
        if not s1 or not s2: return 0.0
        s1, s2 = s1.lower(), s2.lower()
        import re
        s1_clean = re.sub(r'[^a-zа-яё0-9\s]', '', s1).strip()
        s2_clean = re.sub(r'[^a-zа-яё0-9\s]', '', s2).strip()
        
        if s1_clean == s2_clean:
            return 1.0
        elif s2_clean.startswith(s1_clean) or s1_clean.startswith(s2_clean):
            return 0.95
        elif s1_clean in s2_clean or s2_clean in s1_clean:
            return 0.85
        return difflib.SequenceMatcher(None, s1_clean, s2_clean).ratio()

    best_track = None
    best_score = 0.0
    
    for t in tracks:
        a_score = similarity(artist, t.get("artist", ""))
        t_score = similarity(title, t.get("title", ""))
        
        if t_score >= 0.95:
            score = 0.9 + (a_score * 0.1)
        else:
            score = a_score * 0.4 + t_score * 0.6
            
        if score > best_score:
            best_score = score
            best_track = t

    if best_track and best_score > 0.75:
        if log_cb:
            try:
                log_cb(f"[green]Hitmo match: {best_track['artist']} - {best_track['title']} (score: {best_score:.2f})[/green]")
            except Exception:
                log_cb(f"[green]Hitmo match found (score: {best_score:.2f})[/green]")
        return best_track["mp3_url"]
        
    if log_cb:
        log_cb(f"[yellow]Точного совпадения нет на hitmo (лучший score: {best_score:.2f})[/yellow]")
    return None
def search_youtube(artist: str, title: str, log_cb=None) -> str:
    import difflib
    import re
    try:
        import yt_dlp
    except ImportError:
        return None
        
    query = f"{artist} - {title}"
    if log_cb:
        log_cb(f"[cyan]>8A: =0 YouTube: {query}[/cyan]")
        
    ydl_opts = {'extract_flat': True, 'quiet': True}
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(f"ytsearch5:{query}", download=False)
    except Exception as e:
        if log_cb: log_cb(f"[yellow]H81:0 ?>8A:0 YouTube: {e}[/yellow]")
        return None
        
    entries = info.get('entries', [])
    if not entries:
        if log_cb: log_cb(f"[yellow]0 YouTube =8G53> =5 =0945=>: {query}[/yellow]")
        return None
        
    def similarity(s1, s2):
        if not s1 or not s2: return 0.0
        s1, s2 = s1.lower(), s2.lower()
        s1_clean = re.sub(r'[^a-zа-яё0-9\s]', '', s1).strip()
        s2_clean = re.sub(r'[^a-zа-яё0-9\s]', '', s2).strip()
        if s1_clean == s2_clean: return 1.0
        elif s2_clean.startswith(s1_clean) or s1_clean.startswith(s2_clean): return 0.95
        elif s1_clean in s2_clean or s2_clean in s1_clean: return 0.85
        return difflib.SequenceMatcher(None, s1_clean, s2_clean).ratio()

    best_url = None
    best_score = 0.0
    
    for entry in entries:
        yt_title = entry.get('title', '')
        yt_uploader = entry.get('uploader', '')
        
        yt_title_clean = re.sub(r'[^a-zа-яё0-9]', '', yt_title.lower())
        artist_clean = re.sub(r'[^a-zа-яё0-9]', '', artist.lower())
        title_clean = re.sub(r'[^a-zа-яё0-9]', '', title.lower())
        
        is_topic = yt_uploader.endswith(" - Topic") or "release - topic" in yt_uploader.lower()
        a_score = similarity(artist, yt_uploader.replace(" - Topic", "")) if is_topic else similarity(artist, yt_uploader)
        t_score = similarity(title, yt_title)
        
        # If the YouTube title contains both the artist and the song name, it is a very strong match
        if artist_clean and title_clean and artist_clean in yt_title_clean and title_clean in yt_title_clean:
            score = 0.9
        else:
            if "cover" in yt_title.lower() and "cover" not in title.lower():
                t_score -= 0.3
            if "live" in yt_title.lower() and "live" not in title.lower():
                t_score -= 0.3
                
            score = (a_score * 0.4) + (t_score * 0.6)
            
        if is_topic:
            score += 0.2
            
        if score > best_score:
            best_score = score
            best_url = entry.get('url')

    if best_url and best_score > 0.6:
        if log_cb:
            try:
                log_cb(f"[green]YouTube match found (score: {best_score:.2f})[/green]")
            except Exception:
                log_cb(f"[green]YouTube match found[/green]")
        return f"youtube://{best_url}"
        
    if log_cb:
        log_cb(f"[yellow]5B ?>4E>4OI53> A>2?045=8O =0 YouTube (;CGH89 score: {best_score:.2f})[/yellow]")
    return None
