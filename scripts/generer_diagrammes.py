"""Diagrammes draw.io d'Orẽgdo, régénérés à partir du code : à relancer après chaque ajout.

    python scripts/generer_diagrammes.py

Écrit dans docs/modelisation/ (s'ouvre avec draw.io ou https://app.diagrams.net) :
- diagramme-classes.drawio     : TOUTES les classes Python d'oregdo/, lues dans le code (attributs, méthodes, héritage, utilisations)
- modele-donnees.drawio        : les tables SQLite lues dans oregdo/verification/schema.sql (colonnes, liens)
- architecture.drawio          : téléphone, serveur, modules, données, déploiement
- cas-utilisation.drawio       : ce que chaque acteur du sujet fait dans l'application
- sequence-signalement.drawio  : du signalement hors ligne à la tournée recalculée
Les deux premiers suivent le code automatiquement ; les trois autres sont décrits ci-dessous (listes faciles à modifier).
"""
import ast
import html
import re
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
SORTIE = RACINE / "docs" / "modelisation"
VERT, VERT_CLAIR, GRIS = "#1e7a46", "#e8f5ec", "#f4f6f4"


class Diagramme:
    """Construit un fichier draw.io (mxGraphModel) cellule par cellule."""

    def __init__(self, nom):
        self.nom, self.cellules, self.n = nom, [], 2

    def _id(self):
        self.n += 1
        return f"c{self.n}"

    def boite(self, x, y, l, h, texte, style=""):
        i = self._id()
        base = "rounded=1;whiteSpace=wrap;html=1;arcSize=6;"
        self.cellules.append(f'<mxCell id="{i}" value="{html.escape(texte)}" style="{base}{style}" vertex="1" parent="1">'
                             f'<mxGeometry x="{x}" y="{y}" width="{l}" height="{h}" as="geometry"/></mxCell>')
        return i

    def lien(self, a, b, texte="", style=""):
        i = self._id()
        self.cellules.append(f'<mxCell id="{i}" value="{html.escape(texte)}" style="edgeStyle=orthogonalEdgeStyle;rounded=1;html=1;{style}" edge="1" parent="1" source="{a}" target="{b}">'
                             '<mxGeometry relative="1" as="geometry"/></mxCell>')
        return i

    def ecrire(self, fichier):
        corps = "".join(self.cellules)
        xml = (f'<mxfile host="Orẽgdo" type="device"><diagram id="{fichier.stem}" name="{html.escape(self.nom)}">'
               '<mxGraphModel dx="1600" dy="900" grid="1" gridSize="10" guides="1" tooltips="1" connect="1" arrows="1" fold="1" page="1" pageScale="1" pageWidth="1654" pageHeight="1169" math="0" shadow="0">'
               f'<root><mxCell id="0"/><mxCell id="1" parent="0"/>{corps}</root></mxGraphModel></diagram></mxfile>')
        fichier.write_text(xml, encoding="utf-8")
        return fichier


# ------------------------------------------------------------------ diagramme de classes (lu dans le code)
def lire_classes():
    classes = []
    for f in sorted((RACINE / "oregdo").rglob("*.py")):
        source = f.read_text(encoding="utf-8")
        module = ".".join(f.relative_to(RACINE).with_suffix("").parts)
        for n in ast.parse(source).body:
            if not isinstance(n, ast.ClassDef):
                continue
            attributs, methodes = [], []
            for b in n.body:
                if isinstance(b, ast.AnnAssign) and isinstance(b.target, ast.Name):
                    attributs.append(f"{b.target.id} : {ast.unparse(b.annotation)}")
                elif isinstance(b, ast.FunctionDef):
                    if b.name == "__init__":
                        for s in ast.walk(b):
                            if isinstance(s, (ast.Assign, ast.AnnAssign)):
                                for c in (s.targets if isinstance(s, ast.Assign) else [s.target]):
                                    for e in ast.walk(c):
                                        if isinstance(e, ast.Attribute) and isinstance(e.value, ast.Name) and e.value.id == "self" and not e.attr.startswith("_"):
                                            if e.attr not in attributs:
                                                attributs.append(e.attr)
                    elif not b.name.startswith("_"):
                        args = [a.arg for a in b.args.args if a.arg not in ("self", "cls")]
                        methodes.append(f"{b.name}({', '.join(args[:3])}{', …' if len(args) > 3 else ''})")
            classes.append({"nom": n.name, "module": module, "bases": [ast.unparse(b) for b in n.bases],
                            "attributs": list(dict.fromkeys(attributs)), "methodes": methodes, "source": ast.get_source_segment(source, n) or ""})
    return classes


