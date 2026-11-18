"""Graphe routier réel (OpenStreetMap) : distances de plus court chemin et tracés qui suivent les routes.

Le graphe est construit par `scripts/build_osm_layers.py` (nœuds = intersections, arêtes = tronçons de route carrossable, longueur
en mètres). Il remplace « distance à vol d'oiseau x 1,3 » (hypothèse validée : sur des paires réelles, route / vol d'oiseau = 1,27 en
médiane).

Rattachement d'un point au réseau : au point le plus proche SUR un tronçon (pas à l'intersection la plus proche, qui ajoutait en moyenne
~120 m d'écart). Le trajet part du point, rejoint la route (distance perpendiculaire h), puis sort par l'une ou l'autre des deux
intersections du tronçon avec le décalage exact le long du tronçon. On garde la meilleure des quatre combinaisons de deux points.

Saison des pluies, par tronçon (mêmes paramètres que le reste du moteur, `planification.saison_pluies`) :
  - tronçon non revêtu : longueur x facteur_cout_piste (les camions seulement) ;
  - tronçon à moins de rayon_zone_inondable_m de l'eau : longueur x facteur_zone_inondable (tous).
Hypothèses [H] : sens uniques ignorés (peu nombreux à Ouagadougou), revêtement déduit du type de route et du tag `surface` d'OSM.

Vitesse (mesurée : ~30 ms par source sur 102 000 nœuds, ~1 ms avec une limite de 1,5 km) :
  - accès des habitants (rayon 1 km) : Dijkstra avec limite, quasi instantané ;
  - tournées : les « hubs » (sites candidats, dépôt, CET) sont fixes. Leurs distances mutuelles sont calculées une fois, gardées sur
    disque (data/cache) et préchauffées au démarrage ; seuls les points qui changent (dépotoirs, nouveau quartier) coûtent un calcul,
    mis en cache. Le tracé final d'un trajet est un Dijkstra local, borné par la distance déjà connue.
Si le fichier du graphe est absent, `charger` renvoie None et le moteur retombe sur l'ancien calcul.
"""
import hashlib
from collections import OrderedDict
from functools import lru_cache

import numpy as np
import shapely
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import dijkstra
from scipy.spatial.distance import cdist
from shapely import STRtree

from ..config import COMMUNE_DEFAUT, RACINE, charger_config
from .parametres import moteur

LOT = 64               # sources traitées par lot : borne la mémoire (lot x nœuds x 8 octets)
LIGNES_EN_CACHE = 640  # lignes complètes (float32, ~0,4 Mo, soit ~260 Mo) pour les points hors hubs : ~100 dépotoirs x 2 intersections x 2 saisons
TRAJETS_EN_CACHE = 20000   # trajets intersection -> intersection déjà tracés (~0,6 ko chacun), partagés entre les plans


class Accroche:
    """Rattachement d'un jeu de points au réseau : tronçon, distance à la route, décalage le long du tronçon."""

    def __init__(self, g, xy):
        pts = shapely.points(np.asarray(xy, float))
        idx, dist = g.arbre.query_nearest(pts, return_distance=True, all_matches=False)
        self.e = np.empty(len(pts), np.int64)
        self.h = np.empty(len(pts))
        self.e[idx[0]], self.h[idx[0]] = idx[1], dist
        self.loc = shapely.line_locate_point(g.lignes[self.e], pts)         # mètres depuis le nœud eu du tronçon
        self.u, self.v = g.eu[self.e], g.ev[self.e]
        self.long = g.longueur[self.e]
        self.loc = np.clip(self.loc, 0.0, self.long)

    def couts(self, facteur_arete):
        """Coût de sortie par l'intersection u et par v (route : h ; le long du tronçon : décalage x facteur de saison)."""
        f = facteur_arete[self.e]
        return self.h + self.loc * f, self.h + (self.long - self.loc) * f


