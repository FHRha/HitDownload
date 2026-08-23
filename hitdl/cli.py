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

from hitdl.config import get_music_dir, set_music_dir, get_env_path, get_yandex_token, set_genius_token
from hitdl.parser import parse_url, search_hitmo, search_youtube
from hitdl.downloader import download_file, download_youtube_track
from hitdl.metadata import apply_metadata

app = typer.Typer(help="HitDownload CLI - Утилита для скачивания музыки")
console = Console()

def sanitize_filename(name: str) -> str:
    return re.sub(r'[\\/*?:"<>|]', "", name).strip().rstrip('.')

@app.command()
def wizard():
    """Мастер первоначальной настройки."""
    from hitdl.config import get_music_dir, get_genius_token, get_yandex_token, set_yandex_token
    
    console.print(Panel("[bold green]Добро пожаловать в мастер настройки HitDownload![/bold green]", box=ROUNDED))
    
    current_music_dir = get_music_dir()
    music_dir = typer.prompt("Введите путь к директории для музыки (Navidrome)", default=current_music_dir)
    set_music_dir(music_dir)
    console.print(f"[green]OK Директория сохранена в .env:[/green] {music_dir}")
    
    current_genius = get_genius_token()
    genius_token = typer.prompt("Введите токен Genius API (оставьте пустым для пропуска)", default=current_genius, show_default=True if current_genius else False)
    if genius_token.strip() or current_genius:
        # If user leaves it as current, or changes it, set it
        set_genius_token(genius_token.strip())
        console.print("[green]OK Токен Genius сохранен в .env[/green]")
        
    current_yandex = get_yandex_token()
    yandex_token = typer.prompt("Введите токен Yandex Music (позволяет качать полные треки напрямую с Яндекса, оставьте пустым для пропуска)", default=current_yandex, show_default=True if current_yandex else False)
    if yandex_token.strip() or current_yandex:
        set_yandex_token(yandex_token.strip())
        console.print("[green]OK Токен Yandex Music сохранен в .env[/green]")

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
    env_path = get_env_path()
    if env_path.exists():
        env_path.unlink()
        console.print(f"[green]OK Конфигурация удалена из {env_path}[/green]")
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

