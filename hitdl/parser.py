import re
import requests
from bs4 import BeautifulSoup
from typing import List, Dict

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

def parse_url(page_url: str, log_cb=None) -> List[Dict[str, str]]:
    # Очищаем URL от мусорных параметров типа ?ysclid=...
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

    # Album title parsing
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

    # 2. Fallback to HTML parsing (old Hitmo)
    track_items = soup.select(".track__item, .mustrack, .track")
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
