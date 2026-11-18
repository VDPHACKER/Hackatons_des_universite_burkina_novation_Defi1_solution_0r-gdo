"""Authentification et autorisation : comptes en base, jetons signés HMAC-SHA256, rôles, audit, limitation de débit.

- Mots de passe : `hashlib.scrypt` avec sel aléatoire, comparaison à temps constant.
- Jeton : `charge.signature` (JSON en base64url + HMAC-SHA256), expire après `securite.duree_jeton_heures` (12 h),
  révocable (table `session`). Envoyé dans l'en-tête `Authorization: Bearer <jeton>`.
- Clé de signature : variable d'environnement OREGDO_SECRET ; sinon générée au hasard et conservée dans
  `data/secret.key` (hors dépôt : à ne jamais versionner). Aucun secret n'est écrit dans la configuration.
- Rôles : precollecteur, brigade, mairie, admin (admin peut tout). Les citoyens n'ont pas de compte.
- Test uniquement : OREGDO_AUTH=0 désactive le contrôle, mais SEULEMENT sous pytest (variable PYTEST_CURRENT_TEST).
"""
import base64
import hashlib
import hmac
import json
import os
import secrets
import threading
import time
from datetime import datetime, timedelta, timezone

from fastapi import Depends, Header, HTTPException, Request

from .config import RACINE, charger_config
from .verification import base

ROLES = ("precollecteur", "brigade", "mairie", "admin")      # les acteurs du sujet ; le citoyen signale sans compte
MDP_MIN = 8
_N, _R, _P = 2**14, 8, 1
_FAUX_HASH = None


# ------------------------------------------------------------------ mots de passe
def _scrypt(mdp: str, sel: bytes, n=_N, r=_R, p=_P) -> bytes:
    return hashlib.scrypt(mdp.encode("utf-8"), salt=sel, n=n, r=r, p=p, dklen=32, maxmem=64 * 1024 * 1024)


def hacher_mot_de_passe(mdp: str) -> str:
    sel = secrets.token_bytes(16)
    return "scrypt${}${}${}${}${}".format(_N, _R, _P, base64.b64encode(sel).decode(), base64.b64encode(_scrypt(mdp, sel)).decode())


def verifier_mot_de_passe(mdp: str, enregistre: str | None) -> bool:
    """Comparaison à temps constant. Un identifiant inconnu (enregistre=None) coûte le même temps de calcul."""
    global _FAUX_HASH
    if not enregistre:
        _FAUX_HASH = _FAUX_HASH or hacher_mot_de_passe("faux-mot-de-passe")
        enregistre, ok_possible = _FAUX_HASH, False
    else:
        ok_possible = True
    try:
        _, n, r, p, sel, h = enregistre.split("$")
        calcule = _scrypt(mdp, base64.b64decode(sel), int(n), int(r), int(p))
        return hmac.compare_digest(calcule, base64.b64decode(h)) and ok_possible
    except (ValueError, TypeError):
        return False


def valider_mot_de_passe(mdp) -> str:
    if not isinstance(mdp, str) or len(mdp) < MDP_MIN:
        raise ValueError(f"Le mot de passe doit contenir au moins {MDP_MIN} caractères.")
    if len(mdp) > 200:
        raise ValueError("Le mot de passe est trop long (200 caractères maximum).")
    return mdp


# ------------------------------------------------------------------ clé de signature
_cle_cache: dict = {}


def source_secret() -> str:
    return "variable d'environnement OREGDO_SECRET" if os.environ.get("OREGDO_SECRET") else "fichier data/secret.key (généré)"


def cle_signature() -> bytes:
    env = os.environ.get("OREGDO_SECRET")
    if env:
        return env.encode("utf-8")
    fichier = RACINE / "data" / "secret.key"
    if "k" not in _cle_cache or not fichier.exists():
        if not fichier.exists():
            fichier.parent.mkdir(parents=True, exist_ok=True)
            fichier.write_text(secrets.token_urlsafe(48), encoding="utf-8")
            try:
                os.chmod(fichier, 0o600)
            except OSError:
                pass
        _cle_cache["k"] = fichier.read_text(encoding="utf-8").strip().encode("utf-8")
    return _cle_cache["k"]