def execute_downloads(tracks_list, music_dir, workers, lyrics, allow_plain, console, progress, progress_panel, errors_list):
    from concurrent.futures import ThreadPoolExecutor, as_completed
    
    with Live(progress_panel, console=console, refresh_per_second=10):
        def process_track(track):
            # Нормализация регистра для объединения SQWOZ BAB и Sqwoz Bab
            track["artist"] = track.get("artist", "Unknown Artist").title()
            
            raw_artist = track.get("album_artist")
            if not raw_artist:
                import re
                first_artist = track["artist"].split(",")[0].strip()
                first_artist = re.split(r'(?i)\s+(feat\.?|ft\.?|and|&|with|и|x|х)\s+', first_artist)[0].strip()
                raw_artist = first_artist
            
            raw_artist = raw_artist.title()
            artist = sanitize_filename(raw_artist)[:50]
            title = sanitize_filename(track["title"])
            album = sanitize_filename(track["album"])
            
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

            track_artist_raw = track.get("artist", "")
            track_artist = sanitize_filename(track_artist_raw.split(", ")[0])[:50] if track_artist_raw else artist
            
            url = track["mp3_url"]
            success = False

            if url.startswith("yandex://"):
                token = get_yandex_token()
                yandex_success = False
                search_logs = []
                
                if token and track.get("track_obj"):
                    try:
                        info = track["track_obj"].get_download_info(get_direct_links=True)
                        if info:
                            mp3_infos = [i for i in info if i.codec == 'mp3']
                            if mp3_infos:
                                best_info = sorted(mp3_infos, key=lambda x: x.bitrate_in_kbps, reverse=True)[0]
                                url = best_info.direct_link
                            else:
                                url = info[0].direct_link
                            yandex_success = True
                        else:
                            search_logs.append("Yandex Error: Нет прямых ссылок")
                    except Exception as e:
                        search_logs.append(f"Yandex Error: {e}")
                        
                if not yandex_success:
                    def logger(msg):
                        import re
                        plain = re.sub(r'\[.*?\]', '', msg)
                        search_logs.append(plain)
                            
                    fallback_urls = []
                    hitmo_url = search_hitmo(track_artist, track["title"], log_cb=logger)
                    if hitmo_url:
                        fallback_urls.append(hitmo_url)
                        
                    yt_url = search_youtube(track_artist, track["title"], log_cb=logger)
                    if yt_url:
                        fallback_urls.append(yt_url)
                        
                    if not fallback_urls:
                        reasons = " | ".join([log for log in search_logs if not log.startswith("Поиск")])
                        if not reasons:
                            reasons = "Точного совпадения по автору и названию нет на hitmo/yt"
                        cleanup(f"[red]ERROR Не найден трек: {track_artist} - {track['title']} ({reasons})[/red]", True)
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
                            search_logs.append(f"DL Error: {e}")
                            
                    if not success:
                        dl_reasons = " | ".join([log for log in search_logs if log.startswith("DL Error") or log.startswith("Yandex Error")])
                        cleanup(f"[red]ERROR Ссылки найдены, но скачивание сорвалось: {track_artist} - {track['title']} ({dl_reasons})[/red]", True)
                        return
                        
            dl_error_msg = ""
            if not success:
                try:
                    if url.startswith("youtube://"):
                        success = download_youtube_track(url, file_path, progress_cb)
                    else:
                        success = download_file(url, file_path, progress_cb)
                except Exception as e:
                    dl_error_msg = str(e)
                    success = False
            
            if success:
                progress.update(dl_task, description=f"[blue]Теги: {desc}")
                try:
                    apply_metadata(file_path, track["artist"], track["title"], track["album"], track["cover_url"], album_artist=artist)
                    
                    if lyrics:
                        progress.update(dl_task, description=f"[cyan]Текст: {desc}")
                        from hitdl.lyrics import download_track_lyrics
                        lrc_found = download_track_lyrics(
                            artist=track["artist"], 
                            title=track["title"], 
                            audio_path=file_path, 
                            album=track.get("album"),
                            synced_only=not allow_plain
                        )
                        if lrc_found:
                            console.print(f"[cyan]LRC найден: {desc}[/cyan]")
                    
                    cleanup(f"[green]OK Готово: {desc}[/green]")
                except Exception as e:
                    cleanup(f"[red]ERROR Ошибка тегов {desc}: {e}[/red]", True)
            else:
                cleanup(f"[red]ERROR Ошибка загрузки {desc}: {dl_error_msg or 'неизвестная ошибка'}[/red]", True)

        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {executor.submit(process_track, track): track for track in tracks_list}
            for future in as_completed(futures):
                try:
                    future.result()
                except Exception as e:
                    track = futures[future]
                    console.print(f"[red]CRITICAL ERROR processing {track.get('title')}: {e}[/red]")
                    errors_list.append(f"[red]CRITICAL ERROR: {e}[/red]")