def diagramme_classes():
    d = Diagramme("Diagramme de classes (généré depuis le code)")
    classes = lire_classes()
    paquets = {}
    for c in classes:
        paquets.setdefault(c["module"].rsplit(".", 1)[0], []).append(c)
    ids, y = {}, 40
    d.boite(40, 0, 900, 30, "Orẽgdo : classes Python (oregdo/). Généré par scripts/generer_diagrammes.py, ne pas modifier à la main.",
            "strokeColor=none;fillColor=none;fontStyle=1;fontSize=14;align=left;")
    for paquet, liste in paquets.items():
        hauteur_max = 0
        d.boite(40, y, 1560, 24, f"paquet {paquet}", f"fillColor={VERT};fontColor=#ffffff;strokeColor={VERT};fontStyle=1;align=left;spacingLeft=8;")
        y += 34
        x = 40
        for c in liste:
            attrs = c["attributs"][:9] + (["…"] if len(c["attributs"]) > 9 else [])
            meths = c["methodes"][:8] + (["…"] if len(c["methodes"]) > 8 else [])
            externes = [b for b in c["bases"] if b not in {k["nom"] for k in classes}]
            entete = f"<b>{html.escape(c['nom'])}</b>" + (f"<br><i>« {html.escape(', '.join(externes))} »</i>" if externes else "")
            corps = "<br>".join(html.escape(a) for a in attrs) or "&nbsp;"
            ops = "<br>".join(html.escape(m) for m in meths) or "&nbsp;"
            texte = f"<div style='text-align:center'>{entete}</div><hr>{corps}<hr>{ops}"
            h = 60 + 15 * (max(1, len(attrs)) + max(1, len(meths)))
            if x + 250 > 1600:
                x, y = 40, y + hauteur_max + 30
                hauteur_max = 0
            ids[c["nom"]] = d.boite(x, y, 240, h, texte, f"fillColor={VERT_CLAIR};strokeColor={VERT};align=left;verticalAlign=top;spacingLeft=6;fontSize=11;arcSize=2;")
            x += 260
            hauteur_max = max(hauteur_max, h)
        y += hauteur_max + 50
    noms = set(ids)
    for c in classes:
        for b in c["bases"]:
            if b in noms:
                d.lien(ids[c["nom"]], ids[b], "", "endArrow=block;endFill=0;")
        corps = c["source"].split("\n", 1)[-1]
        for autre in sorted(noms - {c["nom"]}):
            if re.search(rf"\b{re.escape(autre)}\b", corps) and autre not in c["bases"]:
                d.lien(ids[c["nom"]], ids[autre], "utilise", "dashed=1;endArrow=open;fontSize=9;strokeColor=#7a8a80;")
    return d


# ------------------------------------------------------------------ modèle de données (lu dans schema.sql)
def diagramme_donnees():
    d = Diagramme("Modèle de données SQLite (généré depuis schema.sql)")
    sql = (RACINE / "oregdo" / "verification" / "schema.sql").read_text(encoding="utf-8")
    tables = {}
    for m in re.finditer(r"CREATE TABLE IF NOT EXISTS (\w+)\s*\((.*?)\n\);", sql, re.S):
        cols = []
        for ligne in m.group(2).split("\n"):
            ligne = ligne.split("--")[0].strip().rstrip(",")
            if ligne and not ligne.upper().startswith(("PRIMARY KEY", "FOREIGN KEY", "UNIQUE", "CHECK", "CONSTRAINT")):
                nom, *reste = ligne.split()
                cols.append((nom, " ".join(reste)))
        tables[m.group(1)] = cols
    d.boite(40, 0, 900, 30, "Orẽgdo : tables SQLite (oregdo/verification/schema.sql). Généré par scripts/generer_diagrammes.py.",
            "strokeColor=none;fillColor=none;fontStyle=1;fontSize=14;align=left;")
    ids, x, y, hmax = {}, 40, 50, 0
    for t, cols in tables.items():
        lignes = "<br>".join(f"{'<u>' if 'PRIMARY KEY' in typ.upper() else ''}{html.escape(c)}{'</u>' if 'PRIMARY KEY' in typ.upper() else ''} <i>{html.escape(typ.split()[0] if typ else '')}</i>" for c, typ in cols[:22])
        h = 40 + 15 * min(len(cols), 23)
        if x + 270 > 1600:
            x, y, hmax = 40, y + hmax + 40, 0
        ids[t] = d.boite(x, y, 250, h, f"<div style='text-align:center'><b>{t}</b></div><hr>{lignes}",
                         f"fillColor={GRIS};strokeColor={VERT};align=left;verticalAlign=top;spacingLeft=6;fontSize=11;arcSize=2;")
        x, hmax = x + 280, max(hmax, h)
    for t, cols in tables.items():                      # liens : REFERENCES explicites, puis colonnes « <table>_id »
        for c, typ in cols:
            m = re.search(r"REFERENCES (\w+)", typ)
            cible = m.group(1) if m else (c[:-3] if c.endswith("_id") and c[:-3] in tables else None)
            if cible and cible in ids and cible != t:
                d.lien(ids[t], ids[cible], c, "endArrow=ERmandOne;startArrow=ERmany;fontSize=9;")
    return d


