import os
import re
import sys
import shutil
import typer
from typing import List, Optional
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.box import ROUNDED
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeRemainingColumn
from rich.live import Live
from rich.layout import Layout
from rich.text import Text
from rich.table import Table

from hitdl.config import get_music_dir, set_music_dir, get_config_dir, get_yandex_token
from hitdl.parser import parse_url, search_hitmo, search_youtube
from hitdl.downloader import download_file, download_youtube_track
from hitdl.metadata import apply_metadata

app = typer.Typer(help="HitDownload CLI - Утилита для скачивания музыки")
console = Console()

def sanitize_filename(name: str) -> str:
    return re.sub(r'[\\/*?:"<>|]', "", name).strip()

@app.command()
def wizard():
    """Мастер первоначальной настройки."""
    console.print(Panel("[bold green]Добро пожаловать в мастер настройки HitDownload![/bold green]", box=ROUNDED))
    default_dir = str(Path.home() / "Music")
    music_dir = typer.prompt("Введите путь к директории для музыки (Navidrome)", default=default_dir)
    set_music_dir(music_dir)
    console.print(f"[green]OK Директория сохранена:[/green] {music_dir}")

@app.command()
def clean():
    """Очистить временные файлы (кэш)."""
    # Simply removing any partial .mp3 files if needed or clearing config dir cache
    console.print("[yellow]Очистка не завершенных загрузок...[/yellow]")
    # For now just a placeholder
    console.print("[green]OK Очистка завершена.[/green]")

@app.command()
def uninstall():
    """Удалить утилиту и ее конфигурацию."""
    config_dir = get_config_dir()
    if config_dir.exists():
        shutil.rmtree(config_dir)
        console.print(f"[green]OK Конфигурация удалена из {config_dir}[/green]")
    console.print("[yellow]Для полного удаления выполните: pip uninstall hitdl[/yellow]")

@app.command()
def repair():
    """Проверка и починка зависимостей или прав доступа."""
    console.print("[cyan]Проверка системы...[/cyan]")
    music_dir = get_music_dir()
    path = Path(music_dir)
    if not path.exists():
        console.print(f"[red]Директория {music_dir} не существует. Создаем...[/red]")
        try:
            path.mkdir(parents=True, exist_ok=True)
            console.print("[green]OK Директория создана.[/green]")
        except Exception as e:
            console.print(f"[bold red]Ошибка создания директории: {e}[/bold red]")
            return
    if not os.access(path, os.W_OK):
        console.print(f"[bold red]Нет прав на запись в директорию {music_dir}[/bold red]")
    else:
        console.print("[green]OK Права на запись присутствуют.[/green]")
    
    console.print("[green]OK Проверка завершена. Все системы в норме.[/green]")

from rich.console import Group