# ------------------------------------------------------------------ jetons
def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def duree_jeton() -> timedelta:
    return timedelta(hours=getattr(getattr(charger_config(), "securite", None), "duree_jeton_heures", 12))


def creer_jeton(conn, identifiant: str, role: str, maintenant: datetime | None = None, duree: timedelta | None = None) -> tuple[str, str]:
    maintenant = maintenant or datetime.now(timezone.utc)
    expire = maintenant + (duree or duree_jeton())
    jti = secrets.token_hex(12)
    charge = _b64(json.dumps({"sub": identifiant, "role": role, "jti": jti, "iat": int(maintenant.timestamp()),
                              "exp": int(expire.timestamp())}, separators=(",", ":")).encode())
    signature = _b64(hmac.new(cle_signature(), charge.encode(), hashlib.sha256).digest())
    conn.execute("INSERT INTO session (jti, utilisateur, cree_le, expire_le) VALUES (?,?,?,?)",
                 (jti, identifiant, maintenant.isoformat(), expire.isoformat()))
    conn.commit()
    return f"{charge}.{signature}", expire.isoformat()


def lire_jeton(jeton: str, conn, maintenant: datetime | None = None) -> dict:
    """Vérifie signature, expiration et révocation. Lève HTTPException 401 en français."""
    non_valide = HTTPException(401, "Jeton invalide ou expiré : reconnectez-vous.", headers={"WWW-Authenticate": "Bearer"})
    try:
        charge, signature = jeton.split(".")
        attendu = _b64(hmac.new(cle_signature(), charge.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(signature.encode(), attendu.encode()):
            raise non_valide
        data = json.loads(_unb64(charge))
    except (ValueError, TypeError, AttributeError, json.JSONDecodeError):
        raise non_valide
    if int(data.get("exp", 0)) < (maintenant or datetime.now(timezone.utc)).timestamp():
        raise HTTPException(401, "Votre session a expiré : reconnectez-vous.", headers={"WWW-Authenticate": "Bearer"})
    s = conn.execute("SELECT revoque FROM session WHERE jti=?", (data.get("jti"),)).fetchone()
    if s is None or s["revoque"]:
        raise non_valide
    return data


# ------------------------------------------------------------------ dépendances FastAPI
def _bypass_tests() -> bool:
    return os.environ.get("OREGDO_AUTH") == "0" and "PYTEST_CURRENT_TEST" in os.environ


UTILISATEUR_TEST = {"identifiant": "test", "nom": "Test (authentification désactivée)", "role": "admin", "zone": None, "point": None}


def utilisateur_optionnel(request: Request, authorization: str | None = Header(None)):
    """Utilisateur connecté, ou None si aucun jeton n'est envoyé (un jeton invalide reste une erreur 401)."""
    if _bypass_tests():
        return UTILISATEUR_TEST
    if not authorization:
        return None
    schema, _, jeton = authorization.partition(" ")
    if schema.lower() != "bearer" or not jeton:
        raise HTTPException(401, "En-tête Authorization incorrect : utilisez « Bearer <jeton> ».", headers={"WWW-Authenticate": "Bearer"})
    conn = base.ouvrir()
    try:
        data = lire_jeton(jeton.strip(), conn)
        u = conn.execute("SELECT * FROM utilisateur WHERE identifiant=?", (data["sub"],)).fetchone()
        if u is None or not u["actif"]:
            raise HTTPException(401, "Compte inexistant ou désactivé.", headers={"WWW-Authenticate": "Bearer"})
        return {"identifiant": u["identifiant"], "nom": u["nom"], "role": u["role"], "zone": u["zone"], "point": u["point"],
                "jti": data["jti"], "derniere_connexion": u["derniere_connexion"]}
    finally:
        conn.close()


def utilisateur_courant(u=Depends(utilisateur_optionnel)):
    if u is None:
        raise HTTPException(401, "Authentification requise : connectez-vous (en-tête Authorization: Bearer <jeton>).",
                            headers={"WWW-Authenticate": "Bearer"})
    return u


def exiger_roles(*roles: str):
    """Dépendance : l'utilisateur doit avoir l'un des rôles (admin passe toujours)."""
    autorises = set(roles) | {"admin"}

    def verifier(u=Depends(utilisateur_courant)):
        if u["role"] not in autorises:
            raise HTTPException(403, f"Action réservée aux rôles : {', '.join(sorted(autorises))}. Votre rôle : {u['role']}.")
        return u
    return verifier


exiger_admin = exiger_roles("admin")
exiger_mairie = exiger_roles("mairie")
exiger_brigade = exiger_roles("brigade")
exiger_precollecteur = exiger_roles("precollecteur")


# ------------------------------------------------------------------ références publiques
def ref_depotoir(did: int) -> str:
    """Référence opaque d'un dépotoir pour la carte publique : la carte ne révèle jamais l'identifiant interne. HMAC de l'identifiant
    avec la clé du serveur : impossible à deviner ou à énumérer, stable tant que la clé ne change pas."""
    digest = hmac.new(cle_signature(), f"depotoir:{int(did)}".encode(), hashlib.sha256).digest()
    return _b64(digest)[:10]


# ------------------------------------------------------------------ audit
def auditer(conn, utilisateur, action: str, cible=None, details=None):
    ident = utilisateur["identifiant"] if isinstance(utilisateur, dict) else utilisateur
    role = utilisateur.get("role") if isinstance(utilisateur, dict) else None
    conn.execute("INSERT INTO audit (date, utilisateur, role, action, cible, details) VALUES (?,?,?,?,?,?)",
                 (base.maintenant(), ident, role, action, None if cible is None else str(cible),
                  None if details is None else (details if isinstance(details, str) else json.dumps(details, ensure_ascii=False))))
    conn.commit()


# ------------------------------------------------------------------ limitation de débit (en mémoire, par processus)
_verrou = threading.Lock()
_passages: dict = {}


def reinitialiser_limites():
    with _verrou:
        _passages.clear()


def limiter(cle: str, maxi: int, fenetre_s: int):
    """Fenêtre glissante. Lève 429 (avec Retry-After) au-delà de `maxi` appels par fenêtre pour cette clé."""
    now = time.monotonic()
    with _verrou:
        liste = [t for t in _passages.get(cle, []) if now - t < fenetre_s]
        if len(liste) >= maxi:
            attente = int(fenetre_s - (now - liste[0])) + 1
            _passages[cle] = liste
            raise HTTPException(429, f"Trop de signalements envoyés depuis cet appareil ou cette connexion : réessayez dans {max(1, attente // 60)} minute(s).",
                                headers={"Retry-After": str(attente)})
        liste.append(now)
        _passages[cle] = liste


def ip_client(request: Request) -> str:
    """Adresse du client pour la limitation de débit. Derrière un proxy ou un tunnel (Cloudflare, nginx), tous les visiteurs arrivent avec
    l'adresse du proxy : avec OREGDO_PROXY_CONFIANT=1, on lit l'adresse transmise par le proxy. Jamais par défaut : un en-tête se falsifie,
    et on ne doit lui faire confiance que si le serveur n'est joignable QUE par ce proxy (écoute sur 127.0.0.1)."""
    if os.environ.get("OREGDO_PROXY_CONFIANT") == "1":
        transmise = request.headers.get("cf-connecting-ip") or request.headers.get("x-forwarded-for", "").split(",")[0].strip()
        if transmise:
            return transmise[:64]
    return request.client.host if request.client else "inconnue"


# compatibilité avec l'ancien nom (plan.py) : le jury est désormais le rôle admin
exiger_jury = exiger_admin
