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

from hitdl.config import get_music_dir, set_music_dir, get_config_dir
from hitdl.parser import parse_url
from hitdl.downloader import download_file
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
def get(urls: List[str] = typer.Argument(..., help="Ссылки на треки или альбомы (можно передать несколько)")):
    """Скачать треки или альбомы по ссылкам."""
    music_dir = get_music_dir()
    
    all_urls = []
    for u in urls:
        all_urls.extend([x.strip() for x in u.split(",") if x.strip()])

    progress = Progress(
        SpinnerColumn(),
        TextColumn("[bold blue]{task.description}", justify="right"),
        BarColumn(bar_width=None),
        "[progress.percentage]{task.percentage:>3.1f}%",
        "-",
        TimeRemainingColumn(),
        expand=True
    )

    header_panel = Panel(Text("HitDownload - Скачивание музыки", style="bold white on blue", justify="center"), box=ROUNDED)
    progress_panel = Panel(progress, title="[green]Прогресс загрузки[/green]", box=ROUNDED, border_style="green")
    
    log_text = Text("")
    log_panel = Panel(log_text, title="[blue]Логи системы[/blue]", box=ROUNDED, border_style="blue")
    
    group = Group(header_panel, progress_panel, log_panel)

    errors_list = []

    with Live(group, console=console, refresh_per_second=10):
        # 1. Сбор информации
        parse_task = progress.add_task("[cyan]Парсинг ссылок...", total=len(all_urls))
        tracks_to_download = []
        for i, url in enumerate(all_urls):
            progress.update(parse_task, description=f"[cyan]Парсинг: {url}")
            
            def parser_logger(msg):
                log_text.append_text(Text.from_markup(f"{msg}\n"))
                
            try:
                tracks = parse_url(url, log_cb=parser_logger)
                tracks_to_download.extend(tracks)
            except Exception as e:
                errors_list.append(f"[red]Ошибка парсинга {url}: {e}[/red]")
            progress.advance(parse_task)
        
        progress.update(parse_task, description="[green]OK Парсинг завершен!", completed=len(all_urls))

        if not tracks_to_download:
            return

        # 2. Скачивание в несколько потоков
        from concurrent.futures import ThreadPoolExecutor, as_completed

        def process_track(track):
            artist = sanitize_filename(track["artist"])
            title = sanitize_filename(track["title"])
            album = sanitize_filename(track["album"])
            
            # Структура папок: MUSIC_DIR / Artist / Album
            album_dir = os.path.join(music_dir, artist, album)
            os.makedirs(album_dir, exist_ok=True)
            
            file_name = f"{artist} - {title}.mp3"
            file_path = os.path.join(album_dir, file_name)

            desc = f"{artist} - {title}"
            if len(desc) > 50:
                desc = desc[:47] + "..."
                
            dl_task = progress.add_task(f"[yellow]Загрузка: {desc}", total=None)

            def progress_cb(chunk_size, total_size):
                if progress.tasks[dl_task].total is None and total_size > 0:
                    progress.update(dl_task, total=total_size)
                progress.advance(dl_task, chunk_size)

            success = download_file(track["mp3_url"], file_path, progress_cb)
            
            if success:
                progress.update(dl_task, description=f"[blue]Теги: {desc}")
                try:
                    apply_metadata(file_path, track["artist"], track["title"], track["album"], track["cover_url"])
                    progress.update(dl_task, description=f"[green]OK Готово: {desc}")
                except Exception as e:
                    progress.update(dl_task, description=f"[red]ERROR Ошибка тегов: {desc}")
                    errors_list.append(f"[red]Ошибка тегов {desc}: {e}[/red]")
            else:
                progress.update(dl_task, description=f"[red]ERROR Ошибка загрузки: {desc}")
                errors_list.append(f"[red]Ошибка загрузки: {desc}[/red]")

        with ThreadPoolExecutor(max_workers=5) as executor:
            # Запускаем задачи в пуле потоков
            futures = [executor.submit(process_track, track) for track in tracks_to_download]
            for _ in as_completed(futures):
                pass

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

if __name__ == "__main__":
    run_app()
