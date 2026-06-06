@echo off
echo Building VoiceCommands.exe ...

echo Closing any running VoiceCommands instances...
taskkill /F /IM VoiceCommands.exe >nul 2>&1
timeout /t 1 /nobreak >nul

pip install pyinstaller certifi >nul 2>&1

pyinstaller ^
  --onefile ^
  --noconsole ^
  --name VoiceCommands ^
  --add-data "version.txt;." ^
  main.py

if errorlevel 1 (
    echo Build failed!
    pause
    exit /b 1
)

echo.
echo Copying Vosk model into dist\ ...
xcopy /E /I /Y "vosk-model-small-en-us-0.15" "dist\vosk-model-small-en-us-0.15"

echo.
echo Done! Contents of dist\:
dir /B dist\

echo.
echo Pushing updated exe to GitHub...
git add dist\VoiceCommands.exe version.txt
git commit -m "Release: update exe and version"
git push

echo.
echo Done! Share this link to download the latest exe:
echo https://github.com/xXBunchXx/Voice-commands/raw/main/dist/VoiceCommands.exe
echo.
pause
