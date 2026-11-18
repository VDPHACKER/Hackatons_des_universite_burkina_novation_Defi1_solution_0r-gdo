@echo off
rem Orẽgdo : crée (ou remet à zéro) un compte par rôle et affiche les mots de passe. Double-cliquer ce fichier.
rem   comptes.bat                  -> un mot de passe lisible par compte (ex. kaya-vert-soleil-47)
rem   comptes.bat mon-mot-commun   -> le même mot de passe pour tous les comptes de démonstration
rem Les identifiants et mots de passe sont aussi notés dans comptes_demo.txt (hors du dépôt Git).
chcp 65001 >nul
cd /d "%~dp0.."
if not exist ".venv\Scripts\python.exe" (
  echo L'application n'est pas encore installee : lancez d'abord  powershell -ExecutionPolicy Bypass -File scripts\deployer.ps1
  pause
  exit /b 1
)
if "%~1"=="" (
  ".venv\Scripts\python.exe" -m oregdo.comptes demo
) else (
  ".venv\Scripts\python.exe" -m oregdo.comptes demo --mdp "%~1"
)
echo.
echo Pas besoin de redemarrer le serveur : les comptes sont actifs tout de suite.
pause
