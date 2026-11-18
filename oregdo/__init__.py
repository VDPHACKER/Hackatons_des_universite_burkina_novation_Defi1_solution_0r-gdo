"""Orẽgdo : aide à la décision pour l'assainissement (signalements vérifiés, plan de gestion, simulation multi-agents).

Compatibilité avec l'ancien nom technique du projet (« laabal_os ») : les variables d'environnement LAABAL_* encore
présentes sur une installation existante valent OREGDO_* (le nouveau nom l'emporte s'il est défini), et une base
data/laabal*.db existante est renommée en data/oregdo*.db au premier démarrage, sans perte de données.
"""
import os
from pathlib import Path

for _cle, _val in list(os.environ.items()):
    if _cle.startswith("LAABAL_"):
        os.environ.setdefault("OREGDO_" + _cle[len("LAABAL_"):], _val)


def _migrer_ancienne_base() -> None:
    donnees = Path(__file__).resolve().parent.parent / "data"
    if not donnees.is_dir():
        return
    for ancien in donnees.glob("laabal*.db"):
        nouveau = ancien.with_name("oregdo" + ancien.name[len("laabal"):])
        if nouveau.exists():
            continue
        for suffixe in ("", "-wal", "-shm"):                    # fichiers annexes du mode WAL de SQLite
            a = ancien.with_name(ancien.name + suffixe)
            if a.exists():
                a.rename(nouveau.with_name(nouveau.name + suffixe))


try:
    _migrer_ancienne_base()
except OSError:          # base ouverte par un autre processus : l'ancienne reste en place, une nouvelle base sera créée
    pass