class Graphe:
    def __init__(self, donnees, cfg, signature):
        self.xy = donnees["noeuds_xy"]
        self.eu, self.ev = donnees["eu"].astype(np.int64), donnees["ev"].astype(np.int64)
        self.longueur = donnees["longueur"].astype(np.float64)
        self.revetue = donnees["revetue"].astype(bool)
        self.d_eau = donnees["d_eau"].astype(np.float64)
        self.debut = donnees["debut"]
        self.geometrie = donnees["geometrie"]
        self.origine = donnees["origine"]
        self.n = len(self.xy)
        sommets = self.geometrie.astype(np.float64) + self.origine
        self.lignes = shapely.linestrings(sommets, indices=np.repeat(np.arange(len(self.eu)), np.diff(self.debut)))
        self.arbre = STRtree(self.lignes)
        self.sp = cfg.planification.saison_pluies
        self.signature = signature
        cle = np.minimum(self.eu, self.ev) * self.n + np.maximum(self.eu, self.ev)
        self._ordre = np.argsort(cle)
        self._cles = cle[self._ordre]
        self._csr = {}
        self._facteurs = {}
        self._lru = {}
        self._hubs = None          # nœuds des hubs (triés)
        self._hub_pos = {}
        self._hub_mat = {}         # (saison, acces) -> matrice float32 hubs x hubs
        self._hub_pred = {}        # (saison, acces) -> prédécesseurs int32 hubs x nœuds
        self._lignes = OrderedDict()
        self.trajets = {}          # (nœud a, nœud b, mode) -> sommets du trajet, en mètres

    # ---------------------------------------------------------------- poids
    def facteur(self, saison_pluies: bool, acces: bool = False):
        """Multiplicateur de longueur de chaque tronçon. `acces` : accès à pied ou en tricycle, seule la zone inondable compte."""
        cle = (bool(saison_pluies), bool(acces))
        if cle not in self._facteurs:
            f = np.ones_like(self.longueur)
            if saison_pluies:
                if not acces:
                    f[~self.revetue] = self.sp.facteur_cout_piste
                f[self.d_eau <= self.sp.rayon_zone_inondable_m] = self.sp.facteur_zone_inondable
            self._facteurs[cle] = f
        return self._facteurs[cle]

    def csr(self, saison_pluies: bool, acces: bool = False):
        cle = (bool(saison_pluies), bool(acces))
        if cle not in self._csr:
            # Matrice SYMÉTRIQUE (chaque tronçon dans les deux sens) : Dijkstra en mode orienté, sans retransposer à chaque appel.
            p = self.longueur * self.facteur(*cle)
            self._csr[cle] = coo_matrix((np.concatenate([p, p]), (np.concatenate([self.eu, self.ev]), np.concatenate([self.ev, self.eu]))),
                                        shape=(self.n, self.n)).tocsr()
        return self._csr[cle]

    @staticmethod
    def _combiner(ca, cb, d, ia, ib):
        """Meilleure des quatre combinaisons (sortie par u ou v de chaque point) : matrice na x nb et choix retenu."""
        (cua, cva), (cub, cvb) = ca, cb
        quatre = np.stack([cua[:, None] + d[np.ix_(ia[0], ib[0])] + cub[None, :], cua[:, None] + d[np.ix_(ia[0], ib[1])] + cvb[None, :],
                           cva[:, None] + d[np.ix_(ia[1], ib[0])] + cub[None, :], cva[:, None] + d[np.ix_(ia[1], ib[1])] + cvb[None, :]])
        return quatre.min(axis=0), quatre.argmin(axis=0)

    def _meme_tronconc(self, a, b, m, f):
        """Deux points sur le même tronçon : le trajet direct le long du tronçon peut être plus court que par les intersections."""
        meme = a.e[:, None] == b.e[None, :]
        if meme.any():
            direct = np.abs(a.loc[:, None] - b.loc[None, :]) * f[a.e][:, None] + a.h[:, None] + b.h[None, :]
            m = np.where(meme, np.minimum(m, direct), m)
        return m

    # ---------------------------------------------------------------- distances locales (accès des habitants)
    def matrice(self, xy_a, xy_b, saison_pluies: bool, acces: bool = False, limite: float | None = None) -> np.ndarray:
        """Distance en mètres entre chaque point de xy_a et chaque point de xy_b (plus court chemin routier).
        `limite` : au-delà, la distance n'intéresse pas l'appelant (renvoyée comme 1e9) ; accélère beaucoup."""
        xy_a, xy_b = np.asarray(xy_a, float), np.asarray(xy_b, float)
        cle = (xy_a.tobytes(), xy_b.tobytes(), bool(saison_pluies), bool(acces), limite)
        if cle in self._lru:
            return self._lru[cle]
        a, b = Accroche(self, xy_a), Accroche(self, xy_b)
        f = self.facteur(saison_pluies, acces)
        ua, ub = np.unique(np.concatenate([a.u, a.v])), np.unique(np.concatenate([b.u, b.v]))
        w = self.csr(saison_pluies, acces)
        d = np.empty((len(ua), len(ub)))
        lim = np.inf if limite is None else limite
        if len(ua) <= len(ub):
            for k in range(0, len(ua), LOT):
                d[k:k + LOT] = dijkstra(w, directed=True, indices=ua[k:k + LOT], limit=lim)[:, ub]
        else:
            for k in range(0, len(ub), LOT):
                d[:, k:k + LOT] = dijkstra(w, directed=True, indices=ub[k:k + LOT], limit=lim)[:, ua].T
        ia = (np.searchsorted(ua, a.u), np.searchsorted(ua, a.v))
        ib = (np.searchsorted(ub, b.u), np.searchsorted(ub, b.v))
        m, _ = self._combiner(a.couts(f), b.couts(f), d, ia, ib)
        m = self._meme_tronconc(a, b, m, f)
        m[cdist(xy_a, xy_b) < 0.5] = 0.0                         # deux points confondus : distance nulle
        m[~np.isfinite(m)] = 1e9                                 # hors limite ou inaccessible : coût prohibitif plutôt que l'infini
        if len(self._lru) >= 8:
            self._lru.pop(next(iter(self._lru)))
        self._lru[cle] = m
        return m

    # ---------------------------------------------------------------- hubs (tournées)
    def definir_hubs(self, xy_hubs):
        """Fixe les points stables du réseau (sites candidats, dépôt, CET). Sans effet s'ils sont déjà connus."""
        a = Accroche(self, xy_hubs)
        noeuds = np.unique(np.concatenate([a.u, a.v]))
        if self._hubs is None or not np.array_equal(noeuds, self._hubs):
            self._hubs, self._hub_pos, self._hub_mat, self._hub_pred = noeuds, {int(n): i for i, n in enumerate(noeuds)}, {}, {}

    def _matrice_hubs(self, saison_pluies: bool, acces: bool):
        """Distances entre hubs (float32, hubs x hubs). Calcule aussi les prédécesseurs de chaque hub vers tous les nœuds
        (int32, hubs x nœuds, lus par mappage mémoire) : un trajet entre hubs devient une simple lecture de tableau."""
        cle = (bool(saison_pluies), bool(acces))
        if cle in self._hub_mat:
            return self._hub_mat[cle]
        h = hashlib.sha1(self._hubs.tobytes() + repr((self.signature, cle, self.sp.facteur_cout_piste, self.sp.facteur_zone_inondable,
                                                      self.sp.rayon_zone_inondable_m)).encode()).hexdigest()[:16]
        f_dist, f_pred = (RACINE / "data" / "cache" / f"hubs_{h}.npy"), (RACINE / "data" / "cache" / f"preds_{h}.npy")
        m = None
        if f_dist.exists() and f_pred.exists():
            try:
                m = np.load(f_dist)
                self._hub_pred[cle] = np.load(f_pred, mmap_mode="r")
            except (OSError, ValueError, EOFError):              # cache abîmé (écriture interrompue, disque plein) : on recalcule
                m = None
        if m is None:
            w = self.csr(*cle)
            m = np.empty((len(self._hubs),) * 2, np.float32)
            preds = np.empty((len(self._hubs), self.n), np.int32)
            for k in range(0, len(self._hubs), LOT):
                dist, pr = dijkstra(w, directed=True, indices=self._hubs[k:k + LOT], return_predecessors=True)
                m[k:k + LOT], preds[k:k + LOT] = dist[:, self._hubs], pr
            try:
                f_dist.parent.mkdir(parents=True, exist_ok=True)
                np.save(f_dist, m)
                np.save(f_pred, preds)
                self._hub_pred[cle] = np.load(f_pred, mmap_mode="r")
            except (OSError, ValueError, EOFError):               # le cache disque est un confort, jamais une obligation
                self._hub_pred[cle] = preds
        self._hub_mat[cle] = m
        return m

    def chauffer(self, xy_hubs):
        """Précalcule les distances entre hubs, hors saison et en saison des pluies (au démarrage du serveur)."""
        self.definir_hubs(xy_hubs)
        for saison in (False, True):
            self._matrice_hubs(saison, False)

    def _ligne(self, noeud, saison_pluies, acces):
        """Distances (float32) d'un nœud vers tous les autres, mises en cache."""
        cle = (int(noeud), bool(saison_pluies), bool(acces))
        if cle in self._lignes:
            self._lignes.move_to_end(cle)
            return self._lignes[cle]
        ligne = dijkstra(self.csr(saison_pluies, acces), directed=True, indices=int(noeud)).astype(np.float32)
        self._lignes[cle] = ligne
        if len(self._lignes) > LIGNES_EN_CACHE:
            self._lignes.popitem(last=False)
        return ligne

    # ---------------------------------------------------------------- tournées : distances entre arrêts et tracés
    def tournees(self, xy, saison_pluies: bool, acces: bool = False):
        """Distances entre tous les points de `xy` (arrêts d'un plan) et de quoi tracer chaque trajet le long des routes."""
        xy = np.asarray(xy, float)
        a = Accroche(self, xy)
        f = self.facteur(saison_pluies, acces)
        un = np.unique(np.concatenate([a.u, a.v]))
        d = np.full((len(un), len(un)), np.inf)
        dans_hub = np.array([self._hub_pos.get(int(n), -1) for n in un]) if self._hubs is not None else np.full(len(un), -1)
        est_hub = dans_hub >= 0
        if est_hub.any():
            hm = self._matrice_hubs(saison_pluies, acces)
            ih = np.flatnonzero(est_hub)
            d[np.ix_(ih, ih)] = hm[np.ix_(dans_hub[ih], dans_hub[ih])]
        for k in np.flatnonzero(~est_hub):                       # dépotoirs, nouveaux quartiers : une ligne complète chacun
            ligne = self._ligne(un[k], saison_pluies, acces)[un]
            d[k, :] = ligne
            d[:, k] = ligne                                      # graphe non orienté : distance symétrique
        ia = (np.searchsorted(un, a.u), np.searchsorted(un, a.v))
        m, choix = self._combiner(a.couts(f), a.couts(f), d, ia, ia)
        m = self._meme_tronconc(a, a, m, f)
        m[cdist(xy, xy) < 0.5] = 0.0                             # points confondus (dont la diagonale) : distance nulle
        m[~np.isfinite(m)] = 1e9
        return Chemins(self, xy, a, ia, choix, m, self.csr(saison_pluies, acces), (bool(saison_pluies), bool(acces)))

    def noeuds_du_trajet(self, a, b, mode, w, borne):
        """Nœuds du plus court chemin de a à b, ou None. Hub à une extrémité : lecture de son arbre (instantané) ; sinon
        Dijkstra local borné par la distance déjà connue."""
        for debut, fin, inverse in ((a, b, False), (b, a, True)):
            i = self._hub_pos.get(int(debut), -1)
            if i >= 0 and mode in self._hub_pred:
                pr, n, noeuds = self._hub_pred[mode][i], fin, [fin]
                while n != debut:
                    n = int(pr[n])
                    if n < 0:
                        return None
                    noeuds.append(n)
                return noeuds if inverse else noeuds[::-1]
        dist, pr = dijkstra(w, directed=True, indices=a, limit=borne, return_predecessors=True)
        if not np.isfinite(dist[b]):
            return None
        noeuds, n = [b], b
        while n != a:
            n = int(pr[n])
            noeuds.append(n)
        return noeuds[::-1]

    def _arete(self, a, b):
        c = min(a, b) * self.n + max(a, b)
        i = np.searchsorted(self._cles, c)
        return int(self._ordre[i]) if i < len(self._cles) and self._cles[i] == c else None

    def polyligne(self, e, de, vers):
        """Sommets (mètres) du tronçon e parcouru de `de` vers `vers`."""
        pts = self.geometrie[self.debut[e]:self.debut[e + 1]].astype(np.float64) + self.origine
        return pts if self.eu[e] == de and self.ev[e] == vers else pts[::-1]


