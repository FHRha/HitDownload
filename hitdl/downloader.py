import os
import requests
from typing import Callable

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
}

def download_file(url: str, output_path: str, progress_callback: Callable[[int, int], None] = None) -> bool:
    try:
        with requests.get(url, headers=HEADERS, stream=True, timeout=30) as r:
            r.raise_for_status()
            total_size = int(r.headers.get("content-length", 0))
            if progress_callback and total_size > 0:
                progress_callback(0, total_size)
            
            with open(output_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=65536):
                    if chunk:
                        f.write(chunk)
                        if progress_callback:
                            progress_callback(len(chunk), total_size)
        return True
    except Exception as e:
        return False
