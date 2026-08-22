import os
import requests
from typing import Callable

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
}



def download_file(url: str, output_path: str, progress_callback: Callable[[int, int], None] = None) -> bool:
    with requests.get(url, headers=HEADERS, stream=True, timeout=30) as r:
        r.raise_for_status()
        total_size = int(r.headers.get("content-length", 0))
        if progress_callback and total_size > 0:
            progress_callback(0, total_size)
            
        with open(output_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
                    if progress_callback:
                        progress_callback(len(chunk), total_size)
    return True
def download_youtube_track(url: str, output_path: str, progress_callback=None) -> bool:
    import yt_dlp
    import os
    import subprocess
    
    if url.startswith("youtube://"):
        url = url.replace("youtube://", "")
        
    base_path = output_path
    if base_path.endswith('.mp3'):
        base_path = base_path[:-4]
        
    class MyLogger:
        def debug(self, msg): pass
        def warning(self, msg): pass
        def error(self, msg): pass

    last_downloaded = [0]
    def yt_progress_hook(d):
        if d['status'] == 'downloading':
            total = d.get('total_bytes') or d.get('total_bytes_estimate', 0)
            downloaded = d.get('downloaded_bytes', 0)
            if progress_callback and total > 0:
                chunk = downloaded - last_downloaded[0]
                if chunk > 0:
                    progress_callback(chunk, total)
                    last_downloaded[0] = downloaded

    ffmpeg_exe = "ffmpeg"
    try:
        import imageio_ffmpeg
        ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        pass

    import uuid
    temp_id = uuid.uuid4().hex[:8]
    temp_base = os.path.join(os.path.dirname(base_path), f"temp_yt_{temp_id}")
    
    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': temp_base + '.%(ext)s',
        'logger': MyLogger(),
        'quiet': True,
        'noprogress': True,
        'progress_hooks': [yt_progress_hook],
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
            
        import glob
        import shutil
        
        downloaded_files = glob.glob(temp_base + ".*")
        if not downloaded_files:
            raise RuntimeError("Файл не был скачан yt-dlp")
            
        for f in downloaded_files:
            if not f.endswith('.mp3'):
                subprocess.check_call([
                    ffmpeg_exe, "-y", "-i", f,
                    "-acodec", "libmp3lame", "-b:a", "192k",
                    output_path
                ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                os.remove(f)
            else:
                shutil.move(f, output_path)
            break
            
        return True
    except Exception as e:
        raise RuntimeError(f"Youtube download error: {e}")