class Chemins:
    """Distances d'un jeu de points ; `trace(i, j)` donne le trajet en mètres, le long des routes (Dijkstra local borné)."""

    def __init__(self, g, xy, acc, ia, choix, matrice, w, mode):
        self.g, self.xy, self.acc, self.ia, self.choix, self.matrice, self.w, self.mode = g, xy, acc, ia, choix, matrice, w, mode
        self._traces = {}

    def tracer_tout(self, paires):
        """Calcule d'un coup les trajets de toutes les paires (i, j). Séquentiel : scipy garde le verrou Python pendant Dijkstra
        (mesuré : aucun gain avec des fils), et le cache de trajets du graphe n'est pas protégé contre les accès concurrents."""
        for p in dict.fromkeys(paires):
            if p not in self._traces:
                self._traces[p] = self._tracer(*p)

    def trace(self, i, j):
        if (i, j) not in self._traces:
            self._traces[(i, j)] = self._tracer(i, j)
        return self._traces[(i, j)]

    def _tracer(self, i, j):
        g, acc = self.g, self.acc
        k = int(self.choix[i, j])                               # 0 : (u,u) 1 : (u,v) 2 : (v,u) 3 : (v,v)
        a = int(acc.u[i] if k < 2 else acc.v[i])
        b = int(acc.u[j] if k % 2 == 0 else acc.v[j])
        sortie = [self.xy[i][None, :], g.xy[a][None, :]]
        if a != b:
            cle = (a, b, self.mode)
            milieu = g.trajets.get(cle)
            if milieu is None:
                noeuds = g.noeuds_du_trajet(a, b, self.mode, self.w, float(self.matrice[i, j]) * 1.05 + 200)
                if noeuds is None:
                    return np.vstack([self.xy[i], self.xy[j]])       # pas de chemin : ligne droite plutôt qu'un trou
                milieu = np.vstack([g.polyligne(e, de, vers) if (e := g._arete(de, vers)) is not None
                                    else np.vstack([g.xy[de], g.xy[vers]]) for de, vers in zip(noeuds[:-1], noeuds[1:])])
                g.trajets[cle] = milieu
                if len(g.trajets) > TRAJETS_EN_CACHE:
                    g.trajets.pop(next(iter(g.trajets)))
            sortie.append(milieu)
        sortie += [g.xy[b][None, :], self.xy[j][None, :]]
        return np.vstack(sortie)                                 # tableau (k, 2) en mètres


@lru_cache(maxsize=4)
def charger(commune: str = COMMUNE_DEFAUT):
    """Graphe de la commune, ou None si le fichier est absent ou désactivé (`planification.moteur.graphe_routier`)."""
    cfg = charger_config(commune)
    nom = getattr(moteur(cfg), "graphe_routier", None)
    if not nom:
        return None
    chemin = cfg.dossier_pack / nom
    if not chemin.exists():
        return None
    st = chemin.stat()
    with np.load(chemin) as f:
        return Graphe({k: f[k] for k in f.files}, cfg, f"{nom}:{st.st_size}:{int(st.st_mtime)}")
