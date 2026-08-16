# ---------------------------------------------------------------------------
# Compteur de derive entre les deux depots jumeaux - entree PowerShell.
#
#   .\scripts\derive.ps1 --autre C:\chemin\vers\l-autre-depot
#   .\scripts\derive.ps1 --autre ... --detail
#
# Le poste de travail est sous Windows : cette entree evite d'avoir a ouvrir
# Git Bash ou WSL pour lire un chiffre. Elle ne fait qu'appeler derive.py, qui
# porte toute la mesure - il n'y a qu'UNE implementation, sinon les deux
# entrees finiraient par rendre deux chiffres differents.
#
# Code de sortie : 0 si toute divergence est declaree, 1 sinon, 2 si le
# compteur n'a pas pu tourner.
# ---------------------------------------------------------------------------

$dossier = Split-Path -Parent $MyInvocation.MyCommand.Path

# Le rapport contient des accents et des guillemets francais. Sans cette ligne,
# une console en codepage 850 les remplace par des « ? » et deux lancements sur
# deux terminaux differents ne rendent plus les memes octets.
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}

function Trouver-Python {
    $candidats = @()
    if ($env:DERIVE_PYTHON) { $candidats += $env:DERIVE_PYTHON }
    $candidats += @("python3", "python", "py")
    foreach ($candidat in $candidats) {
        $commande = Get-Command $candidat -ErrorAction SilentlyContinue
        if (-not $commande) { continue }
        # Le moteur demande 3.9 : bornes d'expression reguliere en Unicode et
        # annotations differees.
        & $candidat -c "import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)" 2>$null
        if ($LASTEXITCODE -eq 0) { return $candidat }
    }
    return $null
}

$python = Trouver-Python
if (-not $python) {
    Write-Error @"
Python 3.9 ou plus recent est introuvable.
Indiquez-le par la variable DERIVE_PYTHON, par exemple :
  `$env:DERIVE_PYTHON = 'C:\Python314\python.exe'; .\scripts\derive.ps1 --autre ...
"@
    exit 2
}

& $python (Join-Path $dossier "derive.py") @args
exit $LASTEXITCODE
