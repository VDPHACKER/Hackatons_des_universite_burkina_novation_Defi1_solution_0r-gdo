"""Comptes utilisateurs : création, connexion, verrouillage, changement de mot de passe, ligne de commande.

Le plus simple (démonstration, essais en équipe) : un compte par rôle, mots de passe affichés et notés dans comptes_demo.txt
    python -m oregdo.comptes demo                       (mots de passe lisibles tirés au hasard)
    python -m oregdo.comptes demo --mdp "un-mot-commun"  (le même mot de passe pour tous les comptes de démonstration)
    Sous Windows : double-cliquer scripts\\comptes.bat
Mot de passe perdu ou compte bloqué :
    python -m oregdo.comptes reinitialiser --id admin   (nouveau mot de passe affiché, compte débloqué et réactivé)
Premier administrateur :
    python -m oregdo.comptes creer-admin                (demande l'identifiant et le mot de passe)
    ou variables d'environnement OREGDO_ADMIN_ID et OREGDO_ADMIN_MDP (créé au démarrage du serveur si absent)
Autres comptes :
    python -m oregdo.comptes creer --id awa --nom "Awa Ouédraogo" --role brigade --zone "Secteur 12"
    python -m oregdo.comptes lister | desactiver --id awa | mot-de-passe --id awa
"""
import argparse
import getpass
import os
import re
import secrets
import sys
from datetime import datetime, timedelta, timezone

from . import securite
from .config import RACINE, charger_config
from .verification import base

ID_VALIDE = re.compile(r"^[A-Za-z0-9._-]{3,40}$")
# Mots courts, sans lettres ambiguës à recopier depuis un écran (l/I/1, O/0) : « kaya-vert-soleil-47 » se lit et se tape sans erreur.
MOTS = ("kaya", "vert", "soleil", "pluie", "baobab", "karite", "mangue", "riz", "fleuve", "colline", "sable", "tamis", "pagne", "tam-tam",
        "nere", "zama", "pagre", "naaba", "toit", "piste", "marche", "case", "jardin", "arbre", "savane", "brise", "harmattan", "mil",
        "sorgho", "zebu", "pirogue", "puits", "grenier", "tisserand", "potier", "forge", "kora", "balafon", "djembe", "cauri")
FICHIER_DEMO = RACINE / "comptes_demo.txt"            # hors du dépôt (.gitignore) : à ne pas partager hors de l'équipe
COMPTES_DEMO = (("admin", "Administration", "admin"), ("mairie", "Mairie (démonstration)", "mairie"),
                ("brigade", "Agent de la brigade (démonstration)", "brigade"), ("precollecteur", "Pré-collecteur (démonstration)", "precollecteur"))


def mot_de_passe_lisible() -> str:
    """Trois mots en minuscules et deux chiffres sans 0 ni 1 (pas de confusion avec O, l ou I) : ≈ 22 bits ;
    le verrouillage après 5 échecs empêche l'essai en masse, et le hachage scrypt protège la base."""
    return "-".join(secrets.choice(MOTS) for _ in range(3)) + "-" + "".join(secrets.choice("23456789") for _ in range(2))


def reinitialiser(conn, identifiant, mot_de_passe=None) -> str:
    """Nouveau mot de passe (lisible si aucun n'est donné), compte débloqué et réactivé. Renvoie le mot de passe."""
    mdp = mot_de_passe or mot_de_passe_lisible()
    modifier_utilisateur(conn, _identifiant_existant(conn, identifiant), mot_de_passe=mdp, actif=True)
    return mdp


def comptes_demo(conn, mot_de_passe=None) -> list[tuple[str, str, str]]:
    """Crée ou remet à zéro un compte par rôle. Renvoie [(identifiant, rôle, mot de passe)]."""
    sortie = []
    for ident, nom, role in COMPTES_DEMO:
        mdp = mot_de_passe or mot_de_passe_lisible()
        if conn.execute("SELECT 1 FROM utilisateur WHERE identifiant=? COLLATE NOCASE", (ident,)).fetchone():
            reinitialiser(conn, ident, mdp)
            modifier_utilisateur(conn, _identifiant_existant(conn, ident), role=role)
        else:
            creer_utilisateur(conn, ident, nom, role, mdp)
        securite.auditer(conn, "systeme", "compte_demo", ident)
        sortie.append((ident, role, mdp))
    return sortie