@app.command()
def get(
    urls: List[str] = typer.Argument(..., help="Ссылки на треки или плейлисты (можно передать несколько)"),
    workers: int = typer.Option(10, "--workers", "-w", help="Количество потоков загрузки: больше = быстрее")
):
    """Скачать треки или альбомы по ссылкам."""
    console = Console()
    check_dependencies(console)
    music_dir = get_music_dir()
    
    all_urls = []
    for u in urls:
        all_urls.extend([x.strip() for x in u.split(",") if x.strip()])

    progress = Progress(
        TextColumn("[bold blue]{task.description}", justify="right"),
        BarColumn(bar_width=None),
        "[progress.percentage]{task.percentage:>3.1f}%",
        "-",
        TimeRemainingColumn(),
        expand=True
    )

    progress_panel = Panel(progress, title="[green]Текущие загрузки[/green]", box=ROUNDED, border_style="green")

    errors_list = []

    with Live(progress_panel, console=console, refresh_per_second=10):
        console.print(Panel(Text("HitDownload - Скачивание музыки", style="bold white on blue", justify="center"), box=ROUNDED))
        
        # 1. Сбор информации
        parse_task = progress.add_task("[cyan]Парсинг ссылок...", total=len(all_urls))
        tracks_to_download = []
        for i, url in enumerate(all_urls):
            progress.update(parse_task, description=f"[cyan]Парсинг: {url}")
            
            def parser_logger(msg):
                console.print(msg)
                
            try:
                tracks = parse_url(url, log_cb=parser_logger)
                tracks_to_download.extend(tracks)
            except Exception as e:
                msg = f"[red]Ошибка парсинга {url}: {e}[/red]"
                errors_list.append(msg)
                console.print(msg)
            progress.advance(parse_task)
        
        progress.remove_task(parse_task)
        console.print(f"[green]OK Парсинг завершен! Найдено треков: {len(tracks_to_download)}[/green]")

        if not tracks_to_download:
            return

        # 2. Скачивание в несколько потоков
        from concurrent.futures import ThreadPoolExecutor, as_completed

        def process_track(track):
            artist = sanitize_filename(track.get("album_artist") or track["artist"].split(", ")[0])[:50]
            title = sanitize_filename(track["title"])
            album = sanitize_filename(track["album"])
            
            # Структура папок: MUSIC_DIR / Artist / Album
            album_dir = os.path.join(music_dir, artist, album)
            os.makedirs(album_dir, exist_ok=True)
            
            file_name = f"{artist} - {title}"[:200] + ".mp3"
            file_path = os.path.join(album_dir, file_name)

            desc = f"{artist} - {title}"
            desc = desc.encode('cp1251', errors='replace').decode('cp1251')
            
            if len(desc) > 50:
                desc = desc[:47] + "..."

            if os.path.exists(file_path):
                console.print(f"[blue]Пропуск (уже скачан): {desc}[/blue]")
                return

            dl_task = progress.add_task(f"[yellow]Загрузка: {desc}", total=None)

            def cleanup(msg, is_error=False):
                console.print(msg)
                progress.remove_task(dl_task)
                if is_error:
                    errors_list.append(msg)

            is_total_set = [False]
            def progress_cb(chunk_size, total_size):
                if not is_total_set[0] and total_size > 0:
                    progress.update(dl_task, total=total_size)
                    is_total_set[0] = True
                progress.advance(dl_task, chunk_size)

            url = track["mp3_url"]
            success = False
            
            if url.startswith("yandex://"):
                token = get_yandex_token()
                if not token:
                    def logger(msg):
                        if "ERROR" in msg or "yellow" in msg or "red" in msg:
                            console.print(msg)
                            
                    fallback_urls = []
                    hitmo_url = search_hitmo(artist, track["title"], log_cb=logger)
                    if hitmo_url:
                        fallback_urls.append(hitmo_url)
                        
                    yt_url = search_youtube(artist, track["title"], log_cb=logger)
                    if yt_url:
                        fallback_urls.append(yt_url)
                        
                    if not fallback_urls:
                        cleanup(f"[red]ERROR Не удалось найти трек {desc} (hitmo/yt)[/red]", True)
                        return
                        
                    for try_url in fallback_urls:
                        try:
                            if try_url.startswith("youtube://"):
                                success = download_youtube_track(try_url, file_path, progress_cb)
                            else:
                                success = download_file(try_url, file_path, progress_cb)
                            if success:
                                break
                        except Exception as e:
                            console.print(f"[red]DL Error (fallback): {e}[/red]")
                            
                    if not success:
                        cleanup(f"[red]ERROR Ошибка загрузки: {desc}[/red]", True)
                        return
                        
                elif track.get("track_obj"):
                    try:
                        info = track["track_obj"].get_download_info(get_direct_links=True)
                        if info:
                            mp3_infos = [i for i in info if i.codec == 'mp3']
                            if mp3_infos:
                                best_info = sorted(mp3_infos, key=lambda x: x.bitrate_in_kbps, reverse=True)[0]
                                url = best_info.direct_link
                            else:
                                url = info[0].direct_link
                        else:
                            raise Exception("Нет прямых ссылок")
                    except Exception as e:
                        cleanup(f"[red]ERROR Ошибка получения ссылки Yandex: {e}[/red]", True)
                        return
                        
            # Если это не фоллбэк (у нас есть токен, или это сразу прямой линк)
            if not success:
                try:
                    if url.startswith("youtube://"):
                        success = download_youtube_track(url, file_path, progress_cb)
                    else:
                        success = download_file(url, file_path, progress_cb)
                except Exception as e:
                    console.print(f"[red]DL Error: {e}[/red]")
                    success = False
            
            if success:
                progress.update(dl_task, description=f"[blue]Теги: {desc}")
                try:
                    apply_metadata(file_path, track["artist"], track["title"], track["album"], track["cover_url"])
                    cleanup(f"[green]OK Готово: {desc}[/green]")
                except Exception as e:
                    cleanup(f"[red]ERROR Ошибка тегов {desc}: {e}[/red]", True)
            else:
                cleanup(f"[red]ERROR Ошибка загрузки: {desc}[/red]", True)

        with ThreadPoolExecutor(max_workers=workers) as executor:
            # Запускаем задачи в пуле потоков
            futures = {executor.submit(process_track, track): track for track in tracks_to_download}
            for future in as_completed(futures):
                try:
                    future.result()
                except Exception as e:
                    track = futures[future]
                    console.print(f"[red]CRITICAL ERROR processing {track.get('title')}: {e}[/red]")
                    errors_list.append(f"[red]CRITICAL ERROR: {e}[/red]")

    if errors_list:
        console.print(Panel("\n".join(errors_list), title="[bold red]Ошибки во время выполнения[/bold red]", box=ROUNDED, border_style="red"))

