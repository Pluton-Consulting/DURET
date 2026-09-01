"""Les suites proposées après un tour, par situation — CONTENU MÉTIER.

Fichier PAR CLIENT (déclaré dans la dérive), pendant exact de
`frontend/lib/raccourcis.ts` : le MÉCANISME vit dans `agents/suggestions.py`
(socle, identique des deux côtés), le VOCABULAIRE est celui d'une entreprise de
sols et revêtements qui répond à des appels d'offres.

Règles d'écriture, non négociables — ce sont elles qui rendent une suggestion
mécanique compatible avec la règle de Noa (« aucun message déterministe dans le
chat ») :
  · à l'IMPÉRATIF et du point de vue de l'UTILISATEUR (c'est ce qu'IL dirait) ;
  · jamais une question — c'est ce que le forceur `propose_au_lieu_d_agir`
    combat depuis le 31/08 ;
  · jamais une donnée du tour (aucun nom, aucun montant, aucune date), rien que
    du vocabulaire fixe : c'est ce qui permet de les poser APRÈS la
    réhydratation sans qu'un jeton d'anonymisation puisse fuir.
`backend/scripts/test_suggestions.py` fait respecter ces trois règles ligne à
ligne — ajouter une entrée qui les viole fait tomber le banc.
"""

# Par SKILL qui vient de réussir. La clé est le nom exact du skill.
PAR_SKILL: dict[str, list[str]] = {
    # ── Mémoire d'entreprise ────────────────────────────────────────────
    "rechercher_documents": ["Ouvre le premier document",
                             "Les 20 documents suivants",
                             "Cherche la même chose dans les marchés"],
    "interroger_donnees":   ["La suite du classement",
                             "Le détail mois par mois",
                             "Exporte ça en Excel"],
    # ── Clients, chantiers, appels d'offres ─────────────────────────────
    "fiche_client":         ["Montre son dernier marché en entier",
                             "Ses chantiers des 12 derniers mois",
                             "Rédige-lui une relance"],
    "liste_clients":        ["Exporte la liste en Excel",
                             "Ceux sans consultation depuis 6 mois",
                             "Le chiffre d'affaires par client"],
    "liste_fournisseurs":   ["Exporte la liste en Excel",
                             "Les prix observés chez eux"],
    "dossiers_en_attente":  ["Relance le plus ancien",
                             "Prépare toutes les relances de la semaine",
                             "Ceux sans réponse depuis 30 jours"],
    "prix_observes":        ["Compare avec le prix du marché",
                             "Chiffre un poste de plus",
                             "Prépare le chiffrage avec ces prix"],
    # ── Courrier ────────────────────────────────────────────────────────
    "check_mails":          ["Ouvre le premier message",
                             "Propose une réponse pour chacun",
                             "Les messages plus anciens"],
    "lire_mails":           ["Ouvre le premier message",
                             "Propose une réponse pour chacun",
                             "Les messages plus anciens"],
    "lire_mail":            ["Réponds à ce message",
                             "Lis les pièces jointes",
                             "Retrouve le dossier de ce client"],
    "lire_piece_jointe":    ["Sors le métré de ce plan",
                             "Retrouve le dossier du chantier",
                             "Réponds au message avec ces éléments"],
    "boites_mail":          ["Fais le point sur les 7 derniers jours",
                             "Ouvre le dernier message reçu"],
    "preparer_envois":      ["Envoie tout le lot",
                             "Change le texte du modèle",
                             "Ajoute des destinataires"],
    "redaction_email":      ["Fais-en une version plus courte",
                             "Joins le devis",
                             "Envoie-le"],
    "envoyer_email":        ["Programme une relance dans 8 jours",
                             "Écris le même message à un autre client",
                             "Fais le point sur mes mails"],
    "triage_email_entrant": ["Prépare la réponse",
                             "Retrouve l'historique de ce client"],
    "resume_fil_email":     ["Prépare la réponse",
                             "Ouvre le dernier message du fil"],
    # ── Documents produits ──────────────────────────────────────────────
    "produire_document":    ["Dépose-le sur le NAS",
                             "Envoie-le au client",
                             "Ajoute le détail par lot"],
    "terminer_document":    ["Dépose-le sur le NAS",
                             "Envoie-le au client",
                             "Refais-le avec le détail par poste"],
    "creer_document":       ["Ajoute le mémoire technique",
                             "Termine le document"],
    # ── Le NAS ──────────────────────────────────────────────────────────
    "nas_arborescence":     ["Ouvre le dossier des chantiers",
                             "Cherche « CCTP » dedans"],
    "nas_lister":           ["Ouvre le premier fichier",
                             "Résume-moi ce document"],
    "nas_chercher":         ["Ouvre le premier fichier",
                             "Résume-moi ce document"],
    "nas_ouvrir":           ["Résume-moi ce document",
                             "Sors les quantités de ce document"],
    "nas_lire":             ["Résume-moi ce document",
                             "Sors les quantités de ce document"],
    "nas_lire_lot":         ["Fais-en une synthèse", "Compare-les"],
    "nas_apercu":           ["Ouvre-le en entier", "Résume-moi ce document"],
    "nas_photos":           ["Retrouve le chantier correspondant",
                             "Fais le point sur son avancement"],
    "nas_deposer":          ["Envoie le lien au client",
                             "Range-le dans le dossier du chantier"],
    "nas_deposer_document": ["Envoie le lien au client",
                             "Range-le dans le dossier du chantier"],
    # ── Web ─────────────────────────────────────────────────────────────
    "chercher_web":         ["Ouvre le premier résultat",
                             "Compare avec nos prix observés"],
    "ouvrir_page":          ["Compare avec nos prix observés",
                             "Retiens cette information"],
    "naviguer":             ["Compare avec nos prix observés",
                             "Retiens cette information"],
    # ── Apprentissage, droits ───────────────────────────────────────────
    "retenir":              ["Relis-moi toutes les consignes",
                             "Applique-la au prochain chiffrage"],
    "consignes_retenues":   ["Retiens une nouvelle consigne",
                             "Oublie la dernière"],
    "connaissances_acquises": ["Retiens une nouvelle consigne",
                               "Cherche dans les documents"],
    "enregistrer_procedure": ["Relis-moi toutes les consignes",
                              "Applique-la maintenant"],
    "mes_droits":           ["Montre-moi ce que tu sais faire",
                             "Fais le point sur mes mails"],
    "mode_emploi":          ["Fais le point sur mes mails de la semaine",
                             "Quels dossiers sont en attente"],
}

