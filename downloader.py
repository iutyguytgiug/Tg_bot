import os
import re
import uuid
import asyncio
import logging
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional, List
from curl_cffi import requests as cffi_requests
import yt_dlp

from config import TEMP_DIR

logger = logging.getLogger(__name__)

# Регулярные выражения для поиска ссылок
TIKTOK_URL_REGEX = re.compile(
    r'(https?://(?:www\.|vm\.|vt\.|m\.|t\.)?tiktok\.com/[^\s]+|https?://[a-zA-Z0-9\.\-]+\.tiktokv\.com/[^\s]+)',
    re.IGNORECASE
)

YOUTUBE_URL_REGEX = re.compile(
    r'(?:https?:\/\/)?(?:www\.|m\.)?(?:youtube\.com\/(?:watch\?v=|shorts\/|embed\/|v\/)|youtu\.be\/)([a-zA-Z0-9_-]{11})',
    re.IGNORECASE
)


@dataclass
class TikTokMediaResult:
    media_type: str  # "video" или "images"
    title: str = ""
    author_name: str = ""
    author_username: str = ""
    video_id: str = ""
    original_url: str = ""
    file_path: Optional[Path] = None
    file_paths: List[Path] = field(default_factory=list)
    audio_path: Optional[Path] = None
    duration: int = 0
    width: Optional[int] = None
    height: Optional[int] = None


def find_tiktok_url(text: str) -> Optional[str]:
    """Извлекает первую ссылку TikTok из текста."""
    if not text:
        return None
    match = TIKTOK_URL_REGEX.search(text)
    if match:
        # Убираем лишние знаки препинания на конце, если они прилипли
        url = match.group(0).rstrip(".,;:!?)\"'>")
        return url
    return None


def find_youtube_url(text: str) -> Optional[str]:
    """Извлекает первую ссылку YouTube из текста."""
    if not text:
        return None
    match = YOUTUBE_URL_REGEX.search(text)
    if match:
        return match.group(0).rstrip(".,;:!?)\"'>")
    return None


def _resolve_redirects(url: str) -> str:
    """Разрешает редиректы (например, для vm.tiktok.com или vt.tiktok.com)."""
    try:
        s = cffi_requests.Session(impersonate="chrome124")
        resp = s.head(url, allow_redirects=True, timeout=10)
        return resp.url
    except Exception as e:
        logger.warning(f"Ошибка при разрешении редиректа для {url}: {e}")
        return url


def _download_via_ytdlp(url: str, unique_id: str) -> Optional[TikTokMediaResult]:
    """
    Загрузка через yt-dlp с фильтрацией водяного знака.
    Возвращает видео без водяного знака или альбом изображений (слайдшоу).
    """
    out_template = str(TEMP_DIR / f"{unique_id}_%(id)s.%(ext)s")
    
    # Формат: выбираем лучший поток БЕЗ водяного знака
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'format': 'best[format_id!*=watermarked][ext=mp4]/best[format_id!*=watermarked]/best',
        'outtmpl': out_template,
        'noplaylist': False,
        'extract_flat': False,
        'socket_timeout': 20,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            
            if not info:
                return None
                
            title = info.get('title') or info.get('description') or "TikTok Video"
            author_name = info.get('uploader') or ""
            author_username = info.get('uploader_id') or author_name
            video_id = str(info.get('id', unique_id))
            duration = int(info.get('duration') or 0)
            width = info.get('width')
            height = info.get('height')

            # Проверяем, слайдшоу ли это (фото-пост)
            entries = info.get('entries')
            if entries:
                image_paths = []
                for entry in entries:
                    entry_id = entry.get('id')
                    # Ищем скачанные файлы
                    for f in TEMP_DIR.glob(f"{unique_id}_{entry_id}*"):
                        if f.is_file() and f.suffix.lower() in ('.jpg', '.jpeg', '.png', '.webp'):
                            image_paths.append(f)
                if image_paths:
                    return TikTokMediaResult(
                        media_type="images",
                        title=title,
                        author_name=author_name,
                        author_username=author_username,
                        video_id=video_id,
                        original_url=url,
                        file_paths=image_paths,
                        duration=0
                    )

            # Обычное видео
            # Ищем созданный видеофайл
            matching_files = list(TEMP_DIR.glob(f"{unique_id}_{video_id}.*"))
            if not matching_files:
                # Попробуем любой файл с префиксом unique_id
                matching_files = list(TEMP_DIR.glob(f"{unique_id}*.*"))

            for f in matching_files:
                if f.is_file() and f.suffix.lower() in ('.mp4', '.mkv', '.webm', '.mov'):
                    return TikTokMediaResult(
                        media_type="video",
                        title=title,
                        author_name=author_name,
                        author_username=author_username,
                        video_id=video_id,
                        original_url=url,
                        file_path=f,
                        duration=duration,
                        width=width,
                        height=height
                    )
    except Exception as e:
        logger.warning(f"yt-dlp не смог обработать ссылку {url}: {e}")

    return None