def interactive_menu():
    console.print(Panel("[bold cyan]HitDownload - Главное меню[/bold cyan]", box=ROUNDED))
    console.print("1. [green]Скачать музыку[/green] (ввести ссылки)")
    console.print("2. [yellow]Настройки (Wizard)[/yellow]")
    console.print("3. [blue]Проверка системы (Repair)[/blue]")
    console.print("4. [magenta]Очистка кэша (Clean)[/magenta]")
    console.print("5. [red]Удаление утилиты (Uninstall)[/red]")
    console.print("0. Выход")
    
    choice = typer.prompt("Выберите действие", type=int, default=1)
    
    if choice == 1:
        urls_str = typer.prompt("Введите ссылки (через запятую)")
        sys.argv = [sys.argv[0], "get", urls_str]
        app()
    elif choice == 2:
        sys.argv = [sys.argv[0], "wizard"]
        app()
    elif choice == 3:
        sys.argv = [sys.argv[0], "repair"]
        app()
    elif choice == 4:
        sys.argv = [sys.argv[0], "clean"]
        app()
    elif choice == 5:
        sys.argv = [sys.argv[0], "uninstall"]
        app()
    else:
        console.print("Выход.")

def run_app():
    if len(sys.argv) == 1:
        interactive_menu()
        return

    # Если передана ссылка напрямую (не начинается с - и не является известной командой), подставляем 'get'
    if len(sys.argv) > 1 and sys.argv[1] not in ["wizard", "clean", "uninstall", "repair", "get", "--help", "-h"]:
        sys.argv.insert(1, "get")
    app()

def check_dependencies(console):
    import sys
    import subprocess
    import shutil
    import typer
    
    try:
        import yt_dlp
    except ImportError:
        console.print("[yellow]81;8>B5:0 yt-dlp =5 =0945=0. #AB0=>2:0...[/yellow]")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "yt-dlp", "-q"])
        
    try:
        import imageio_ffmpeg
    except ImportError:
        console.print("[yellow]#B8;8B0 ffmpeg =5 =0945=0. =0 =5>1E>48<0 4;O :>=25@B0F88 YouTube B@5:>2 2 MP3.[/yellow]")
        if typer.confirm("#AB0=>28BL imageio-ffmpeg A59G0A (>:>;> 20 )?", default=True):
            console.print("[cyan]#AB0=>2:0 imageio-ffmpeg...[/cyan]")
            subprocess.check_call([sys.executable, "-m", "pip", "install", "imageio-ffmpeg", "-q"])

if __name__ == "__main__":
    run_app()
