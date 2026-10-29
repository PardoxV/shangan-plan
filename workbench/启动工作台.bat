@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo === 上岸计划 · 本地工作台 ===
python start_workbench.py
pause