def _download_via_tikmate(url: str, unique_id: str) -> Optional[TikTokMediaResult]:
    """
    Запасной движок: Tikmate API через curl_cffi.
    Отдает HD видео без водяного знака.
    """
    try:
        s = cffi_requests.Session(impersonate="chrome124")
        resp = s.post(
            "https://api.tikmate.app/api/lookup",
            data={"url": url},
            headers={
                "Origin": "https://tikmate.app",
                "Referer": "https://tikmate.app/"
            },
            timeout=15
        )

        if resp.status_code != 200:
            logger.warning(f"Tikmate status code: {resp.status_code}")
            return None

        data = resp.json()
        if not data.get("success", False) and not data.get("token"):
            logger.warning(f"Tikmate error: {data.get('message')}")
            return None

        token = data.get("token")
        video_id = str(data.get("id", unique_id))
        title = data.get("desc") or "TikTok Video"
        author_name = data.get("author_name") or ""
        author_username = data.get("author_id") or author_name

        if not token or not video_id:
            return None

        # Ссылка на прямое скачивание без водяного знака в HD
        dl_url = f"https://tikmate.app/download/{token}/{video_id}.mp4?hd=1"
        out_file = TEMP_DIR / f"{unique_id}_{video_id}.mp4"

        # Скачиваем файл
        video_resp = s.get(
            dl_url,
            headers={
                "Referer": "https://tikmate.app/"
            },
            stream=True,
            timeout=30
        )

        if video_resp.status_code not in (200, 206):
            # Пробуем без ?hd=1
            dl_url = f"https://tikmate.app/download/{token}/{video_id}.mp4"
            video_resp = s.get(dl_url, headers={"Referer": "https://tikmate.app/"}, stream=True, timeout=30)
            if video_resp.status_code not in (200, 206):
                return None

        with open(out_file, "wb") as f:
            for chunk in video_resp.iter_content(chunk_size=1024 * 64):
                if chunk:
                    f.write(chunk)

        if out_file.exists() and out_file.stat().st_size > 1024:
            return TikTokMediaResult(
                media_type="video",
                title=title,
                author_name=author_name,
                author_username=author_username,
                video_id=video_id,
                original_url=url,
                file_path=out_file,
                duration=0
            )
    except Exception as e:
        logger.warning(f"Tikmate ошибка для {url}: {e}")

    return None


async def download_tiktok_media(url: str) -> TikTokMediaResult:
    """
    Основная асинхронная функция скачивания медиа из TikTok.
    Использует двухъядерный механизм: yt-dlp + Tikmate (с автоматическим failover).
    """
    unique_id = uuid.uuid4().hex[:8]

    # Сначала проверяем и разрешаем редиректы в фоновом потоке
    resolved_url = await asyncio.to_thread(_resolve_redirects, url)

    # Попытка 1: yt-dlp (дает полную информацию, размеры, длительность, слайдшоу)
    result = await asyncio.to_thread(_download_via_ytdlp, resolved_url, unique_id)
    if result:
        return result

    # Попытка 2: Tikmate (быстрый API для HD MP4 без водяного знака)
    result = await asyncio.to_thread(_download_via_tikmate, resolved_url, unique_id)
    if result:
        return result

    raise RuntimeError("Не удалось скачать видео. Возможно, видео удалено, доступ ограничен или ссылка недействительна.")


