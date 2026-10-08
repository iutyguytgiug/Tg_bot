@echo off
chcp 65001 > nul
title Telegram TikTok Downloader Bot (Python 3.14)

echo ======================================================
echo   Запуск Telegram TikTok Downloader Bot (Python 3.14)
echo ======================================================
echo.

rem Проверка наличия Python
py -3.14 --version >nul 2>&1
if %errorlevel% equ 0 (
    set PYTHON_CMD=py -3.14
) else (
    python --version >nul 2>&1
    if %errorlevel% equ 0 (
        set PYTHON_CMD=python
    ) else (
        echo [ОШИБКА] Python не найден в системе!
        echo Пожалуйста, установите Python 3.14 с python.org
        pause
        exit /b 1
    )
)

rem Проверка файла .env
if not exist .env (
    echo [ИНФО] Файл .env не найден. Создаем копию из .env.example...
    copy .env.example .env
    echo.
    echo Пожалуйста, откройте файл .env в Блокноте и укажите токен вашего бота!
    notepad .env
    pause
    exit /b 0
)

rem Установка/проверка зависимостей
echo [1/2] Проверка зависимостей...
%PYTHON_CMD% -m pip install -r requirements.txt --quiet

rem Запуск бота
echo [2/2] Запуск бота...
echo.
%PYTHON_CMD% bot.py

pause
