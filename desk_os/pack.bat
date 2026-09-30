@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONUTF8=1

where python >nul 2>&1
if %errorlevel%==0 (
  python pack.py
) else (
  py -3 pack.py
)
set ERR=%errorlevel%

echo.
if %ERR%==0 (
  echo 完成。安装包在 release\DeskOS-Setup.exe
  echo 以后改过程序，再双击 pack.bat，就会按最新功能重新打包。
) else (
  echo 打包失败，请看上面的报错。
)
pause
exit /b %ERR%
