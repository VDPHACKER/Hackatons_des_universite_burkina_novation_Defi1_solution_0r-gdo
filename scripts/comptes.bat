@echo off
rem Oregdo : cree (ou remet a zero) un compte par role : admin, mairie, brigade, precollecteur.
rem Double-cliquer ce fichier. Le meme mot de passe est donne aux 4 comptes et affiche a la fin.
rem   comptes.bat                -> mot de passe lisible tire au hasard (ex. kaya-vert-soleil-47)
rem   comptes.bat mon-mot-commun -> ce mot de passe-la (8 caracteres minimum)
rem Les comptes sont crees dans l'application lancee avec scripts\deployer.ps1 (base data\oregdo.db)
rem ET dans le conteneur Docker s'il tourne (docker compose up) : chacun a sa propre base.
setlocal
chcp 65001 >nul
cd /d "%~dp0.."
set "MDP=%~1"
set "LOCAL="
set "CONTENEUR="
if exist ".venv\Scripts\python.exe" set "LOCAL=1"
for /f %%i in ('docker compose ps -q --status running oregdo 2^>nul') do set "CONTENEUR=%%i"
if not defined LOCAL if not defined CONTENEUR (
  echo L'application n'est ni installee ni lancee.
  echo Lancez d'abord : powershell -ExecutionPolicy Bypass -File scripts\deployer.ps1   ou   docker compose up --build
  pause
  exit /b 1
)
rem Mot de passe commun : tire au hasard par l'application (locale, sinon Docker) s'il n'est pas donne.
if not "%MDP%"=="" goto :creer
if defined LOCAL goto :mdp_local
goto :mdp_docker
:mdp_local
for /f "delims=" %%p in ('.venv\Scripts\python.exe -c "from oregdo.comptes import mot_de_passe_lisible as m; print(m())"') do set "MDP=%%p"
goto :creer
:mdp_docker
for /f "delims=" %%p in ('docker compose exec -T oregdo python -c "from oregdo.comptes import mot_de_passe_lisible as m; print(m())"') do set "MDP=%%p"
:creer
if not defined LOCAL goto :docker
echo === Application locale, lancee par scripts\deployer.ps1 ===
".venv\Scripts\python.exe" -m oregdo.comptes demo --mdp "%MDP%"
:docker
if not defined CONTENEUR goto :fin
echo === Application Docker, lancee par docker compose ===
docker compose exec -T oregdo python -m oregdo.comptes demo --mdp "%MDP%"
:fin
echo.
echo ==================================================================
echo   Identifiants : admin, mairie, brigade, precollecteur
echo   Mot de passe (le meme pour les 4) : %MDP%
echo ==================================================================
echo Pas besoin de redemarrer le serveur : les comptes sont actifs tout de suite.
endlocal
pause
