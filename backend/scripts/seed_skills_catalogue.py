"""
Seed du CATALOGUE DE SKILLS génériques — Duret & Sols (travaux de sols / BTP).

Objectif : « roder les agents » en dotant l'Agent 1 (administratif / suivi de chantiers)
et l'Agent 2 (appels d'offres / chiffrage / analyse de plans) d'un catalogue de capacités
métier, au format attendu par le système (`skills.code` = Python exposant `run(data)->dict`,
statut 'draft' → à valider par la direction).

Ces skills sont des SQUELETTES génériques : ils documentent entrées/sorties et ne renvoient
jamais de valeur inventée (champs manquants => "[À COMPLÉTER]"). La logique métier réelle est
à implémenter progressivement (ou générée par l'Agent 3), puis validée humainement.

Idempotent : réexécutable sans doublon (ON CONFLICT (name) DO NOTHING).
Lancement : docker compose exec backend sh -c "PYTHONPATH=. python scripts/seed_skills_catalogue.py"
"""
import asyncio

from database.connection import init_db, get_db


# ── Générateur de squelette de skill (DRY) ────────────────────────────────
def scaffold(name: str, requis: list[str], resultat: list[str]) -> str:
    resultat_lines = "\n".join(f'            {k!r}: "[À COMPLÉTER]",' for k in resultat)
    return (
        "def run(data: dict) -> dict:\n"
        f'    """Skill Duret & Sols « {name} » : squelette générique.\n'
        f"    Entrées attendues : {requis}.\n"
        '    Règle: ne JAMAIS inventer. Toute donnée absente => "[À COMPLÉTER]".\n'
        '    La logique métier réelle est décrite dans prompt_template."""\n'
        f"    requis = {requis!r}\n"
        "    manquants = [k for k in requis if not data.get(k)]\n"
        "    return {\n"
        f'        "skill": {name!r},\n'
        '        "status": "a_completer" if manquants else "pret",\n'
        '        "champs_manquants": manquants,\n'
        "        \"resultat\": {\n"
        f"{resultat_lines}\n"
        "        },\n"
        '        "note": "Squelette générique : implémenter la logique métier (voir prompt_template).",\n'
        "    }\n"
    )


# ── Catalogue ─────────────────────────────────────────────────────────────
# Skills NATIFS (exécutés dans le backend — voir mail/skills.py).
NATIFS = [
    ("triage_email_entrant",
     "Classe et priorise un message reçu (catégorie, urgence, action suggérée). N'exécute aucune action."),
    ("redaction_email",
     "Rédige un BROUILLON de message dans le style de l'expéditeur, pour 11 types "
     "(réponse, relance devis, relance impayé, envoi de devis, réclamation, information "
     "chantier, confirmation de rendez-vous, demande d'informations, remerciement, refus, "
     "interne). N'envoie jamais."),
    ("resume_fil_email",
     "Résume un échange de mails et en extrait les demandes, engagements et points en attente."),
    ("profil_style_email",
     "(Re)calcule le profil de style rédactionnel d'une boîte à partir de ses messages envoyés."),
]

