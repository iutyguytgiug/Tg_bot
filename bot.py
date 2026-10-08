import sys
import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from config import BOT_TOKEN, validate_config
from handlers import router

# Корректный вывод UTF-8 в консоли Windows
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("tiktok_bot")


async def main():
    """Точка входа запуска бота."""
    if not validate_config():
        sys.exit(1)

    # Инициализация бота и диспетчера
    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )
    dp = Dispatcher()

    # Подключаем роутер с обработчиками
    dp.include_router(router)

    # Удаляем старые обновления (накопившиеся пока бот был оффлайн)
    await bot.delete_webhook(drop_pending_updates=True)

    bot_info = await bot.get_me()
    logger.info(f"Бот успешно запущен: @{bot_info.username} (ID: {bot_info.id})")
    print("\n" + "=" * 60)
    print(f"  Бот @{bot_info.username} готов к работе!")
    print("  Отправьте ему ссылку на видео из TikTok в Telegram.")
    print("  Нажмите Ctrl + C для остановки бота.")
    print("=" * 60 + "\n")

    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()
        logger.info("Бот остановлен.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("\nБот выключен.")
