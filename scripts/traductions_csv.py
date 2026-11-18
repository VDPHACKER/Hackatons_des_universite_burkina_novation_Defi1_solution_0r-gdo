"""Feuille de traduction pour les locuteurs natifs : exporte les textes à traduire en CSV (Excel), puis recharge le CSV rempli.

    python scripts/traductions_csv.py exporter                 # écrit livrables/traductions_a_valider.csv
    python scripts/traductions_csv.py importer fichier.csv     # met à jour web/data/i18n/dyu.json et mos.json (statut « brouillon »)
    python scripts/traductions_csv.py importer fichier.csv --valide   # même chose, statut « valide » : le bandeau « brouillon » disparaît

Colonnes : cle ; francais ; dioula ; moore. Une cellule vide = pas de traduction : l'application affiche le français (jamais un texte vide).
Les textes à traduire sont ceux écrits t('cle', 'français') dans web/js, plus les titres d'écran et les statuts.
Fichier CSV : UTF-8 avec BOM et point-virgule, pour s'ouvrir correctement dans Excel.
"""
import argparse
import csv
import json
import re
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
JS = RACINE / "web" / "js"
DICO = RACINE / "web" / "data" / "i18n"
SORTIE = RACINE / "livrables" / "traductions_a_valider.csv"
LANGUES = {"dioula": "dyu", "moore": "mos"}
TEXTE = r"""(?:'((?:[^'\\]|\\.)*)'|"((?:[^"\\]|\\.)*)")"""
APPEL = re.compile(r"\bt\(\s*'([^']+)'\s*,\s*" + TEXTE)


def _decode(s):
    return re.sub(r"\\(.)", r"\1", s)


def textes_source():
    """{clé: français} d'après le code : appels t('clé', 'français'), titres d'écran (nav.*) et statuts (st.*)."""
    sortie = {}
    for f in sorted(JS.rglob("*.js")):
        for m in APPEL.finditer(f.read_text(encoding="utf-8")):
            sortie.setdefault(m.group(1), _decode(m.group(2) if m.group(2) is not None else m.group(3)))
    acces = (JS / "acces.js").read_text(encoding="utf-8")
    for m in re.finditer(r"^\s{2}(\w+): \{ fichier: '[^']*', titre: ['\"]((?:[^'\"\\]|\\.)*)['\"]", acces, re.M):
        sortie.setdefault("nav." + m.group(1), _decode(m.group(2)))
    util = (JS / "util.js").read_text(encoding="utf-8")
    for m in re.finditer(r"^\s{2}(\w+): \['([^']+)', '\w+'", util, re.M):
        sortie.setdefault("st." + m.group(1), m.group(2))
    return sortie


def lire_dico(code):
    p = DICO / f"{code}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def exporter():
    src = textes_source()
    d = {nom: lire_dico(code) for nom, code in LANGUES.items()}
    SORTIE.parent.mkdir(exist_ok=True)
    with SORTIE.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["cle", "francais", "dioula", "moore"])
        for cle in sorted(src):
            w.writerow([cle, src[cle]] + [d[nom].get(cle, "") for nom in LANGUES])
    rempli = {nom: sum(1 for c in src if d[nom].get(c)) for nom in LANGUES}
    print(f"{len(src)} textes exportés vers {SORTIE} ; déjà traduits : {rempli}")


def importer(fichier, valide):
    with open(fichier, encoding="utf-8-sig", newline="") as f:
        lignes = list(csv.DictReader(f, delimiter=";"))
    if not lignes or "cle" not in lignes[0]:
        sys.exit("CSV invalide : colonnes attendues cle ; francais ; dioula ; moore (séparateur point-virgule).")
    for nom, code in LANGUES.items():
        ancien = lire_dico(code)
        dico = {"_statut": "valide" if valide else "brouillon", "_note": ancien.get("_note", "")}
        n = 0
        for l in lignes:
            v = (l.get(nom) or "").strip()
            if v:
                dico[l["cle"].strip()] = v
                n += 1
        (DICO / f"{code}.json").write_text(json.dumps(dico, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"{code}.json : {n} textes, statut {dico['_statut']}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("action", choices=["exporter", "importer"])
    ap.add_argument("fichier", nargs="?")
    ap.add_argument("--valide", action="store_true")
    a = ap.parse_args()
    if a.action == "exporter":
        exporter()
    elif not a.fichier:
        sys.exit("Indiquez le fichier CSV à importer.")
    else:
        importer(a.fichier, a.valide)
