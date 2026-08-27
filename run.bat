@echo off
chcp 65001 >nul
title B站视频转写 - 存入 Obsidian Clippings
cd /d "%~dp0"

echo ================================================
echo   B站视频 → Markdown 转写（GPU）
echo   转写结果自动存入 D:\obsidian\Clippings\
echo ================================================
echo.

set URL=%1
if "%URL%"=="" (
    set /p URL=  请输入 B站视频链接: 
)
if "%URL%"=="" (
    echo   未输入链接，退出。
    pause
    exit /b
)

echo.
echo   正在处理: %URL%
echo   首次运行会加载模型，之后很快。转写中请勿关闭窗口...
echo.

".\venv\Scripts\python.exe" transcribe.py "%URL%" --out "D:\obsidian\Clippings"

echo.
echo   处理结束。按任意键关闭...
pause >nul
