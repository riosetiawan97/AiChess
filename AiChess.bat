@echo off
rem Launcher panel kontrol AiChess (double-click saja)
cd /d %~dp0
start "" .venv\Scripts\pythonw.exe -m chessbot.gui