# ------------------------------------------------------------------ architecture (décrite ici)
def diagramme_architecture():
    d = Diagramme("Architecture d'Orẽgdo")

    def b(x, y, l, h, t, c=VERT_CLAIR):
        return d.boite(x, y, l, h, t, f"fillColor={c};strokeColor={VERT};fontSize=12;")
    tel = b(40, 60, 300, 160, "<b>Téléphone : application web installable (PWA)</b><br>web/ : écrans par rôle (MapLibre)<br>Service worker : fonctionne sans réseau<br>IndexedDB : file d'attente des signalements<br>Masquage des visages et plaques sur le téléphone")
    nav = b(40, 260, 300, 90, "<b>Ordinateur de la mairie</b><br>même application, écrans larges<br>(tableau de bord, plan, simulation, jury)")
    api = b(440, 60, 340, 290, "<b>Serveur FastAPI</b> (oregdo/app.py)<br><br>api/signalements.py : dépôt, import, revalidation<br>api/portails.py : comptes, brigade, pré-collecteur, mairie<br>api/plan.py : plan, scénario, aléas, simulation<br>api/notifications.py<br><br>securite.py : jetons signés, rôles, limitation de débit<br>comptes.py : comptes, mots de passe (scrypt)", "#ffffff")
    ver = b(880, 40, 330, 110, "<b>Vérification</b> (oregdo/verification)<br>8 contrôles, score 0-100, doublons → dépotoirs,<br>import CSV / Kobo / WKT / GeoJSON,<br>collecte simulée, jeux synthétiques")
    pla = b(880, 170, 330, 110, "<b>Planification</b> (oregdo/planning)<br>p-médiane (HiGHS) : points de regroupement<br>tournées (PyVRP) sur le réseau OSM<br>aléas : panne, pluie, quartier, pièges")
    sim = b(880, 300, 330, 90, "<b>Simulation multi-agents</b> (oregdo/simulation, Mesa)<br>ménages, pré-collecteurs, brigade Laabal, mairie")
    bdd = b(1300, 40, 300, 110, "<b>SQLite</b> data/oregdo.db<br>signalements, dépotoirs, comptes,<br>interventions, collectes, journal d'audit", GRIS)
    pack = b(1300, 170, 300, 130, "<b>Pack commune</b> packs/ouaga/<br>commune_config.yaml (paramètres [S]/[H])<br>couches GeoJSON, graphe routier,<br>population (Open Buildings)", GRIS)
    src = b(1300, 330, 300, 80, "<b>Données ouvertes</b><br>OpenStreetMap, Google Open Buildings,<br>RGPH 2019", GRIS)
    dep = b(440, 400, 340, 80, "<b>Déploiement en une commande</b><br>docker compose up --build<br>ou scripts\\deployer.ps1 (Windows)", "#fff3c4")
    osm = b(880, 420, 330, 60, "<b>Bien commun</b> : export OpenStreetMap (.osm, GeoJSON ODbL)", "#fff3c4")
    d.lien(tel, api, "HTTPS /api (JSON), synchronisation", "endArrow=block;")
    d.lien(nav, api, "HTTPS /api", "endArrow=block;")
    for m in (ver, pla, sim):
        d.lien(api, m, "", "endArrow=block;")
    d.lien(ver, bdd, "", "endArrow=block;")
    d.lien(pla, pack, "", "endArrow=block;")
    d.lien(sim, pack, "", "endArrow=block;")
    d.lien(pla, bdd, "dépotoirs vérifiés", "endArrow=block;dashed=1;")
    d.lien(src, pack, "scripts/build_*.py", "endArrow=block;dashed=1;")
    d.lien(api, osm, "", "endArrow=block;dashed=1;")
    d.lien(dep, api, "", "endArrow=block;dashed=1;")
    return d


