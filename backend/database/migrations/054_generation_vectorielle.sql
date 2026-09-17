-- Tables additives : aucun vecteur, réglage ou historique existant modifié.
CREATE TABLE IF NOT EXISTS embedding_actif(id INTEGER PRIMARY KEY CHECK(id=1),modele TEXT NOT NULL,updated_at TIMESTAMPTZ NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS embedding_preparations(modele TEXT NOT NULL,dimension INTEGER NOT NULL,phase TEXT NOT NULL,erreur TEXT,updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),PRIMARY KEY(modele,dimension));
CREATE TABLE IF NOT EXISTS embedding_candidats(modele TEXT NOT NULL,dimension INTEGER NOT NULL,source TEXT NOT NULL,document_id UUID NOT NULL,empreinte TEXT NOT NULL,vecteur vector NOT NULL,PRIMARY KEY(modele,dimension,source,document_id));
REVOKE ALL ON embedding_actif, embedding_preparations, embedding_candidats FROM infra_ia_lecteur_rls;