# (name, agent, category, description, requis[], resultat[], prompt_template)
CATALOGUE = [
    # ===================== AGENT 1 — Administratif / Suivi de chantiers =====================
    ("recherche_dossier_chantier", "agent1", "chantier",
     "Retrouve un dossier chantier et synthétise son état (documents, commandes, factures, réserves).",
     ["chantier"], ["chantier", "documents_lies", "etat_avancement", "points_ouverts"],
     "Rassemble tout ce qui concerne un chantier depuis la mémoire (appels d'offres, devis, commandes, "
     "factures, réserves, docs juridiques). Restitue une vue synthétique par chantier."),

    ("suivi_commandes", "agent1", "commandes",
     "Fait le point sur les commandes d'un chantier (commandé / livré / facturé).",
     ["chantier"], ["commandes", "en_attente_livraison", "a_facturer"],
     "Liste les commandes du chantier avec leur statut. Signale les livraisons ou factures manquantes."),

    ("rapprochement_commande_livraison_facture", "agent1", "commandes",
     "Croise commandes, bons de livraison et factures pour détecter les écarts.",
     ["chantier"], ["rapprochements", "ecarts_detectes", "a_verifier"],
     "Rapproche commande ↔ BL ↔ facture. Remonte les écarts (quantité, prix, manquants). "
     "Ne conclut pas seul : signale les écarts à vérifier."),

    ("suivi_reglements_fournisseurs", "agent1", "fournisseurs",
     "Suit les règlements fournisseurs (payés / à payer / échéances).",
     ["fournisseur"], ["reglements", "en_attente", "echeances"],
     "Fait le point sur les règlements d'un fournisseur. Ne calcule pas de solde si des montants manquent."),

    ("suivi_reserves", "agent1", "chantier",
     "Suit les réserves à lever et leurs échéances (15 jours / 1 mois).",
     ["chantier"], ["reserves", "echeances", "en_retard"],
     "Liste les réserves d'un chantier avec leur délai de levée. Alerte sur celles proches ou dépassées."),

    ("suivi_echeances", "agent1", "administratif",
     "Remonte les échéances et actions en attente (convocations, réunions d'expertise, délais).",
     ["chantier"], ["echeances", "actions_en_attente"],
     "Restitue les échéances à venir (convocations, expertises, délais contractuels) et les actions non suivies."),

    ("suivi_dossier_juridique", "agent1", "juridique",
     "Fait le point sur un dossier contentieux / juridique.",
     ["dossier"], ["etat", "historique", "prochaines_actions", "pieces_manquantes"],
     "Synthétise l'état d'un dossier juridique (ancienneté, échanges, actions). "
     "⚠ Aucune action engageante sans validation humaine."),

    ("recherche_document", "agent1", "administratif",
     "Recherche transverse d'un document (facture, CCTP, CCAP, convocation, BL, devis…).",
     ["requete"], ["resultats", "sources"],
     "Recherche sémantique dans la mémoire d'entreprise, tous types de documents. "
     "Restitue les extraits pertinents avec leur source. Rien d'inventé si absent."),

    ("redaction_reponse_mail", "agent1", "administratif",
     "Rédige un BROUILLON de réponse à un mail (validation humaine obligatoire avant envoi).",
     ["objet", "corps"], ["brouillon_reponse", "elements_a_verifier"],
     "Rédige un brouillon professionnel en français. ⚠ VALIDATION HUMAINE OBLIGATOIRE avant envoi. "
     "N'invente ni montant ni engagement : [À COMPLÉTER]."),

    ("preparation_facture_situation", "agent1", "administratif",
     "Rassemble les éléments pour préparer une facture ou une situation de travaux.",
     ["chantier"], ["elements", "avancement", "manque"],
     "Agrège marché, avancement et pièces pour préparer une situation. Ne CHIFFRE pas seul : "
     "prépare les éléments, la facturation reste validée par un humain."),

    ("facturation_sous_traitant", "agent1", "fournisseurs",
     "Suit et prépare la facturation des sous-traitants.",
     ["chantier"], ["sous_traitants", "a_facturer", "regles"],
     "Fait le point sur la facturation des sous-traitants d'un chantier. Signale ce qui reste à traiter."),

    ("vision_chantier", "agent1", "chantier",
     "Tableau de bord d'un chantier : actions en attente, commandes, docs manquants, réserves, factures, règlements, échéances.",
     ["chantier"], ["actions_en_attente", "commandes", "documents_manquants", "reserves",
                     "factures", "reglements", "echeances", "juridique"],
     "Produit une vue claire par chantier avec tous les points de suivi. Marque [À COMPLÉTER] "
     "tout élément absent de la mémoire, n'invente aucun statut."),

    # ===================== AGENT 2 — Appels d'offres / Chiffrage / Études =====================
    ("analyse_cctp", "agent2", "appels_offres",
     "Analyse un CCTP : prestations demandées, contraintes techniques, exclusions.",
     ["fichier"], ["prestations", "contraintes_techniques", "exclusions", "points_vigilance"],
     "Lis le CCTP (par lot) et extrais prestations, contraintes, exclusions et subtilités. "
     "Signale les points pouvant impacter le prix ou la marge. Ne devine pas : [À COMPLÉTER] si non lisible."),

    ("analyse_ccap", "agent2", "appels_offres",
     "Analyse un CCAP : subtilités contractuelles, obligations particulières, pénalités.",
     ["fichier"], ["clauses_cles", "obligations", "penalites", "risques"],
     "Extrais du CCAP les clauses à risque (délais, pénalités, retenues, obligations). "
     "Mets en avant ce qui peut créer un risque financier."),

    ("analyse_reglement_consultation", "agent2", "appels_offres",
     "Analyse un règlement de consultation : dates, pièces à fournir, critères de jugement.",
     ["fichier"], ["dates_echeances", "pieces_a_fournir", "criteres", "variantes_options"],
     "Extrais dates limites, documents de candidature à fournir, critères et variantes/options autorisées."),

    ("analyse_dpgf", "agent2", "chiffrage",
     "Extrait les postes et quantités d'une DPGF.",
     ["fichier"], ["postes", "quantites", "unites", "postes_incertains"],
     "Extrais la décomposition (postes, quantités, unités) de la DPGF. "
     "Marque [À COMPLÉTER] toute quantité non lisible plutôt que de l'inventer."),

    ("synthese_appel_offre", "agent2", "appels_offres",
     "Produit une synthèse exploitable d'un appel d'offres (avant chiffrage).",
     ["dossier"], ["prestations", "echeances", "documents_a_fournir", "variantes", "exclusions",
                   "contraintes_dechets", "obligations", "points_vigilance", "risques_prix_marge"],
     "À partir des pièces (CCTP, CCAP, RC, DPGF, lot 0, plans), produis une synthèse : prestations, "
     "échéances, variantes, exclusions, contraintes déchets, obligations, points de vigilance et risques "
     "sur le prix/la marge. ⚠ Ne remplace PAS la validation de Benoît : tu prépares et fiabilises la lecture."),

    ("analyse_plan", "agent2", "plans",
     "Extrait les informations d'un plan (locaux, revêtements, surfaces, plinthes, contraintes).",
     ["fichier"], ["locaux_zones", "revetements", "surfaces_m2", "lineaires_plinthes_ml", "contraintes"],
     "Analyse le plan (vision). Repère locaux, revêtements de sol, surfaces/cotes lisibles, linéaires "
     "de plinthes, contraintes. « non lisible » si une mesure n'est pas exploitable."),

    ("calcul_metres", "agent2", "chiffrage",
     "Aide au métré : surfaces, volumes, plinthes à partir d'un plan ou de cotes.",
     ["cotes"], ["surfaces", "volumes", "plinthes_ml", "hypotheses", "total"],
     "Calcule surfaces / volumes / linéaires de plinthes à partir des cotes fournies. Explicite chaque "
     "hypothèse. Si des cotes manquent, ne calcule pas le total : [À COMPLÉTER]."),

    ("rapprochement_plan_dpgf", "agent2", "chiffrage",
     "Contrôle la cohérence des quantités entre plans, DPGF et CCTP.",
     ["plan", "dpgf"], ["ecarts", "quantites_confirmees", "a_verifier"],
     "Rapproche les quantités du plan avec la DPGF et le CCTP. Remonte les écarts et les points à vérifier. "
     "Ne tranche pas seul : signale."),

    ("couts_dechets_soged", "agent2", "chiffrage",
     "Estime les coûts SOGED selon les typologies et quantités de déchets.",
     ["dechets"], ["typologies", "quantites", "cout_estime", "hypotheses"],
     "Prépare une estimation SOGED (gestion des déchets) selon typologies et quantités. Estimation "
     "indicative, à valider. N'invente pas de tonnage."),

    ("obligations_reemploi_reinsertion", "agent2", "appels_offres",
     "Repère les obligations de réemploi et de réinsertion professionnelle dans un dossier.",
     ["dossier"], ["obligations_reemploi", "obligations_reinsertion", "references_clauses"],
     "Identifie dans les pièces les obligations de réemploi (matériaux) et de réinsertion, avec la clause source."),

    ("recherche_dossier_similaire", "agent2", "etudes",
     "Recherche des dossiers / devis similaires pour servir de référence au chiffrage.",
     ["description"], ["dossiers_similaires", "postes_recurrents", "prix_reference"],
     "Recherche RAG de dossiers comparables (mêmes prestations/typologies) pour aider Benoît à chiffrer plus vite."),

    ("base_prechiffrage", "agent2", "chiffrage",
     "Prépare une base de PRÉ-DEVIS (jamais un chiffrage final, validation obligatoire de Benoît).",
     ["postes"], ["lignes_prechiffrage", "hypotheses", "a_valider"],
     "Assemble une base de pré-chiffrage à partir des postes (DPGF/métrés) + prix de référence + règles "
     "internes. ⚠⚠ NE VALIDE JAMAIS un chiffrage : la décision finale et les prix restent 100% humains (Benoît)."),

    ("maj_documents_candidature", "agent2", "appels_offres",
     "Met à jour les documents de candidature à partir des trames existantes.",
     ["appel_offre"], ["documents_a_mettre_a_jour", "trames_utilisees", "manque"],
     "Repère quels documents de candidature actualiser pour un appel d'offres, à partir des trames et "
     "éléments réutilisables. Signale les pièces manquantes, ne fabrique pas d'attestation."),
]


