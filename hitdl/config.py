import os
import json
from pathlib import Path
import typer
from dotenv import load_dotenv, set_key

APP_NAME = "hitdl"

def get_config_dir() -> Path:
    config_dir = Path(typer.get_app_dir(APP_NAME))
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir

def get_config_path() -> Path:
    return get_config_dir() / "config.json"

def get_env_path() -> Path:
    return get_config_dir() / ".env"

# Инициализируем загрузку .env при импорте модуля
load_dotenv(get_env_path())

def load_config() -> dict:
    config_path = get_config_path()
    if not config_path.exists():
        return {}
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def save_config(config: dict) -> None:
    config_path = get_config_path()
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=4, ensure_ascii=False)

def get_music_dir() -> str:
    config = load_config()
    # Check env var first, then config, then default
    return os.getenv("MUSIC_DIR") or config.get("music_dir") or str(Path.home() / "Music")

def set_music_dir(path: str) -> None:
    config = load_config()
    config["music_dir"] = path
    save_config(config)

def get_yandex_token() -> str:
    # Загружаем из .env или переменных окружения
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
