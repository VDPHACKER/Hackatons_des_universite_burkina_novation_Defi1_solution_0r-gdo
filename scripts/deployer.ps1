<#
Deploiement d'Oregdo en UNE commande (Windows 10/11, PowerShell) :

    powershell -ExecutionPolicy Bypass -File scripts\deployer.ps1

Ce script : verifie Python 3.12, cree l'environnement .venv, installe les dependances (une seule fois, ou quand
requirements.txt change), cree l'administrateur avec un mot de passe aleatoire affiche une seule fois, puis demarre le serveur.

Options :
    -Port 8000        port d'ecoute (le suivant est pris s'il est occupe)
    -Commune ouaga    pack de commune a servir (ouaga, bobo...)
    -Reseau           ecoute sur tout le reseau local (pour un telephone ou un autre PC) au lieu de l'ordinateur seul
    -SansDemarrer     prepare tout (environnement, dependances, administrateur) sans lancer le serveur
#>
param([int]$Port = 8000, [string]$Commune = "ouaga", [switch]$Reseau, [switch]$SansDemarrer)
$ErrorActionPreference = "Stop"
$racine = Split-Path -Parent $PSScriptRoot
Set-Location $racine
if ($racine.Length -gt 110) {
    Write-Host "ATTENTION : le chemin du projet est long ($($racine.Length) caracteres). Windows limite les chemins a 260 caracteres : si l'installation echoue avec 'No such file or directory', deplacez le projet dans un dossier court (par exemple C:\oregdo) et relancez." -ForegroundColor Yellow
}
function Etape($t) { Write-Host ""; Write-Host "== $t" -ForegroundColor Green }
function Echec($t) { Write-Host ""; Write-Host "ERREUR : $t" -ForegroundColor Red; exit 1 }

Etape "1/4  Python 3.12"
$py = $null
foreach ($essai in @(@("py", "-3.12"), @("python"), @("python3"))) {
    try {
        $exe = $essai[0]; $args1 = @($essai | Select-Object -Skip 1)
        $v = & $exe @args1 -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
        if ($LASTEXITCODE -eq 0 -and $v -eq "3.12") { $py = @($exe) + $args1; break }
    } catch { }
}
if (-not $py) { Echec "Python 3.12 est introuvable. Installez-le depuis https://www.python.org/downloads/ (cochez 'Add python.exe to PATH'), puis relancez cette commande." }
Write-Host "Python 3.12 trouve : $($py -join ' ')"

Etape "2/4  Environnement et dependances"
$venvPy = Join-Path $racine ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPy)) {
    & $py[0] @($py | Select-Object -Skip 1) -m venv .venv
    if ($LASTEXITCODE -ne 0) { Echec "Impossible de creer l'environnement .venv." }
}
$empreinte = (Get-FileHash requirements.txt -Algorithm SHA256).Hash
$marque = Join-Path $racine ".venv\.requirements.sha"
if ((Test-Path $marque) -and ((Get-Content $marque -Raw).Trim() -eq $empreinte)) {
    Write-Host "Dependances deja installees (requirements.txt inchange)."
} else {
    Write-Host "Installation des dependances (plusieurs minutes la premiere fois)..."
    & $venvPy -m pip install --disable-pip-version-check --quiet -r requirements.txt
    if ($LASTEXITCODE -ne 0) { Echec "L'installation des dependances a echoue. Verifiez la connexion Internet puis relancez." }
    Set-Content -Path $marque -Value $empreinte -Encoding ASCII
}

Etape "3/4  Premier demarrage (donnees et administrateur)"
$env:OREGDO_COMMUNE = $Commune
& $venvPy scripts\premier_demarrage.py
if ($LASTEXITCODE -ne 0) { Echec "Le premier demarrage a echoue." }

if ($SansDemarrer) { Write-Host ""; Write-Host "Tout est pret. Pour demarrer : .venv\Scripts\python.exe -m uvicorn oregdo.app:app --port $Port"; exit 0 }

Etape "4/4  Demarrage du serveur"
$libre = $false
$demande = $Port
for ($p = $Port; $p -lt ($Port + 20); $p++) {
    $occupe = Get-NetTCPConnection -State Listen -LocalPort $p -ErrorAction SilentlyContinue
    if (-not $occupe) { $Port = $p; $libre = $true; break }
}
if (-not $libre) { Echec "Aucun port libre entre $Port et $($Port + 19). Fermez les anciens serveurs." }
$hote = if ($Reseau) { "0.0.0.0" } else { "127.0.0.1" }
Write-Host ""
Write-Host "  Application : http://127.0.0.1:$Port/   (API : http://127.0.0.1:$Port/docs)" -ForegroundColor Cyan
if ($Reseau) { Write-Host "  Sur le reseau local : http://<adresse-de-cet-ordinateur>:$Port/   (un telephone exige HTTPS : voir le README, section Sur un telephone)" -ForegroundColor Cyan }
if ($Port -ne $demande) { Write-Host "  ATTENTION : le port $demande est deja pris par un autre programme. Utilisez bien l'adresse ci-dessus (port $Port)." -ForegroundColor Yellow }
Write-Host "  Comptes des autres profils (mairie, brigade, pre-collecteur) : double-cliquer scripts\comptes.bat" -ForegroundColor Cyan
Write-Host "  Ctrl+C pour arreter."
Write-Host ""
& $venvPy -m uvicorn oregdo.app:app --host $hote --port $Port
