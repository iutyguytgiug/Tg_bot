import logging
import uuid
from collections import OrderedDict
from typing import Optional

from aiogram import Router, F
from aiogram.filters import CommandStart, Command
from aiogram.types import (
    Message,
    CallbackQuery,
    FSInputFile,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    InputMediaPhoto
)
from aiogram.enums import ChatAction
from aiogram.exceptions import TelegramBadRequest

from downloader import (
    find_tiktok_url,
    download_tiktok_media,
    download_tiktok_audio,
    cleanup_files,
    TikTokMediaResult
)

logger = logging.getLogger(__name__)

router = Router()

# Кэш для хранения соответствия short_id -> original_url (ограничен 1000 записей)
class UrlCache:
    def __init__(self, maxsize: int = 1000):
        self.cache: OrderedDict[str, str] = OrderedDict()
        self.maxsize = maxsize

    def set(self, url: str) -> str:
        key = uuid.uuid4().hex[:12]
        self.cache[key] = url
        if len(self.cache) > self.maxsize:
            self.cache.popitem(last=False)
        return key

    def get(self, key: str) -> Optional[str]:
        return self.cache.get(key)

url_cache = UrlCache()


@router.message(CommandStart())
async def cmd_start(message: Message):
    """Обработка команды /start."""
    welcome_text = (
        "👋 <b>Привет! Я бот для скачивания из TikTok без водяного знака.</b>\n\n"
        "✨ <b>Что я умею:</b>\n"
        "• 📥 Скачивать видео в максимальном качестве без водяного знака (HD)\n"
        "• 🎵 Извлекать и отправлять аудиодорожку (MP3)\n"
        "• 📸 Скачивать фото-альбомы (слайдшоу)\n\n"
        "🚀 <b>Как пользоваться:</b>\n"
        "Просто отправь мне любую ссылку на TikTok (например, из приложения через «Поделиться» → «Ссылка»).\n\n"
        "<i>Поддерживаются ссылки tiktok.com, vm.tiktok.com, vt.tiktok.com и другие.</i>"
    )
    await message.answer(welcome_text, parse_mode="HTML")


@router.message(Command("help"))
async def cmd_help(message: Message):
    """Обработка команды /help."""
    help_text = (
        "ℹ️ <b>Инструкция по использованию:</b>\n\n"
        "1. Откройте TikTok и найдите понравившееся видео или фото.\n"
        "2. Нажмите <b>«Поделиться»</b> и выберите <b>«Ссылка»</b>.\n"
        "3. Отправьте скопированную ссылку в этот чат.\n"
        "4. Через несколько секунд бот пришлет готовый файл без водяных знаков!\n\n"
        "❓ <b>Если видео не скачивается:</b>\n"
        "• Проверьте, не является ли видео приватным или удаленным.\n"
        "• Проверьте, доступно ли оно в вашем регионе.\n"
        "• Попробуйте отправить ссылку еще раз через минуту."
    )
    await message.answer(help_text, parse_mode="HTML")