# Repli PAR BLOC présent à l'écran, quand aucun skill de la table n'a tourné.
PAR_BLOC: dict[str, list[str]] = {
    "visuel":  ["Retrouve le chantier correspondant",
                "Envoie-le au client"],
    "fichier": ["Dépose-le sur le NAS", "Envoie-le au client",
                "Ajoute-y une colonne"],
    "arbre":   ["Ouvre le dossier des chantiers", "Cherche un fichier dedans"],
    "email":   ["Prépare la réponse", "Ouvre le message en entier"],
    "quote":   ["Envoie ce chiffrage au client", "Chiffre une variante"],
    "table":   ["Exporte ça en Excel", "Trie du plus élevé au plus bas"],
    "site":    ["Compare avec nos prix observés", "Retiens cette information"],
}

# Repli PAR EXPERT (agents/journal.py, frontend/lib/permissions.ts : EXPERTS).
PAR_EXPERT: dict[str, list[str]] = {
    "agent2": ["Sors le métré de ce plan",
               "Retrouve l'historique du client",
               "Prépare le chiffrage"],
    "agent3": ["Relis-moi toutes les consignes",
               "Montre-moi ce que tu sais faire"],
}

# Un tour où rien n'a abouti. Ce sont des RACCOURCIS, pas une excuse : on ne
# commente pas l'échec, on rouvre trois portes qui, elles, marchent.
ERREUR: list[str] = ["Cherche plutôt dans les marchés",
                     "Fais le point sur mes mails de la semaine",
                     "Montre-moi ce que tu sais faire"]

# Salutation, question de cadrage, tour sans aucun geste : les mêmes entrées
# que le menu éclair de la saisie, pour que les deux disent la même chose.
DEFAUT: list[str] = ["Fais le point sur mes mails de la semaine",
                     "Quels dossiers sont en attente",
                     "Analyse un DCE"]
