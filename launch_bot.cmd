@echo off
cd /d "%~dp0"
call run_bot.bat %* >> data\bot.out.log 2>> data\bot.err.log