def _identifiant_existant(conn, identifiant) -> str:
    """Identifiant tel qu'il est enregistré, retrouvé sans tenir compte des majuscules (« Admin » tapé sur un téléphone = « admin »)."""
    r = conn.execute("SELECT identifiant FROM utilisateur WHERE identifiant=? COLLATE NOCASE", (str(identifiant or "").strip()[:60],)).fetchone()
    if r is None:
        raise ErreurCompte(f"Utilisateur « {identifiant} » introuvable.", 404)
    return r["identifiant"]


class ErreurCompte(Exception):
    """Erreur lisible (message en français) : conflit = 409, introuvable = 404, sinon 422."""

    def __init__(self, message, code=422):
        super().__init__(message)
        self.code = code


def _public(row) -> dict:
    d = {k: row[k] for k in ("identifiant", "nom", "role", "zone", "point", "cree_le", "derniere_connexion")}
    d["actif"] = bool(row["actif"])
    return d


def creer_utilisateur(conn, identifiant, nom, role, mot_de_passe, zone=None, point=None) -> dict:
    identifiant = (identifiant or "").strip()
    if not ID_VALIDE.match(identifiant):
        raise ErreurCompte("Identifiant invalide : 3 à 40 caractères parmi lettres, chiffres, point, tiret et tiret bas.")
    if role not in securite.ROLES:
        raise ErreurCompte(f"Rôle inconnu « {role} » : choisir parmi {', '.join(securite.ROLES)}.")
    if not (nom or "").strip() or len(nom) > 120:
        raise ErreurCompte("Le nom est obligatoire (120 caractères maximum).")
    try:
        securite.valider_mot_de_passe(mot_de_passe)
    except ValueError as e:
        raise ErreurCompte(str(e))
    if conn.execute("SELECT 1 FROM utilisateur WHERE identifiant=? COLLATE NOCASE", (identifiant,)).fetchone():
        raise ErreurCompte(f"L'identifiant « {identifiant} » existe déjà.", 409)
    conn.execute("INSERT INTO utilisateur (identifiant, nom, role, zone, point, mot_de_passe, cree_le) VALUES (?,?,?,?,?,?,?)",
                 (identifiant, nom.strip(), role, (zone or None), (point or None), securite.hacher_mot_de_passe(mot_de_passe), base.maintenant()))
    conn.commit()
    return lire_utilisateur(conn, identifiant)


def lire_utilisateur(conn, identifiant) -> dict:
    row = conn.execute("SELECT * FROM utilisateur WHERE identifiant=?", (identifiant,)).fetchone()
    if row is None:
        raise ErreurCompte(f"Utilisateur « {identifiant} » introuvable.", 404)
    return _public(row)


def lister_utilisateurs(conn) -> list[dict]:
    return [_public(r) for r in conn.execute("SELECT * FROM utilisateur ORDER BY identifiant")]


def modifier_utilisateur(conn, identifiant, **champs) -> dict:
    lire_utilisateur(conn, identifiant)
    sets, args = [], []
    for k in ("nom", "role", "zone", "point"):
        if champs.get(k) is not None:
            if k == "role" and champs[k] not in securite.ROLES:
                raise ErreurCompte(f"Rôle inconnu « {champs[k]} » : choisir parmi {', '.join(securite.ROLES)}.")
            sets.append(f"{k}=?"); args.append(champs[k])
    if champs.get("actif") is not None:
        sets.append("actif=?"); args.append(int(bool(champs["actif"])))
    if champs.get("mot_de_passe") is not None:
        try:
            securite.valider_mot_de_passe(champs["mot_de_passe"])
        except ValueError as e:
            raise ErreurCompte(str(e))
        sets += ["mot_de_passe=?", "echecs=0", "verrouille_jusqua=NULL"]; args.append(securite.hacher_mot_de_passe(champs["mot_de_passe"]))
    if sets:
        conn.execute(f"UPDATE utilisateur SET {', '.join(sets)} WHERE identifiant=?", (*args, identifiant))
        if champs.get("actif") is False or champs.get("role") is not None or champs.get("mot_de_passe") is not None:
            conn.execute("UPDATE session SET revoque=1 WHERE utilisateur=?", (identifiant,))   # les jetons en cours ne valent plus
        conn.commit()
    return lire_utilisateur(conn, identifiant)