@router.message(F.text)
async def handle_tiktok_link(message: Message):
    """Обработка входящих сообщений с ссылками TikTok."""
    url = find_tiktok_url(message.text)
    if not url:
        # Если ссылки нет, даем подсказку
        await message.reply(
            "🔍 Отправьте корректную ссылку на видео из TikTok (например, https://vm.tiktok.com/...)",
            parse_mode="HTML"
        )
        return

    # Отправляем статус "в процессе"
    status_msg = await message.reply("⏳ <i>Скачиваю медиа без водяного знака...</i>", parse_mode="HTML")
    await message.bot.send_chat_action(chat_id=message.chat.id, action=ChatAction.UPLOAD_VIDEO)

    try:
        # Скачиваем медиа
        media_result: TikTokMediaResult = await download_tiktok_media(url)
    except Exception as e:
        logger.error(f"Ошибка при обработке {url}: {e}")
        await status_msg.edit_text(
            "❌ <b>Не удалось скачать видео.</b>\n\n"
            "Возможные причины:\n"
            "• Видео является приватным или было удалено автором\n"
            "• Ограничение доступа по региону\n"
            "• Недействительная ссылка\n\n"
            "<i>Пожалуйста, проверьте ссылку и попробуйте снова.</i>",
            parse_mode="HTML"
        )
        return

    # Сохраняем URL в кэш для кнопки скачивания аудио
    cache_key = url_cache.set(url)

    # Формируем клавиатуру
    keyboard_buttons = [
        [
            InlineKeyboardButton(text="🎵 Скачать звук (MP3)", callback_data=f"audio:{cache_key}"),
            InlineKeyboardButton(text="🔗 Оригинал", url=url)
        ]
    ]
    reply_markup = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)

    # Формируем описание (подпись)
    caption_parts = []
    if media_result.title:
        title_clean = media_result.title[:600]
        caption_parts.append(f"📝 <b>{title_clean}</b>")
    if media_result.author_name:
        author_display = media_result.author_name
        if media_result.author_username and media_result.author_username != media_result.author_name:
            author_display += f" (@{media_result.author_username})"
        caption_parts.append(f"👤 Автор: <b>{author_display}</b>")
    
    caption = "\n".join(caption_parts) if caption_parts else "🎬 <b>TikTok без водяного знака</b>"

    try:
        if media_result.media_type == "video" and media_result.file_path:
            # Проверяем размер файла (лимит Telegram Bot API 50 МБ)
            file_size_mb = media_result.file_path.stat().st_size / (1024 * 1024)
            if file_size_mb > 50:
                await status_msg.edit_text(
                    f"⚠️ Размер видео ({file_size_mb:.1f} МБ) превышает лимит Telegram в 50 МБ.",
                    reply_markup=reply_markup
                )
                cleanup_files(media_result.file_path)
                return

            video_file = FSInputFile(
                path=media_result.file_path,
                filename=f"tiktok_{media_result.video_id}.mp4"
            )

            await message.reply_video(
                video=video_file,
                caption=caption,
                parse_mode="HTML",
                duration=media_result.duration,
                width=media_result.width,
                height=media_result.height,
                supports_streaming=True,
                reply_markup=reply_markup
            )
            # Удаляем статусное сообщение
            try:
                await status_msg.delete()
            except Exception:
                pass

            cleanup_files(media_result.file_path)

        elif media_result.media_type == "images" and media_result.file_paths:
            # Слайдшоу из фото
            media_group = []
            for idx, img_path in enumerate(media_result.file_paths[:10]):  # лимит медиагруппы 10 элементов
                photo_file = FSInputFile(path=img_path)
                if idx == 0:
                    media_group.append(InputMediaPhoto(media=photo_file, caption=caption, parse_mode="HTML"))
                else:
                    media_group.append(InputMediaPhoto(media=photo_file))

            await message.reply_media_group(media=media_group)
            await message.answer("🎵 Скачать аудиодорожку:", reply_markup=reply_markup)

            try:
                await status_msg.delete()
            except Exception:
                pass

            cleanup_files(media_result.file_paths)

        else:
            await status_msg.edit_text("❌ Не удалось найти подходящие медиафайлы в этой публикации.")
    except Exception as e:
        logger.error(f"Ошибка при отправке в Telegram: {e}")
        await status_msg.edit_text("❌ Произошла ошибка при отправке файла в Telegram. Попробуйте еще раз.")
        if media_result.file_path:
            cleanup_files(media_result.file_path)
        if media_result.file_paths:
            cleanup_files(media_result.file_paths)


@router.callback_query(F.data.startswith("audio:"))
async def handle_download_audio(callback: CallbackQuery):
    """Обработчик кнопки скачивания аудио (MP3)."""
    cache_key = callback.data.split(":", 1)[1]
    url = url_cache.get(cache_key)

    if not url:
        await callback.answer("⏳ Ссылка устарела. Отправьте ссылку на видео еще раз.", show_alert=True)
        return

    await callback.answer("⏳ Скачиваю аудиодорожку...")
    await callback.bot.send_chat_action(chat_id=callback.message.chat.id, action=ChatAction.UPLOAD_VOICE)

    try:
        audio_path = await download_tiktok_audio(url)
        if not audio_path or not audio_path.exists():
            await callback.message.reply("❌ Не удалось извлечь аудиодорожку из этого видео.")
            return

        audio_file = FSInputFile(path=audio_path, filename=audio_path.name)
        await callback.message.reply_audio(
            audio=audio_file,
            caption="🎵 <b>Звук из TikTok</b>",
            parse_mode="HTML"
        )
        cleanup_files(audio_path)
    except Exception as e:
        logger.error(f"Ошибка при скачивании аудио: {e}")
        await callback.message.reply("❌ Ошибка при отправке звука.")