@app.command()
def get(
    urls: List[str] = typer.Argument(..., help="Ссылки на треки или плейлисты (можно передать несколько)"),
    workers: int = typer.Option(10, "--workers", "-w", help="Количество потоков загрузки: больше = быстрее"),
    lyrics: bool = typer.Option(True, "--lyrics/--no-lyrics", help="Скачивать ли тексты песен (LRC)"),
    allow_plain: bool = typer.Option(False, "--allow-plain", help="Разрешить скачивание обычного текста, если синхронизированный не найден"),
    check_albums: bool = typer.Option(True, "--albums/--no-albums", help="Проверять и докачивать недостающие треки с альбомов")
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

    def download_tracks_list(tracks_list):
        execute_downloads(tracks_list, music_dir, workers, lyrics, allow_plain, console, progress, progress_panel, errors_list)

    # 1. Скачиваем основу
    download_tracks_list(tracks_to_download)

    # 2. Проверка альбомов
    if check_albums:
        try:
            from yandex_music import Client
            token = get_yandex_token()
            
            albums_to_check = {}
            for t in tracks_to_download:
                if t.get("album_id") and t.get("track_obj"):
                    aid = t["album_id"]
                    if aid not in albums_to_check:
                        albums_to_check[aid] = {"downloaded_track_ids": set(), "sample_track": t}
                    albums_to_check[aid]["downloaded_track_ids"].add(str(t["track_id"]))
            
            if albums_to_check:
                missing_tracks = []
                albums_summary = []
                
                with Live(progress_panel, console=console, refresh_per_second=10):
                    check_task = progress.add_task("[cyan]Проверка полноты альбомов...", total=len(albums_to_check))
                    client = Client(token).init() if token else Client().init()
                    
                    for aid, data in albums_to_check.items():
                        try:
                            album_obj = client.albums_with_tracks(aid)
                            if not album_obj or getattr(album_obj, 'error', None):
                                continue
                                
                            all_tracks = []
                            for vol in album_obj.volumes:
                                all_tracks.extend(vol)
                                
                            missing = []
                            for t in all_tracks:
                                if str(t.id) not in data["downloaded_track_ids"]:
                                    missing.append(t)
                                    
                            if missing:
                                album_title = album_obj.title
                                album_artist = ", ".join(a.name for a in album_obj.artists) if album_obj.artists else "Unknown"
                                albums_summary.append(f"  - [yellow]Альбом \"{album_title}\" ({album_artist})[/yellow]: не хватает {len(missing)} треков")
                                missing_tracks.extend(missing)
                        except Exception:
                            pass
                        progress.advance(check_task)
                    progress.remove_task(check_task)
                    
                if missing_tracks:
                    console.print("\n[cyan]Найдены не полностью скачанные альбомы:[/cyan]")
                    for line in albums_summary:
                        console.print(line)
                        
                    import typer
                    if typer.confirm(f"\nВ общем нужно будет докачать {len(missing_tracks)} трека(ов). Докачать все недостающие треки?", default=True):
                        albums_tracks_to_download = []
                        for t in missing_tracks:
                            artist = ", ".join(a.name for a in t.artists) if t.artists else "Unknown Artist"
                            album = t.albums[0] if t.albums else None
                            album_title = album.title if album else "Unknown Album"
                            album_artist = album.artists[0].name if album and album.artists else t.artists[0].name if t.artists else "Unknown Artist"
                            cover_url = f"https://{t.cover_uri.replace('%%', '400x400')}" if t.cover_uri else None
                            
                            albums_tracks_to_download.append({
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
                        console.print(f"[green]Докачиваем {len(albums_tracks_to_download)} треков...[/green]\n")
                        download_tracks_list(albums_tracks_to_download)
                    else:
                        console.print("[yellow]Докачка альбомов пропущена.[/yellow]\n")
        except ImportError:
            pass
        except Exception as e:
            console.print(f"[red]Ошибка при проверке альбомов: {e}[/red]")

    if errors_list:
        console.print(Panel("\n".join(errors_list), title="[bold red]Ошибки во время выполнения[/bold red]", box=ROUNDED, border_style="red"))


@app.command(name="fetch-lyrics")
def fetch_lyrics(
    path: str = typer.Argument(None, help="Путь к папке с музыкой (по умолчанию директория из настроек)"),
    allow_plain: bool = typer.Option(False, "--allow-plain", help="Разрешить скачивание обычного текста, если синхронизированный не найден")
):
    """Скачать тексты (LRC) для уже существующих файлов."""
    music_dir = path or get_music_dir()
    music_path = Path(music_dir)
    
    if not music_path.exists() or not music_path.is_dir():
        console.print(f"[red]Директория {music_dir} не найдена.[/red]")
        return
        
    from hitdl.lyrics import download_track_lyrics
    from mutagen.mp3 import MP3
    
    files = list(music_path.rglob("*.mp3"))
    if not files:
        console.print(f"[yellow]MP3 файлы не найдены в {music_dir}[/yellow]")
        return
        
    console.print(f"[cyan]Найдено {len(files)} MP3 файлов. Ищем отсутствующие тексты...[/cyan]")
    
    for f in files:
        lrc_path = f.with_suffix(".lrc")
        if lrc_path.exists():
            continue
            
        artist = ""
        title = f.stem
        album = ""
        
        try:
            audio = MP3(f)
            if audio.tags:
                artist = audio.tags.getall("TPE1")[0].text[0] if audio.tags.getall("TPE1") else ""
                title = audio.tags.getall("TIT2")[0].text[0] if audio.tags.getall("TIT2") else f.stem
                album = audio.tags.getall("TALB")[0].text[0] if audio.tags.getall("TALB") else ""
        except Exception:
            pass
            
        console.print(f"Поиск текста: {artist} - {title}...")
        found = download_track_lyrics(artist, title, str(f), album, synced_only=not allow_plain)
        if found:
            console.print(f"[green]Текст скачан: {f.name}[/green]")
        else:
            console.print(f"[yellow]Текст не найден: {f.name}[/yellow]")
            
    console.print("[bold green]Готово![/bold green]")



@app.command()
def watch(
    auto: bool = typer.Option(False, "--auto", help="Автоматический режим: скачивать всё без вопросов"),
    setup_cron: bool = typer.Option(False, "--setup-cron", help="Добавить задачу в cron (только Linux)"),
    workers: int = typer.Option(10, "-w", "--workers", help="Количество потоков загрузки"),
    lyrics: bool = typer.Option(True, "--lyrics/--no-lyrics", help="Скачивать тексты"),
    allow_plain: bool = typer.Option(False, "--allow-plain", help="Разрешить обычный текст (не LRC)")
):
    """Мониторинг Я.Музыки на предмет новых релизов для локальных артистов."""
    import platform
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from rich.panel import Panel
    from rich.table import Table
    from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeRemainingColumn
    from rich.live import Live
    from hitdl.watcher import get_local_artists, fetch_missing_releases, load_ignore_list, add_to_ignore
    from yandex_music import Client
    from hitdl.config import get_music_dir, get_yandex_token, get_repo_root
    
    if setup_cron:
        if platform.system() != "Linux":
            console.print("[red]Опция --setup-cron поддерживается только на Linux.[/red]")
            return
        import subprocess
        cron_cmd = "0 2 * * * cd " + str(get_repo_root()) + " && " + sys.executable + " -m hitdl watch --auto > /tmp/hitdl_watch.log 2>&1"
        try:
            current_cron = subprocess.check_output("crontab -l", shell=True).decode("utf-8")
        except Exception:
            current_cron = ""
        if "hitdl watch" not in current_cron:
            new_cron = current_cron.strip() + "\n" + cron_cmd + "\n"
            p = subprocess.Popen("crontab -", shell=True, stdin=subprocess.PIPE)
            p.communicate(new_cron.encode("utf-8"))
            console.print("[green]OK Задача добавлена в crontab (запуск каждый день в 2:00 ночи).[/green]")
        else:
            console.print("[yellow]Задача уже существует в crontab.[/yellow]")
        return

    music_dir = get_music_dir()
    artists = get_local_artists(music_dir)
    
    if not artists:
        console.print("[yellow]Не найдено ни одной папки артиста в библиотеке.[/yellow]")
        return
        
    token = get_yandex_token()
    client = Client(token).init() if token else Client().init()
    ignore_list = load_ignore_list(music_dir)
    
    all_missing_tracks = []
    
    progress = Progress(
        TextColumn("[bold blue]{task.description}", justify="right"),
        BarColumn(bar_width=None),
        "[progress.percentage]{task.percentage:>3.0f}%",
        expand=True
    )
    
    progress_panel = Panel(progress, title="[cyan]Поиск новых релизов[/cyan]", box=ROUNDED, border_style="cyan")
    
    with Live(progress_panel, console=console, refresh_per_second=10):
        main_task = progress.add_task("[bold cyan]Общий прогресс", total=len(artists))
        
        def process_artist(artist):
            task_id = progress.add_task(f"[yellow]{artist}", total=1)
            
            def p_cb(cur, tot):
                if tot > 0:
                    progress.update(task_id, total=tot, completed=cur)
            
            def l_cb(msg): pass
            
            tracks = []
            try:
                tracks = fetch_missing_releases(client, music_dir, artist, ignore_list, log_cb=l_cb, progress_cb=p_cb)
            except Exception as e:
                pass
                
            progress.update(task_id, completed=progress.tasks[task_id].total, description=f"[green]✔ {artist}")
            return tracks
            
        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = {executor.submit(process_artist, art): art for art in artists}
            for future in as_completed(futures):
                try:
                    res = future.result()
                    if res:
                        all_missing_tracks.extend(res)
                except Exception:
                    pass
                progress.advance(main_task)

    if not all_missing_tracks:
        console.print("[green]Все релизы ваших артистов уже скачаны![/green]")
        return
        
    # Группируем треки по артистам
    artists_releases = {}
    for t in all_missing_tracks:
        art_name = t["watcher_artist_name"]
        if art_name not in artists_releases:
            artists_releases[art_name] = {}
            
        k = (t["watcher_album_title"], t["is_single"], t["album_id"])
        if k not in artists_releases[art_name]:
            artists_releases[art_name][k] = []
        artists_releases[art_name][k].append(t)
        
    if auto:
        console.print(f"[green]Авто-режим: скачивание {len(all_missing_tracks)} треков.[/green]")
        selected_tracks = all_missing_tracks
    else:
        while True:
            # Показываем список артистов с новыми релизами
            artist_keys = list(artists_releases.keys())
            if not artist_keys:
                return
                
            table = Table(title="[bold cyan]Сводка по артистам[/bold cyan]", box=ROUNDED)
            table.add_column("№", style="dim", width=4)
            table.add_column("Артист", style="magenta")
            table.add_column("Новых релизов (Альбомов/Синглов)", style="yellow")
            table.add_column("Всего треков", style="green")
            
            for i, art in enumerate(artist_keys):
                rels = artists_releases[art]
                track_count = sum(len(trks) for trks in rels.values())
                table.add_row(str(i+1), art, str(len(rels)), str(track_count))
                
            console.print(table)
            console.print("\n[1] Скачать ВСЁ для всех артистов")
            console.print("[2] Провалиться в конкретного артиста (ввести номер)")
            console.print("[0] Отмена / Выход")
            
            choice = typer.prompt("Выберите действие", type=str, default="1")
            selected_tracks = []
            
            if choice == "1":
                for rels in artists_releases.values():
                    for trks in rels.values():
                        selected_tracks.extend(trks)
                break
            elif choice == "2":
                nums = typer.prompt("Введите номер артиста")
                try:
                    idx = int(nums.strip()) - 1
                    if 0 <= idx < len(artist_keys):
                        selected_art = artist_keys[idx]
                        selected_tracks = handle_artist_drilldown(selected_art, artists_releases[selected_art], music_dir)
                        if selected_tracks:
                            break
                except ValueError:
                    console.print("[red]Неверный ввод.[/red]")
            elif choice == "0":
                console.print("[yellow]Отменено.[/yellow]")
                return

    if not selected_tracks:
        return
        
    progress_dl = Progress(
        TextColumn("[bold blue]{task.description}", justify="right"),
        BarColumn(bar_width=None),
        "[progress.percentage]{task.percentage:>3.1f}%",
        "-",
        TimeRemainingColumn(),
        expand=True
    )
    progress_dl_panel = Panel(progress_dl, title="[green]Текущие загрузки[/green]", box=ROUNDED, border_style="green")
    errors_list = []
    
    execute_downloads(selected_tracks, music_dir, workers, lyrics, allow_plain, console, progress_dl, progress_dl_panel, errors_list)
    
    if errors_list:
        console.print(Panel("\n".join(errors_list), title="[bold red]Ошибки во время выполнения[/bold red]", box=ROUNDED, border_style="red"))

def handle_artist_drilldown(artist_name, releases_dict, music_dir):
    from hitdl.watcher import add_to_ignore
    from rich.table import Table
    from rich.box import ROUNDED
    import typer
    
    release_list = list(releases_dict.items())
    
    table = Table(title=f"[bold cyan]Релизы: {artist_name}[/bold cyan]", box=ROUNDED)
    table.add_column("№", style="dim", width=4)
    table.add_column("Тип", style="yellow")
    table.add_column("Название", style="green")
    table.add_column("Треков", style="blue")
    
    for i, ((alb, is_single, aid), tracks) in enumerate(release_list):
        rtype = "Сингл" if is_single else "Альбом"
        table.add_row(str(i+1), rtype, alb, str(len(tracks)))
        
    console.print(table)
    console.print("\n[1] Скачать ВСЁ для этого артиста")
    console.print("[2] Выбрать конкретные номера для СКАЧИВАНИЯ")
    console.print("[3] Выбрать конкретные номера для ИГНОРА")
    console.print("[0] Назад")
    
    choice = typer.prompt("Выберите действие", type=str, default="1")
    
    selected_tracks = []
    if choice == "1":
        for trks in releases_dict.values():
            selected_tracks.extend(trks)
        return selected_tracks
    elif choice == "2":
        nums = typer.prompt("Введите номера через запятую")
        for n in nums.split(","):
            if not n.strip(): continue
            try:
                idx = int(n.strip()) - 1
                if 0 <= idx < len(release_list):
                    selected_tracks.extend(release_list[idx][1])
            except ValueError:
                pass
        return selected_tracks
    elif choice == "3":
        nums = typer.prompt("Введите номера для добавления в игнор")
        for n in nums.split(","):
            if not n.strip(): continue
            try:
                idx = int(n.strip()) - 1
                if 0 <= idx < len(release_list):
                    aid = release_list[idx][0][2]
                    add_to_ignore(music_dir, artist_name, aid)
                    del releases_dict[release_list[idx][0]]
            except ValueError:
                pass
        console.print("[green]Игнор-лист обновлён. Возврат...[/green]")
        return []
    return []


def interactive_menu():
    while True:
        console.print(Panel("[bold cyan]HitDownload - Главное меню[/bold cyan]", box=ROUNDED))
        console.print("1. [green]Скачать музыку[/green] (ввести ссылки)")
        console.print("2. [yellow]Настройки (Wizard)[/yellow]")
        console.print("3. [blue]Проверка системы (Repair)[/blue]")
        console.print("4. [magenta]Очистка кэша (Clean)[/magenta]")
        console.print("5. [red]Удаление утилиты (Uninstall)[/red]")
        console.print("6. [cyan]Мониторинг Я.Музыки (Watch)[/cyan]")
        console.print("0. Выход")
        
        choice = typer.prompt("Выберите действие", type=int, default=1)
        
        if choice == 1:
            urls_str = typer.prompt("Введите ссылки (через запятую)")
            sys.argv = [sys.argv[0], "get", urls_str]
        elif choice == 2:
            sys.argv = [sys.argv[0], "wizard"]
        elif choice == 3:
            sys.argv = [sys.argv[0], "repair"]
        elif choice == 4:
            sys.argv = [sys.argv[0], "clean"]
        elif choice == 5:
            sys.argv = [sys.argv[0], "uninstall"]
        elif choice == 6:
            sys.argv = [sys.argv[0], "watch"]
        elif choice == 0:
            console.print("Выход.")
            break
        else:
            console.print("Неизвестный выбор.")
            continue
            
        try:
            app()
        except SystemExit:
            pass
            
        console.print("\n[dim]--- Нажмите Enter для возврата в меню ---[/dim]")
        input()
        console.print("\n" * 2)

def run_app():
    if len(sys.argv) == 1:
        interactive_menu()
        return

    # Если передана ссылка напрямую (не начинается с - и не является известной командой), подставляем 'get'
    if len(sys.argv) > 1 and sys.argv[1] not in ["wizard", "clean", "uninstall", "repair", "get", "fetch-lyrics", "watch", "--help", "-h"]:
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
