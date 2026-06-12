@echo off
chcp 65001 >nul
title 廣東話會議錄音轉文字
cd /d "%~dp0"
start "" pyw run-desktop.pyw