def connecter(conn, identifiant, mot_de_passe, maintenant=None) -> dict:
    """Vérifie les identifiants. Renvoie {jeton, expire_le, utilisateur}. Lève ErreurCompte 401/403/423."""
    maintenant = maintenant or datetime.now(timezone.utc)
    cfg = charger_config().securite.verrouillage
    # Sans tenir compte des majuscules ni des espaces autour : le clavier d'un téléphone écrit souvent « Admin » ou « admin ».
    u = conn.execute("SELECT * FROM utilisateur WHERE identifiant=? COLLATE NOCASE", (str(identifiant or "").strip()[:60],)).fetchone()
    if u is not None and u["verrouille_jusqua"]:
        fin = datetime.fromisoformat(u["verrouille_jusqua"])
        if fin > maintenant:
            e = ErreurCompte(f"Compte verrouillé après des échecs répétés : réessayez dans {int((fin - maintenant).total_seconds()) // 60 + 1} minute(s).", 423)
            e.reessayer_dans_s = int((fin - maintenant).total_seconds()) + 1
            raise e
    mdp = str(mot_de_passe or "")
    ok = securite.verifier_mot_de_passe(mdp, u["mot_de_passe"] if u else None)
    if not ok and u is not None:
        # Clavier de téléphone : espace ajoutée, tiret transformé en tiret long (– —), espace insécable, guillemets copiés.
        corrige = re.sub(r"[‐-―−]", "-", mdp.replace(" ", " ")).strip().strip("\"'«»“”")
        if corrige != mdp:
            ok = securite.verifier_mot_de_passe(corrige, u["mot_de_passe"])
    if not ok:
        if u is not None:
            echecs = u["echecs"] + 1
            verrou = (maintenant + timedelta(minutes=cfg.duree_minutes)).isoformat() if echecs >= cfg.echecs_max else None
            conn.execute("UPDATE utilisateur SET echecs=?, verrouille_jusqua=? WHERE identifiant=?",
                         (0 if verrou else echecs, verrou, u["identifiant"]))
            conn.commit()
            securite.auditer(conn, u["identifiant"], "connexion_echec", u["identifiant"], "verrouillé" if verrou else f"échec {echecs}")
        raise ErreurCompte("Identifiant ou mot de passe incorrect.", 401)
    if not u["actif"]:
        raise ErreurCompte("Ce compte est désactivé : contactez l'administrateur.", 403)
    conn.execute("UPDATE utilisateur SET echecs=0, verrouille_jusqua=NULL, derniere_connexion=? WHERE identifiant=?",
                 (maintenant.isoformat(), u["identifiant"]))
    jeton, expire = securite.creer_jeton(conn, u["identifiant"], u["role"], maintenant)
    securite.auditer(conn, {"identifiant": u["identifiant"], "role": u["role"]}, "connexion")
    return {"jeton": jeton, "type": "Bearer", "expire_le": expire, "utilisateur": lire_utilisateur(conn, u["identifiant"])}


def changer_mot_de_passe(conn, identifiant, ancien, nouveau):
    u = conn.execute("SELECT * FROM utilisateur WHERE identifiant=?", (identifiant,)).fetchone()
    if u is None or not securite.verifier_mot_de_passe(ancien or "", u["mot_de_passe"]):
        raise ErreurCompte("Ancien mot de passe incorrect.", 401)
    try:
        securite.valider_mot_de_passe(nouveau)
    except ValueError as e:
        raise ErreurCompte(str(e))
    conn.execute("UPDATE utilisateur SET mot_de_passe=? WHERE identifiant=?", (securite.hacher_mot_de_passe(nouveau), identifiant))
    conn.commit()
    securite.auditer(conn, {"identifiant": identifiant, "role": u["role"]}, "mot_de_passe_change")


def amorcer_admin_depuis_env(conn=None) -> bool:
    """Crée le premier administrateur depuis OREGDO_ADMIN_ID / OREGDO_ADMIN_MDP s'il n'existe pas encore."""
    ident, mdp = os.environ.get("OREGDO_ADMIN_ID"), os.environ.get("OREGDO_ADMIN_MDP")
    if not ident or not mdp:
        return False
    propre = conn is None
    conn = conn or base.ouvrir()
    try:
        if conn.execute("SELECT 1 FROM utilisateur WHERE identifiant=?", (ident,)).fetchone():
            return False
        creer_utilisateur(conn, ident, "Administrateur", "admin", mdp)
        securite.auditer(conn, "systeme", "admin_cree_depuis_env", ident)
        return True
    finally:
        if propre:
            conn.close()


