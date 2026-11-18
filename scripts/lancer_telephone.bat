@echo off
rem Lance Oregdo en HTTPS sur le reseau local pour le tester sur un telephone. Double-cliquer ce fichier.
chcp 65001 >nul
cd /d "%~dp0.."
if not exist ".venv\Scripts\python.exe" (
  echo Python du projet introuvable : .venv\Scripts\python.exe
  echo Lancez d'abord l'installation decrite dans le README.
  pause
  exit /b 1
)
set OREGDO_PRECHAUFFAGE=1
echo.
echo  Demarrage... patientez environ 30 secondes, puis suivez les instructions affichees.
echo.
".venv\Scripts\python.exe" scripts\telephone_https.py
echo.
echo  Le serveur s'est arrete. Si un message d'erreur est affiche ci-dessus, copiez-le.
pause
