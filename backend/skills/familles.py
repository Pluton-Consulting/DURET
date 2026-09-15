"""
LES FAMILLES D'OUTILS — pour ne détailler au modèle que ce dont la demande a besoin.

Demande de Noa (15/09) : des consignes plus ciblées. Le prompt de chaque tour
portait ~74 000 caractères, dont ~35 000 de catalogue : les 76 outils décrits
en détail pour dire « bonjour » comme pour relancer une facture. Un modèle
rapide noyé sous des dizaines d'outils en confond, en oublie, et se contredit.

LE CHOIX N'EST PAS UNE LISTE DE MOTS-CLÉS : c'est le ROUTEUR (un modèle, déjà
appelé à chaque tour pour orienter la demande) qui dit quelles familles la
demande concerne. Ce fichier ne fait que dire quel outil appartient à quelle
famille — une donnée, pas une décision.

TROIS FILETS pour qu'un mauvais choix ne prive jamais le modèle d'un outil :
  · un INDEX de TOUS les outils (nom + une ligne) reste dans le prompt : le
    modèle sait qu'un outil existe même s'il n'est pas détaillé, et peut
    l'appeler — une erreur de paramètres lui rend alors son détail ;
  · un outil qu'aucune famille ne nomme (compétence validée en base, outil
    ajouté demain) est TOUJOURS détaillé : l'oubli d'une ligne ici n'enlève rien ;
  · sans choix du routeur (voie rapide, panne), tout le catalogue est détaillé,
    comme avant.

Le même fichier des deux côtés : un nom absent d'un projet (drive_* chez Duret,
nas_* chez Symbiose) est simplement ignoré.
"""
from __future__ import annotations

FAMILLES: dict[str, tuple[str, ...]] = {
    "mails": ("boites_mail", "check_mails", "lire_mails", "lire_mail", "lire_piece_jointe",
              "courrier_entrant", "triage_email_entrant", "resume_fil_email", "redaction_email",
              "deposer_brouillon", "envoyer_email", "preparer_envois", "apprendre_style_email",
              "profil_style_email", "apprendre_signature", "ma_signature", "supprimer_signature",
              "dossiers_mail"),
    "agenda": ("mon_agenda", "creneaux_agenda", "creer_rendez_vous"),
    "documents": ("creer_document", "ajouter_document", "terminer_document", "abandonner_document",
                  "produire_document", "reproduire_document", "enregistrer_trame", "utiliser_trame",
                  "mes_trames", "oublier_trame", "compte_rendu_reunion"),
    "stockage": ("ou_chercher", "inventaire_dossier",
                 "drive_arborescence", "drive_chercher", "drive_lister", "drive_ouvrir",
                 "drive_lire_lot", "drive_apercu", "drive_photos", "drive_deposer",
                 "drive_deposer_document",
                 "nas_arborescence", "nas_lister", "nas_ouvrir", "nas_lire", "nas_lire_lot",
                 "nas_chercher", "nas_apercu", "nas_photos", "nas_deposer", "nas_deposer_document"),
    "donnees": ("interroger_donnees", "liste_clients", "liste_fournisseurs", "fiche_client",
                "dossiers_en_attente", "prix_observes"),
    "facturation": ("suivre_facture", "factures_suivies", "relancer_factures", "enregistrer_relance",
                    "facture_reglee"),
    "web": ("chercher_web", "ouvrir_page", "naviguer"),
    "visuels": ("preparer_visuel", "tester_visuel", "generer_visuel", "modifier_visuel"),
    "taches": ("creer_tache_agent", "mes_taches", "suspendre_tache", "supprimer_tache"),
    "memoire": ("retenir", "oublier", "consignes_retenues", "connaissances_acquises",
                "enregistrer_procedure"),
    "administration": ("lancer_ingestion_documents", "statut_ingestion_documents",
                       "lancer_enrichissement", "statut_enrichissement"),
}

# Toujours détaillés : ce qui sert à presque toute demande, ou à se renseigner
# sur ses propres capacités.
TOUJOURS: tuple[str, ...] = ("rechercher_documents", "mes_droits", "mode_emploi", "proposer_plan")

# Ce que le routeur lit : une ligne par famille.
DESCRIPTIONS: dict[str, str] = {
    "mails": "lire, trier, répondre, envoyer ou préparer des mails ; signature, style d'écriture",
    "agenda": "agenda, rendez-vous, créneaux libres",
    "documents": "produire un Word/PDF/Excel, reprendre un document ou une trame, compte rendu",
    "stockage": "parcourir, chercher, ouvrir ou déposer des fichiers du stockage de l'entreprise, photos",
    "donnees": "clients, fournisseurs, devis, factures, chiffres, listes, totaux",
    "facturation": "suivre et relancer des factures impayées",
    "web": "information publique sur internet, ouvrir un site",
    "visuels": "créer ou retoucher une image, photomontage",
    "taches": "tâches planifiées ou récurrentes",
    "memoire": "retenir ou oublier une consigne, procédures, connaissances apprises",
    "administration": "importer ou enrichir la mémoire documentaire",
}


def familles_valides(brutes) -> list[str] | None:
    """Les familles reconnues dans ce que le routeur a rendu, ou None (= tout)."""
    if not isinstance(brutes, (list, tuple)):
        return None
    vues = [str(f).strip().lower() for f in brutes if str(f).strip().lower() in FAMILLES]
    return list(dict.fromkeys(vues)) or None


def a_detailler(noms, familles, deja_utilises=()) -> set[str]:
    """Les outils décrits EN DÉTAIL pour ce tour.

    `familles` None : tous. Une liste (même vide) : ceux des familles choisies, les TOUJOURS, ceux
    qu'aucune famille ne nomme (fail-safe), et ceux déjà utilisés dans le tour.
    """
    noms = list(noms)
    if familles is None:
        return set(noms)
    connus = {n for fam in FAMILLES.values() for n in fam}
    retenus = {n for f in familles for n in FAMILLES.get(f, ())}
    return {n for n in noms
            if n in retenus or n in TOUJOURS or n not in connus or n in set(deja_utilises)}


def liste_pour_le_routeur() -> str:
    return "\n".join(f'- "{f}" : {d}' for f, d in DESCRIPTIONS.items())
