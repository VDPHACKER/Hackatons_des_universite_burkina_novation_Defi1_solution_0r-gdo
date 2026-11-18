"""Graphe routier OSM : propriétés physiques des distances, limite, saison des pluies, tracés, repli sans graphe."""
import numpy as np
import pytest
from scipy.spatial.distance import cdist

from oregdo.planning import donnees, graphe_routier, plan
from oregdo.planning.scenario import Scenario

g = graphe_routier.charger("ouaga")
pytestmark = pytest.mark.skipif(g is None, reason="graphe routier absent : lancer scripts/build_osm_layers.py")


@pytest.fixture(scope="module")
def pts():
    base = donnees.charger("ouaga")
    rng = np.random.default_rng(5)
    return base.sites_xy[rng.choice(len(base.sites_xy), 40, replace=False)]


def test_la_route_n_est_jamais_plus_courte_que_le_vol_d_oiseau(pts):
    m = g.matrice(pts, pts, False)
    crow = cdist(pts, pts)
    assert np.all(m >= crow - 1.0)                       # tolérance d'un mètre (arrondis de projection)
    proches = (crow > 300) & (crow < 1500)
    ratio = m[proches] / crow[proches]
    assert 1.0 <= np.median(ratio) <= 1.6                # mesuré : 1,27 ; l'hypothèse historique du moteur était 1,3


def test_distances_symetriques_et_nulles_sur_la_diagonale(pts):
    m = g.matrice(pts, pts, False)
    assert np.allclose(m, m.T, atol=1e-6)
    assert np.allclose(np.diag(m), 0, atol=1e-6)


def test_matrice_asymetrique_coherente_avec_la_matrice_carree(pts):
    a, b = pts[:10], pts[10:25]
    assert np.allclose(g.matrice(a, b, False), g.matrice(pts, pts, False)[:10, 10:25], atol=1e-3)


def test_limite_ne_change_pas_les_distances_proches_et_ecarte_les_lointaines(pts):
    libre = g.matrice(pts, pts, False)
    borne = g.matrice(pts, pts, False, limite=1500)
    proches = libre <= 1500 - 200                         # marge : la limite porte sur le trajet entre intersections
    assert np.allclose(borne[proches], libre[proches], atol=1e-6)
    assert np.all(borne[libre > 2500] >= 1e8)             # hors limite : coût prohibitif


def test_la_saison_des_pluies_n_accourcit_jamais_un_trajet(pts):
    sec, pluie = g.matrice(pts, pts, False), g.matrice(pts, pts, True)
    assert np.all(pluie >= sec - 1e-6) and (pluie > sec + 1.0).any()
    acces = g.matrice(pts, pts, True, acces=True)          # à pied : seule la zone inondable compte, donc <= camion
    assert np.all(acces <= pluie + 1e-6) and np.all(acces >= sec - 1e-6)


def test_tournees_distances_et_traces(pts):
    g.definir_hubs(pts)                                    # ici, tous les points sont des hubs (distances précalculées)
    c = g.tournees(pts, False)
    assert np.allclose(c.matrice, g.matrice(pts, pts, False), rtol=1e-3, atol=2.0)      # hubs en float32
    for i, j in ((0, 5), (3, 17), (10, 2)):
        ligne = c.trace(i, j)
        assert np.allclose(ligne[0], pts[i]) and np.allclose(ligne[-1], pts[j])         # le tracé part et arrive aux bons points
        longueur = np.hypot(*np.diff(ligne, axis=0).T).sum()
        assert 0.7 * c.matrice[i, j] <= longueur <= 1.15 * c.matrice[i, j] + 100        # il suit les routes : même ordre de grandeur


def test_trace_d_un_point_hors_hub_utilise_le_dijkstra_local(pts):
    g.definir_hubs(pts[:20])
    c = g.tournees(pts, False)
    ligne = c.trace(30, 35)                                # ni l'un ni l'autre n'est un hub
    assert np.allclose(ligne[0], pts[30]) and np.allclose(ligne[-1], pts[35]) and len(ligne) > 3


def test_le_plan_se_calcule_sans_graphe(monkeypatch):
    """Repli : sans fichier de graphe, ancien calcul (vol d'oiseau x détour) ; aucune erreur."""
    monkeypatch.setattr(graphe_routier, "charger", lambda commune="ouaga": None)
    p = plan.calculer_plan(Scenario.depuis_config())
    assert p["tournees"]["features"] and p["kpi"]["nb_pr"] > 0
    assert all(len(f["geometry"]["coordinates"]) >= 2 for f in p["tournees"]["features"])


def test_tournees_suivent_les_routes_avec_le_graphe():
    """Avec le graphe, une tournée a beaucoup plus de sommets que ses arrêts : elle suit les routes."""
    p = plan.calculer_plan(Scenario.depuis_config())
    f = p["tournees"]["features"][0]
    assert len(f["geometry"]["coordinates"]) > 5 * (len(f["properties"]["arrets"]) + 2)


def test_un_cache_abime_est_recalcule_sans_planter(tmp_path, monkeypatch, pts):
    """Vu à l'essai à froid dans Docker : un fichier de cache tronqué faisait planter le premier calcul (EOFError)."""
    import gc
    monkeypatch.setattr(graphe_routier, "RACINE", tmp_path)
    gr = graphe_routier.charger("ouaga")                 # objet partagé (lru_cache) : on vide ses mémoires internes
    etat = {k: getattr(gr, k) for k in ("_hubs", "_hub_pos", "_hub_mat", "_hub_pred")}
    try:
        gr._hubs = None
        gr.definir_hubs(pts[:6])
        attendu = np.array(gr._matrice_hubs(False, False))
        fichiers = list((tmp_path / "data" / "cache").glob("*.npy"))
        assert len(fichiers) == 2
        gr._hub_mat.clear(); gr._hub_pred.clear(); gc.collect()   # Windows : libérer la projection mémoire du fichier
        for f in fichiers:                               # écriture interrompue : fichiers vides
            f.write_bytes(b"")
        assert np.allclose(gr._matrice_hubs(False, False), attendu)
    finally:                                             # rendre le graphe partagé aux autres tests tel qu'il était
        gr._hub_mat, gr._hub_pred = {}, {}
        gc.collect()
        for k, v in etat.items():
            setattr(gr, k, v)
