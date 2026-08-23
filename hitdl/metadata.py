import requests
from mutagen.mp3 import MP3
from mutagen.id3 import ID3, TIT2, TPE1, TPE2, TALB, APIC, ID3NoHeaderError

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
}

def apply_metadata(mp3_path: str, artist: str, title: str, album: str = "Single", cover_url: str = None, album_artist: str = None) -> None:
    try:
        try:
            audio = MP3(mp3_path, ID3=ID3)
            audio.delete()  # Полностью удаляем старые теги (водяные знаки и чужие обложки)
        except Exception:
            pass

        audio = MP3(mp3_path)
        audio.add_tags()

        audio.tags.add(TPE1(encoding=3, text=artist))
        audio.tags.add(TIT2(encoding=3, text=title))
        audio.tags.add(TALB(encoding=3, text=album))
        if album_artist:
            audio.tags.add(TPE2(encoding=3, text=album_artist))

        if cover_url:
            try:
                img_data = requests.get(cover_url, headers=HEADERS, timeout=15).content
                audio.tags.add(
                    APIC(
                        encoding=3,
                        mime="image/jpeg",
                        type=3,
                        desc="Cover",
                        data=img_data
                    )
                )
            except Exception as e:
                pass # Fail silently on cover

        audio.save(v2_version=3)
    except Exception as e:
        raise RuntimeError(f"Metadata error: {e}")