async def main() -> None:
    await init_db()
    async with get_db() as conn:
        # Colonnes d'organisation / gouvernance (idempotent)
        await conn.execute("ALTER TABLE skills ADD COLUMN IF NOT EXISTS agent VARCHAR(20)")
        await conn.execute("ALTER TABLE skills ADD COLUMN IF NOT EXISTS category VARCHAR(50)")
        await conn.execute("ALTER TABLE skills ADD COLUMN IF NOT EXISTS enabled BOOLEAN NOT NULL DEFAULT true")

        inserted = 0
        for name, agent, category, description, requis, resultat, prompt in CATALOGUE:
            code = scaffold(name, requis, resultat)
            status = await conn.execute(
                """INSERT INTO skills
                       (name, description, code, prompt_template, status, created_by, agent, category)
                   VALUES ($1, $2, $3, $4, 'draft', 'system', $5, $6)
                   ON CONFLICT (name) DO NOTHING""",
                name, description, code, prompt, agent, category,
            )
            if status.endswith(" 1"):
                inserted += 1

        # Skills NATIFS : implémentés dans le backend (mail/skills.py), pas en bac
        # à sable. Ils sont donc directement 'stable' — leur code est livré avec
        # l'application, il n'y a rien à générer ni à valider. Les référencer ici
        # les rend visibles et surtout DÉSACTIVABLES depuis l'interface.
        for name, description in NATIFS:
            status = await conn.execute(
                """INSERT INTO skills
                       (name, description, code, prompt_template, status, created_by, agent, category)
                   VALUES ($1, $2, '', '', 'stable', 'system', 'agent1', 'mail')
                   ON CONFLICT (name) DO UPDATE
                       SET description = EXCLUDED.description, status = 'stable'""",
                name, description,
            )
            if status.endswith(" 1"):
                inserted += 1

        total = await conn.fetchval("SELECT COUNT(*) FROM skills")
        by_agent = await conn.fetch(
            "SELECT agent, category, COUNT(*) n FROM skills GROUP BY agent, category ORDER BY agent, category"
        )

    print(f"Skills insérées cette exécution : {inserted}")
    print(f"Total skills en base : {total}")
    print("Répartition :")
    for r in by_agent:
        print(f"  {r['agent'] or '—':8} / {r['category'] or '—':14} : {r['n']}")


if __name__ == "__main__":
    asyncio.run(main())
