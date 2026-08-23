import os
from pathlib import Path
import typer
from dotenv import load_dotenv, set_key

APP_NAME = "hitdl"

def get_repo_root() -> Path:
    return Path(__file__).parent.parent

def get_env_path() -> Path:
    return get_repo_root() / ".env"

# Инициализируем загрузку .env при импорте модуля
load_dotenv(get_env_path())

def get_music_dir() -> str:
    return os.getenv("MUSIC_DIR") or str(Path.home() / "Music")

def set_music_dir(path: str) -> None:
    env_path = get_env_path()
    if not env_path.exists():
        env_path.touch()
    set_key(str(env_path), "MUSIC_DIR", path)
    os.environ["MUSIC_DIR"] = path

def get_yandex_token() -> str:
    return os.getenv("YANDEX_MUSIC_TOKEN") or ""

def set_yandex_token(token: str) -> None:
    env_path = get_env_path()
    if not env_path.exists():
        env_path.touch()
    set_key(str(env_path), "YANDEX_MUSIC_TOKEN", token)
    os.environ["YANDEX_MUSIC_TOKEN"] = token

def get_genius_token() -> str:
    return os.getenv("GENIUS_API_TOKEN") or ""

def set_genius_token(token: str) -> None:
    env_path = get_env_path()
    if not env_path.exists():
        env_path.touch()
    set_key(str(env_path), "GENIUS_API_TOKEN", token)
    os.environ["GENIUS_API_TOKEN"] = token