async def download_tiktok_audio(url: str) -> Optional[Path]:
    """
    Скачивание аудиодорожки из TikTok видео в формате MP3.
    """
    unique_id = uuid.uuid4().hex[:8]
    resolved_url = await asyncio.to_thread(_resolve_redirects, url)

    def _get_audio():
        out_template = str(TEMP_DIR / f"{unique_id}_audio_%(id)s.%(ext)s")
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'format': 'audio/bestaudio[ext=mp3]/bestaudio/best',
            'outtmpl': out_template,
            'socket_timeout': 20,
        }
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(resolved_url, download=True)
                audio_id = info.get('id', unique_id)
                # Ищем скачанный файл
                for f in TEMP_DIR.glob(f"{unique_id}_audio_{audio_id}*"):
                    if f.is_file():
                        return f
                for f in TEMP_DIR.glob(f"{unique_id}_audio*"):
                    if f.is_file():
                        return f
        except Exception as e:
            logger.warning(f"Ошибка при скачивании аудио yt-dlp: {e}")
        return None

    return await asyncio.to_thread(_get_audio)


def _download_via_ytdlp_youtube(url: str, unique_id: str) -> Optional[TikTokMediaResult]:
    """Загрузка видео с YouTube с помощью yt-dlp."""
    out_template = str(TEMP_DIR / f"{unique_id}_%(id)s.%(ext)s")
    
    # Для YouTube скачиваем формат mp4, стараясь ограничиться размером (около 50МБ для Telegram)
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'format': 'best[ext=mp4][filesize<=50M]/bestvideo[ext=mp4][filesize<=40M]+bestaudio[ext=m4a]/best[ext=mp4]/best',
        'outtmpl': out_template,
        'noplaylist': True,
        'socket_timeout': 20,
        'merge_output_format': 'mp4'
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            
            if not info:
                return None
                
            title = info.get('title') or "YouTube Video"
            author_name = info.get('uploader') or ""
            author_username = info.get('uploader_id') or author_name
            video_id = str(info.get('id', unique_id))
            duration = int(info.get('duration') or 0)
            width = info.get('width')
            height = info.get('height')

            matching_files = list(TEMP_DIR.glob(f"{unique_id}_{video_id}.*"))
            if not matching_files:
                matching_files = list(TEMP_DIR.glob(f"{unique_id}*.*"))

            for f in matching_files:
                if f.is_file() and f.suffix.lower() in ('.mp4', '.mkv', '.webm'):
                    return TikTokMediaResult(
                        media_type="video",
                        title=title,
                        author_name=author_name,
                        author_username=author_username,
                        video_id=video_id,
                        original_url=url,
                        file_path=f,
                        duration=duration,
                        width=width,
                        height=height
                    )
    except Exception as e:
        logger.warning(f"yt-dlp не смог скачать YouTube видео {url}: {e}")

    return None


async def download_youtube_media(url: str) -> TikTokMediaResult:
    """Асинхронная функция скачивания медиа из YouTube."""
    unique_id = uuid.uuid4().hex[:8]
    result = await asyncio.to_thread(_download_via_ytdlp_youtube, url, unique_id)
    if result:
        return result
    raise RuntimeError("Не удалось скачать видео с YouTube. Возможно оно слишком большое (>50МБ) или недоступно.")


async def download_youtube_audio(url: str) -> Optional[Path]:
    """Скачивание аудиодорожки из YouTube видео в формате MP3."""
    unique_id = uuid.uuid4().hex[:8]

    def _get_audio():
        out_template = str(TEMP_DIR / f"{unique_id}_audio_%(id)s.%(ext)s")
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'format': 'bestaudio/best',
            'outtmpl': out_template,
            'socket_timeout': 20,
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
        }
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                audio_id = info.get('id', unique_id)
                for f in TEMP_DIR.glob(f"{unique_id}_audio_{audio_id}*"):
                    if f.is_file():
                        return f
                for f in TEMP_DIR.glob(f"{unique_id}_audio*"):
                    if f.is_file():
                        return f
        except Exception as e:
            logger.warning(f"Ошибка при скачивании аудио YouTube: {e}")
        return None

    return await asyncio.to_thread(_get_audio)


def cleanup_files(*paths: Optional[Path]):
    """Удаляет временные файлы."""
    for p in paths:
        if p and isinstance(p, Path) and p.exists():
            try:
                p.unlink()
            except Exception as e:
                logger.warning(f"Не удалось удалить файл {p}: {e}")
        elif p and isinstance(p, list):
            for sub_p in p:
                cleanup_files(sub_p)
