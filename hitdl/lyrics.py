import os
import syncedlyrics
from hitdl.config import get_genius_token

PROVIDERS = ['lrclib', 'netease', 'genius']

def download_track_lyrics(artist: str, title: str, audio_path: str, album: str = None, synced_only: bool = True) -> bool:
    """
    Очищает название/артиста, ищет текст через LRCLIB, NetEase, Genius и сохраняет рядом с треком.
    По умолчанию (synced_only=True) скачивает только тексты с таймингами (.lrc).
    Если synced_only=False, может скачать и обычный текст.
    """
    if not artist or not title:
        return False

    # 1. Очистка поискового запроса от мусора, фитов и скобок
    clean_title = title.split('(')[0].split('[')[0].strip()
    clean_artist = artist.split(';')[0].split(',')[0].strip()
    
    for word in [' feat', ' ft', ' prod', ' prod by']:
        clean_title = clean_title.lower().split(word)[0].strip()

    query = f"{clean_artist} {clean_title}"
    if album and any(x in clean_title.lower() for x in ['интро', 'intro', 'скит', 'skit']):
        query += f" {album}"

    # 2. Путь сохранения файла рядом с аудио (mp3/flac/m4a)
    lrc_path = os.path.splitext(audio_path)[0] + ".lrc"

    # 3. Поиск и сохранение текста
    try:
        genius_token = get_genius_token()
        if genius_token:
            os.environ["GENIUS_API_TOKEN"] = genius_token
            
        # Если synced_only=True, передаем параметр в syncedlyrics
        lrc_content = syncedlyrics.search(query, providers=PROVIDERS, synced_only=synced_only)
        if lrc_content:
            with open(lrc_path, 'w', encoding='utf-8') as f:
                f.write(lrc_content)
            return True
    except Exception:
        pass

    return False
