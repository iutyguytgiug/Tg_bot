import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Загружаем .env
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
TEMP_DIR = Path(os.getenv("TEMP_DIR", "temp_downloads"))

# Создаем временную директорию, если ее еще нет
TEMP_DIR.mkdir(parents=True, exist_ok=True)

def validate_config() -> bool:
    """Проверка корректности конфигурации."""
    if not BOT_TOKEN or BOT_TOKEN == "ВАШ_ТОКЕН_БОТА_ЗДЕСЬ":
        print("=" * 60, flush=True)
        print(" ОШИБКА: Не указан токен бота в файле .env!", flush=True)
        print(" Откройте файл .env и укажите токен от @BotFather:", flush=True)
        print(" BOT_TOKEN=123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ", flush=True)
        print("=" * 60, flush=True)
        return False
    return True
