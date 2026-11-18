-- Schéma SQLite du module de vérification des signalements (Orẽgdo).
-- Règle : on ne supprime JAMAIS un signalement ; un rejet reste en base avec ses motifs.

CREATE TABLE IF NOT EXISTS depotoir (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    lat               REAL NOT NULL,           -- centre du tas (moyenne des signalements)
    lon               REAL NOT NULL,
    nb_signalements   INTEGER NOT NULL,
    nb_enqueteurs     INTEGER NOT NULL,        -- enquêteurs DISTINCTS
    confiance         REAL NOT NULL,           -- 0 à 100
    statut            TEXT NOT NULL DEFAULT 'verifie',
    synthetique       INTEGER NOT NULL DEFAULT 0,
    mis_a_jour_le     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS signalement (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    lat               REAL,                    -- peut être vide si la donnée d'origine est inutilisable
    lon               REAL,
    secteur           TEXT,                    -- secteur déclaré (identifiant ou nom)
    taille            TEXT,                    -- taille estimée
    nature            TEXT,                    -- nature des déchets
    caniveau          INTEGER,                 -- 1 si un caniveau est touché
    accessibilite     TEXT,
    enqueteur         TEXT,
    appareil          TEXT,
    horodatage        TEXT,                    -- date déclarée, ISO 8601
    recu_le           TEXT NOT NULL,           -- date de réception par le serveur
    source            TEXT NOT NULL DEFAULT 'application',   -- application | csv | geojson
    nb_photos         INTEGER NOT NULL DEFAULT 0,
    score             REAL,                    -- 0 à 100
    statut            TEXT NOT NULL,           -- verifie | a_confirmer | rejete
    motifs            TEXT NOT NULL DEFAULT '[]',  -- JSON : un résultat lisible par contrôle
    depotoir_id       INTEGER REFERENCES depotoir(id),
    synthetique       INTEGER NOT NULL DEFAULT 0,
    essai             INTEGER NOT NULL DEFAULT 0,   -- 1 : lot d'essai (pièges du jury) ; conservé mais exclu par défaut
    photo_plausible   INTEGER NOT NULL DEFAULT 0,   -- 1 : au moins une photo jugée plausible
    exif_coherent     INTEGER NOT NULL DEFAULT 0,   -- 1 : EXIF cohérent avec la position et la date déclarées
    utilisateur       TEXT,                         -- compte connecté qui a envoyé le signalement (enquêteur)
    code_suivi        TEXT,                         -- code remis au citoyen pour suivre son signalement
    audio             TEXT,                         -- nom du fichier du message vocal (effacé après conservation_jours), jamais exposé
    cle_client        TEXT                          -- clé tirée par le téléphone : un renvoi après coupure ne crée jamais un second signalement
);
CREATE INDEX IF NOT EXISTS idx_signalement_statut ON signalement(statut);
CREATE INDEX IF NOT EXISTS idx_signalement_appareil ON signalement(appareil);
CREATE INDEX IF NOT EXISTS idx_signalement_code ON signalement(code_suivi);
CREATE INDEX IF NOT EXISTS idx_signalement_cle ON signalement(cle_client) WHERE cle_client IS NOT NULL;

-- Empreintes perceptuelles des photos déjà reçues (la photo elle-même n'est pas conservée).
CREATE TABLE IF NOT EXISTS photo (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    signalement_id    INTEGER NOT NULL REFERENCES signalement(id),
    empreinte         TEXT NOT NULL            -- pHash en hexadécimal
);
CREATE INDEX IF NOT EXISTS idx_photo_signalement ON photo(signalement_id);

-- Journal des décisions : décision automatique à la réception, puis chaque revalidation manuelle.
CREATE TABLE IF NOT EXISTS journal (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    signalement_id    INTEGER NOT NULL REFERENCES signalement(id),
    ancien_statut     TEXT,
    nouveau_statut    TEXT NOT NULL,
    agent             TEXT NOT NULL,           -- 'automatique' ou nom de l'agent
    motif             TEXT,
    date              TEXT NOT NULL
);

-- Lignes d'un fichier importé qui n'ont pas pu être lues (conservées pour l'audit).
CREATE TABLE IF NOT EXISTS ligne_refusee (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    fichier           TEXT,
    ligne             INTEGER,
    raison            TEXT NOT NULL,
    contenu           TEXT,
    date              TEXT NOT NULL
);

-- ------------------------------------------------------------------ portails (comptes, audit, terrain)
CREATE TABLE IF NOT EXISTS utilisateur (
    identifiant       TEXT PRIMARY KEY,
    nom               TEXT NOT NULL,
    role              TEXT NOT NULL,           -- precollecteur | brigade | mairie | admin
    zone              TEXT,                    -- secteur ou quartier d'opération
    point             TEXT,                    -- point de regroupement de rattachement (pré-collecteur)
    mot_de_passe      TEXT NOT NULL,           -- scrypt$n$r$p$sel$hash (jamais en clair)
    actif             INTEGER NOT NULL DEFAULT 1,
    cree_le           TEXT NOT NULL,
    derniere_connexion TEXT,
    echecs            INTEGER NOT NULL DEFAULT 0,
    verrouille_jusqua TEXT
);

CREATE TABLE IF NOT EXISTS session (           -- jetons émis (pour la déconnexion = révocation)
    jti               TEXT PRIMARY KEY,
    utilisateur       TEXT NOT NULL,
    cree_le           TEXT NOT NULL,
    expire_le         TEXT NOT NULL,
    revoque           INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS audit (             -- actions sensibles, avec l'identifiant de l'utilisateur
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    date              TEXT NOT NULL,
    utilisateur       TEXT,
    role              TEXT,
    action            TEXT NOT NULL,
    cible             TEXT,
    details           TEXT
);

CREATE TABLE IF NOT EXISTS notification_lue (  -- dernière lecture du centre de notifications, par compte (les événements viennent du journal)
    utilisateur       TEXT PRIMARY KEY,
    vu_le             TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS collecte (          -- registre de collecte des pré-collecteurs
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    date              TEXT NOT NULL,
    kg                REAL NOT NULL,
    nb_menages        INTEGER NOT NULL,
    point             TEXT,
    utilisateur       TEXT NOT NULL,
    saisi_le          TEXT NOT NULL,
    cle_client        TEXT                     -- clé tirée par le téléphone : un renvoi après coupure ne double jamais le poids
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_collecte_cle ON collecte(utilisateur, cle_client) WHERE cle_client IS NOT NULL;

CREATE TABLE IF NOT EXISTS avis (              -- « moi aussi je le vois » / « ce tas n'est plus là » : avis de voisins sur un dépotoir
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    depotoir_id       INTEGER NOT NULL REFERENCES depotoir(id),
    type              TEXT NOT NULL,           -- present | disparu
    appareil          TEXT NOT NULL,           -- identifiant d'appareil déclaré par l'application (non authentifié)
    distance_m        REAL,                    -- distance entre le GPS de l'appareil et le dépotoir (preuve de présence)
    date              TEXT NOT NULL,
    signalement_id    INTEGER REFERENCES signalement(id)   -- pour « present » : le signalement créé dans le pipeline
);
CREATE INDEX IF NOT EXISTS idx_avis_depotoir ON avis(depotoir_id, type);

CREATE TABLE IF NOT EXISTS intervention (      -- sensibilisation puis sanction de la brigade
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    depotoir_id       INTEGER NOT NULL REFERENCES depotoir(id),
    type              TEXT NOT NULL,           -- sensibilisation | sanction
    date              TEXT NOT NULL,
    agent             TEXT NOT NULL,
    issue             TEXT,
    numero_pv         TEXT,
    montant_fcfa      INTEGER,
    recidive          INTEGER NOT NULL DEFAULT 0,
    flagrant_delit    INTEGER NOT NULL DEFAULT 0,
    motif_flagrant    TEXT,
    synthetique       INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_intervention_depotoir ON intervention(depotoir_id);