# ------------------------------------------------------------------ cas d'utilisation (décrits ici)
CAS = {
    "Ménage (citoyen, sans compte)": ["Signaler un tas (photo ou message vocal), même sans réseau", "Suivre son signalement avec un code",
                                      "Voir la carte des dépotoirs vérifiés", "Gagner des points et des badges", "Lire ses droits et devoirs", "Installer l'application"],
    "Pré-collecteur": ["Saisir ses collectes (kg, ménages servis)", "Voir les passages de camion à son point"],
    "Brigade Laabal": ["Vérifier un signalement « à confirmer »", "Enregistrer une sensibilisation puis une sanction", "Importer une collecte de terrain"],
    "Mairie": ["Consulter le tableau de bord", "Voir le plan de gestion d'un arrondissement", "Modifier les paramètres et comparer des scénarios",
               "Simuler 90 jours (multi-agents)", "Exporter vers OpenStreetMap", "Importer un fichier (jeu de test du jury)"],
    "Jury / administration": ["Injecter des signalements piégés", "Mettre des camions en panne, saison des pluies, nouveau quartier", "Gérer les comptes"],
}


def diagramme_cas():
    d = Diagramme("Cas d'utilisation par acteur")
    y = 40
    d.boite(360, 20, 620, 40 + 52 * sum(len(v) for v in CAS.values()) + 10 * len(CAS), "", "fillColor=none;strokeColor=#9aa;dashed=1;")
    d.boite(370, 24, 300, 24, "Application Orẽgdo", "strokeColor=none;fillColor=none;fontStyle=1;align=left;")
    for acteur, cas in CAS.items():
        a = d.boite(120, y + 26 * (len(cas) - 1), 40, 60, acteur, f"shape=umlActor;verticalLabelPosition=bottom;verticalAlign=top;fillColor=#ffffff;strokeColor={VERT};")
        for c in cas:
            e = d.boite(420, y, 520, 40, c, f"ellipse;fillColor={VERT_CLAIR};strokeColor={VERT};fontSize=11;")
            d.lien(a, e, "", "endArrow=none;")
            y += 52
        y += 10
    return d


# ------------------------------------------------------------------ séquence (décrite ici)
ETAPES = [("Ménage", "Téléphone (PWA)", "Signaler : photo masquée sur place, position GPS affinée"),
          ("Téléphone (PWA)", "Téléphone (PWA)", "Enregistrement immédiat dans la file (IndexedDB), clé unique"),
          ("Téléphone (PWA)", "Serveur", "POST /api/signalements dès que le réseau revient (sans doublon)"),
          ("Serveur", "Vérification", "8 contrôles + précision GPS → vérifié / à confirmer / rejeté"),
          ("Vérification", "SQLite", "Signalement et motifs ; regroupement en dépotoir"),
          ("Serveur", "Téléphone (PWA)", "Code de suivi (et statut)"),
          ("Brigade", "Serveur", "Revalider un « à confirmer » après visite"),
          ("Mairie / jury", "Serveur", "Aléa : panne, pluie, nouveau quartier, pièges"),
          ("Serveur", "Planification", "Recalcul : points de regroupement, tournées (quelques secondes)"),
          ("Planification", "Mairie / jury", "Plan avant / après, feuilles de route par camion")]


def diagramme_sequence():
    d = Diagramme("Séquence : du signalement à la tournée")
    acteurs = list(dict.fromkeys([a for a, _, _ in ETAPES] + [b for _, b, _ in ETAPES]))
    x0, pas, haut = 40, 190, 80 + 60 * len(ETAPES)
    col = {}
    for i, a in enumerate(acteurs):
        x = x0 + i * pas
        d.boite(x, 20, 160, 40, f"<b>{a}</b>", f"fillColor={VERT_CLAIR};strokeColor={VERT};")
        col[a] = x + 80
        d.boite(x + 79, 60, 2, haut, "", "fillColor=#9aa;strokeColor=none;rounded=0;")
    for k, (a, b, texte) in enumerate(ETAPES):
        y = 90 + 60 * k
        xa, xb = col[a], col[b]
        if a == b:
            d.boite(xa + 6, y - 6, 300, 34, f"{k + 1}. {texte}", f"fillColor=#ffffff;strokeColor={VERT};fontSize=10;align=left;spacingLeft=4;")
        else:
            gauche, l = min(xa, xb), abs(xb - xa)
            d.boite(gauche, y, l, 2, "", f"fillColor={VERT};strokeColor=none;rounded=0;")
            d.boite(gauche + 4, y - 28, max(l - 8, 160), 26, f"{k + 1}. {texte} {'→' if xb > xa else '←'}", "fillColor=none;strokeColor=none;fontSize=10;align=center;")
    return d


def main():
    SORTIE.mkdir(parents=True, exist_ok=True)
    for nom, fabrique in (("diagramme-classes", diagramme_classes), ("modele-donnees", diagramme_donnees), ("architecture", diagramme_architecture),
                          ("cas-utilisation", diagramme_cas), ("sequence-signalement", diagramme_sequence)):
        f = fabrique().ecrire(SORTIE / f"{nom}.drawio")
        print(f"{f.relative_to(RACINE)}  ({f.stat().st_size // 1024} Ko)")


if __name__ == "__main__":
    main()