def _saisir(valeur, invite, secret=False):
    if valeur:
        return valeur
    return getpass.getpass(invite) if secret else input(invite)


def main(argv=None):
    p = argparse.ArgumentParser(prog="python -m oregdo.comptes", description="Gestion des comptes Orẽgdo")
    sp = p.add_subparsers(dest="cmd", required=True)
    a = sp.add_parser("creer-admin", help="crée un administrateur")
    a.add_argument("--id", default=os.environ.get("OREGDO_ADMIN_ID")); a.add_argument("--nom", default="Administrateur")
    a.add_argument("--mdp", default=os.environ.get("OREGDO_ADMIN_MDP"))
    c = sp.add_parser("creer", help="crée un compte")
    c.add_argument("--id", required=True); c.add_argument("--nom", required=True); c.add_argument("--role", required=True, choices=securite.ROLES)
    c.add_argument("--zone"); c.add_argument("--point"); c.add_argument("--mdp")
    sp.add_parser("lister")
    d = sp.add_parser("desactiver"); d.add_argument("--id", required=True)
    m = sp.add_parser("mot-de-passe"); m.add_argument("--id", required=True); m.add_argument("--mdp")
    dm = sp.add_parser("demo", help="crée ou remet à zéro un compte par rôle (admin, mairie, brigade, precollecteur)")
    dm.add_argument("--mdp", help="même mot de passe pour tous (8 caractères minimum) ; sinon un mot de passe lisible par compte")
    r = sp.add_parser("reinitialiser", help="nouveau mot de passe, compte débloqué et réactivé")
    r.add_argument("--id", required=True); r.add_argument("--mdp")
    args = p.parse_args(argv)
    conn = base.ouvrir()
    try:
        if args.cmd == "demo":
            lignes = comptes_demo(conn, args.mdp)
            texte = ("Comptes de DÉMONSTRATION Orẽgdo (ne pas partager hors de l'équipe)\n"
                     f"Créés le {base.maintenant()} pour la base {base.chemin_base()}\n\n"
                     + "\n".join(f"  {i:15} {r_:14} {m_}" for i, r_, m_ in lignes)
                     + "\n\nIdentifiant à gauche, mot de passe à droite. Majuscules indifférentes pour l'identifiant.\n"
                     "Pour recommencer : python -m oregdo.comptes demo   (ou double-cliquer scripts\\comptes.bat)\n")
            print(texte)                                   # d'abord à l'écran : les comptes existent déjà, le mot de passe ne doit jamais être perdu
            for fichier in (FICHIER_DEMO, RACINE / "data" / "comptes_demo.txt"):   # le dossier de l'application peut être en lecture seule (Docker)
                try:
                    fichier.write_text(texte, encoding="utf-8")
                    print(f"(Aussi noté dans {fichier})")
                    break
                except OSError:
                    continue
            else:
                print("(Fichier non écrit : notez les mots de passe ci-dessus.)")
        elif args.cmd == "reinitialiser":
            mdp = reinitialiser(conn, args.id, args.mdp)
            print(f"Compte « {_identifiant_existant(conn, args.id)} » débloqué. Nouveau mot de passe : {mdp}")
        elif args.cmd == "creer-admin":
            u = creer_utilisateur(conn, _saisir(args.id, "Identifiant de l'administrateur : "), args.nom, "admin", _saisir(args.mdp, "Mot de passe (8 caractères minimum) : ", True))
            print(f"Administrateur « {u['identifiant']} » créé.")
        elif args.cmd == "creer":
            u = creer_utilisateur(conn, args.id, args.nom, args.role, _saisir(args.mdp, "Mot de passe (8 caractères minimum) : ", True), args.zone, args.point)
            print(f"Compte « {u['identifiant']} » ({u['role']}) créé.")
        elif args.cmd == "lister":
            for u in lister_utilisateurs(conn):
                print(f"{u['identifiant']:20} {u['role']:14} {'actif' if u['actif'] else 'INACTIF':8} {u['nom']}")
        elif args.cmd == "desactiver":
            modifier_utilisateur(conn, args.id, actif=False); print(f"Compte « {args.id} » désactivé.")
        elif args.cmd == "mot-de-passe":
            modifier_utilisateur(conn, args.id, mot_de_passe=_saisir(args.mdp, "Nouveau mot de passe : ", True)); print("Mot de passe modifié.")
    except ErreurCompte as e:
        print(f"Erreur : {e}", file=sys.stderr)
        return 1
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
