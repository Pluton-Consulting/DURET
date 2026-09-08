"""
Skills de FACTURATION — suivre une facture, relancer selon la chaîne, noter la
relance, marquer réglée. Socle, identique des deux côtés.

Demande de Noa du 08/09 : « prépare des skills de facturation ; les demandes
doivent s'appuyer sur ces skills ; public : maître d'œuvre, puis architecte,
puis l'architecte encore ; le même process même quand c'est planifié ».

La chaîne vit dans `facturation/relances.py` (fonctions pures). Ici : la
table `factures_suivies` (migration 037), les cartes de relance (bloc
`reponses_mail`, garanti), et rien qui parte tout seul — chaque envoi passe
par `envoyer_email` et son accord, puis `enregistrer_relance` note l'étape.
Une tâche planifiée « tous les 7 jours à 9h : relance les factures impayées »
appelle `relancer_factures` : même chaîne, mêmes cartes, mêmes accords
(tableau de bord → À valider).

Une facture ne se SUPPRIME pas d'ici : elle se marque réglée ou close.
"""
from __future__ import annotations

import json
import logging
from datetime import date

from database.connection import get_db
from facturation.relances import (INTERVALLE_JOURS, ROLES, corps_de_relance, destinataire_de,
                                  maintenant_utc, regime_de, relances_dues, ton_de)
from skills.registre import Declaration

logger = logging.getLogger("symbiose.skills.facturation")
MAX_FACTURES = 200


class FactureInvalide(Exception):
    """Une demande incomplète : le message dit ce qui manque."""


def _jsonb(v):
    if isinstance(v, str):
        try:
            return json.loads(v)
        except Exception:  # noqa: BLE001
            return {}
    return dict(v or {})


def _ligne(l) -> dict:
    d = dict(l)
    d["contacts"] = _jsonb(d.get("contacts"))
    for k in ("echeance", "derniere_relance", "created_at", "updated_at"):
        if d.get(k) is not None and hasattr(d[k], "isoformat"):
            d[k] = d[k].isoformat()
    d["id"] = str(d.get("id"))
    if d.get("montant") is not None:
        d["montant"] = float(d["montant"])
    return d


async def _mes_factures(user, statuts=("en_cours",), reference: str | None = None) -> list:
    async with get_db() as conn:
        if reference:
            lignes = await conn.fetch(
                "SELECT * FROM factures_suivies WHERE user_id = $1::uuid AND reference ILIKE $2 "
                "ORDER BY echeance NULLS LAST LIMIT $3", str(user.id), f"%{reference.strip()}%", MAX_FACTURES)
        else:
            lignes = await conn.fetch(
                "SELECT * FROM factures_suivies WHERE user_id = $1::uuid AND statut = ANY($2::text[]) "
                "ORDER BY echeance NULLS LAST LIMIT $3", str(user.id), list(statuts), MAX_FACTURES)
    return [_ligne(l) for l in lignes]


def _entreprise() -> str:
    try:
        from emails.marque import MARQUE
        return str(MARQUE.get("nom") or "L'entreprise")
    except Exception:  # noqa: BLE001 — sans marque, un nom neutre
        return "L'entreprise"


async def suivre_facture(data: dict, user) -> dict:
    """Enregistre une facture à suivre, avec son régime et ses contacts."""
    reference = str(data.get("reference") or data.get("facture") or data.get("numero") or "").strip()
    client = str(data.get("client") or "").strip()
    echeance_brute = data.get("echeance") or data.get("date_echeance")
    if not reference or not client or not echeance_brute:
        raise FactureInvalide("Il faut la référence de la facture, le client et son échéance "
                              "(reference, client, echeance).")
    from facturation.relances import _date
    echeance = _date(echeance_brute)
    if echeance is None:
        raise FactureInvalide(f"Échéance illisible : « {echeance_brute} » (attendu : une date, ex. 15/09/2026).")
    regime = regime_de(data.get("regime") or data.get("type") or "")
    contacts = {k: str(data.get(k) or data.get(f"email_{k}") or "").strip().lower() or None
                for k in ("client", "maitre_oeuvre", "architecte")}
    if data.get("email_client") and not contacts["client"]:
        contacts["client"] = str(data["email_client"]).strip().lower()
    # `client` est le NOM du client ; son ADRESSE vient d'`email_client` (ou `client`
    # si c'est manifestement une adresse).
    if contacts["client"] and "@" not in contacts["client"]:
        contacts["client"] = str(data.get("email_client") or "").strip().lower() or None
    montant = data.get("montant")
    try:
        montant = float(str(montant).replace("€", "").replace(" ", "").replace(",", ".")) if montant not in (None, "") else None
    except ValueError:
        montant = None
    async with get_db() as conn:
        ligne = await conn.fetchrow(
            """INSERT INTO factures_suivies
                   (user_id, reference, client, chantier, montant, echeance, regime, contacts, notes)
               VALUES ($1::uuid, $2, $3, $4, $5, $6, $7, $8::jsonb, $9)
               ON CONFLICT (user_id, reference) DO UPDATE
                   SET client = EXCLUDED.client, chantier = EXCLUDED.chantier,
                       montant = COALESCE(EXCLUDED.montant, factures_suivies.montant),
                       echeance = EXCLUDED.echeance, regime = EXCLUDED.regime,
                       contacts = EXCLUDED.contacts, notes = COALESCE(EXCLUDED.notes, factures_suivies.notes),
                       updated_at = NOW()
               RETURNING *""",
            str(user.id), reference[:120], client[:200],
            str(data.get("chantier") or data.get("objet") or "").strip()[:200] or None,
            montant, echeance, regime, json.dumps(contacts, ensure_ascii=False),
            str(data.get("notes") or "").strip()[:1000] or None)
    f = _ligne(ligne)
    manque = [ROLES[r] for r in (("maitre_oeuvre", "architecte") if regime == "public" else ("client",))
              if not contacts.get(r)]
    role1, _ = destinataire_de(regime, 1, contacts)
    return {
        "facture": f,
        "message_final": (f"Facture {reference} de {client} suivie (régime {regime}, échéance "
                          f"{echeance:%d/%m/%Y}). Première relance : {ROLES[role1]}."
                          + (f" Il manque l'adresse de : {', '.join(manque)}." if manque else "")),
        "a_faire": ("Dis en une phrase ce qui est suivi et qui sera relancé en premier. "
                    + ("Demande les adresses manquantes AVANT de relancer." if manque else
                       "Pour relancer maintenant : `relancer_factures` avec cette référence.")),
    }


async def factures_suivies(data: dict, user) -> dict:
    """Les factures suivies, avec leur étape et ce qui est dû."""
    tout = str(data.get("tout") or data.get("toutes") or "").strip().lower() in ("1", "true", "oui")
    factures = await _mes_factures(user, ("en_cours", "reglee", "close") if tout else ("en_cours",))
    if not factures:
        return {"factures": [], "nombre": 0,
                "message_final": "Aucune facture suivie" + ("" if tout else " en cours") + ".",
                "a_faire": "Dis-le, et propose d'en suivre une (`suivre_facture` : référence, client, échéance, régime, contacts)."}
    dues, ecartees = relances_dues(factures, date.today())
    dues_refs = {f["id"] for f in dues}
    lignes = []
    for f in factures:
        role, adresse = destinataire_de(f["regime"], int(f.get("etape") or 0) + 1, f["contacts"])
        etat = ("à relancer" if f["id"] in dues_refs else
                next((e["raison"] for e in ecartees if e["id"] == f["id"]), f.get("statut") or ""))
        lignes.append([f["reference"], f["client"], f["regime"],
                       (f["echeance"] or "")[:10], f"{int(f.get('etape') or 0)}",
                       f"{ROLES[role]}" + ("" if adresse else " (adresse manquante)"), etat])
    return {
        "factures": factures, "nombre": len(factures), "a_relancer": len(dues),
        "bloc_ui": {"type": "table", "titre": "Factures suivies",
                    "columns": ["Référence", "Client", "Régime", "Échéance", "Relances faites",
                                "Prochaine relance à", "État"],
                    "rows": lignes},
        "bloc_garanti": True,
        "message_final": f"{len(factures)} facture(s) suivie(s), {len(dues)} à relancer aujourd'hui.",
        "a_faire": ("Le tableau s'affiche automatiquement. Pour relancer celles qui sont dues : "
                    "`relancer_factures`. Pour en clore une : `facture_reglee`."),
    }


async def relancer_factures(data: dict, user) -> dict:
    """Les relances dues aujourd'hui, en cartes — chacune au bon destinataire de la chaîne."""
    reference = str(data.get("reference") or data.get("facture") or "").strip() or None
    forcer = str(data.get("forcer") or "").strip().lower() in ("1", "true", "oui")
    factures = await _mes_factures(user, ("en_cours",), reference)
    if not factures:
        return {"cartes": [], "nombre": 0,
                "message_final": ("Aucune facture suivie" + (f" pour « {reference} »" if reference else " en cours") + "."),
                "a_faire": "Dis-le. Pour suivre une facture : `suivre_facture` (référence, client, échéance, régime, contacts)."}
    aujourd_hui = date.today()
    if forcer:
        dues, ecartees = [dict(f, raison="relance demandée explicitement") for f in factures], []
    else:
        dues, ecartees = relances_dues(factures, aujourd_hui, INTERVALLE_JOURS)
    entreprise = _entreprise()
    signataire = str(getattr(user, "name", "") or "") or entreprise
    cartes, sans_adresse = [], []
    for f in dues:
        etape = int(f.get("etape") or 0) + 1
        role, adresse = destinataire_de(f["regime"], etape, f["contacts"])
        if not adresse:
            sans_adresse.append(f"{f['reference']} ({ROLES[role]})")
            continue
        objet, corps = corps_de_relance(f, etape, role, entreprise, signataire)
        cartes.append({"de": adresse, "objet": objet, "reponse": corps,
                       "nom": f"{f['client']} — {ROLES[role]}",
                       "synthese": (f"Facture {f['reference']}, relance {etape} ({ton_de(etape)}) à "
                                    f"{ROLES[role]} — {f['raison']}. Régime {f['regime']}.")})
    sortie = {
        "nombre": len(cartes), "cartes": cartes,
        "ecartees": [{"reference": e["reference"], "raison": e["raison"]} for e in ecartees],
        "sans_adresse": sans_adresse,
        "relances": [{"reference": f["reference"], "etape": int(f.get("etape") or 0) + 1,
                      "role": destinataire_de(f["regime"], int(f.get("etape") or 0) + 1, f["contacts"])[0]}
                     for f in dues],
    }
    if cartes:
        sortie["bloc_ui"] = {"type": "reponses_mail", "titre": "Relances de facturation à envoyer",
                             "reponses": cartes}
        sortie["bloc_garanti"] = True
    sortie["message_final"] = (f"{len(cartes)} relance(s) à envoyer"
                               + (f", {len(ecartees)} facture(s) non dues" if ecartees else "")
                               + (f", sans adresse : {', '.join(sans_adresse)}" if sans_adresse else "") + ".")
    sortie["a_faire"] = (
        "Les cartes sont DÉJÀ affichées (éditables) : ne les recopie pas. Chaque envoi passe par "
        "`envoyer_email` (destinataire, objet, corps de la carte) et son accord humain ; APRÈS "
        "chaque envoi réussi, appelle `enregistrer_relance` avec la référence de la facture pour "
        "noter l'étape — sinon la même relance repartira. Le destinataire de chaque carte est "
        "IMPOSÉ par la chaîne (public : maître d'œuvre, puis architecte, puis l'architecte "
        "encore) : ne le change pas. Dis en une phrase combien de relances et à qui."
        + (" Demande les adresses manquantes avant de relancer les factures citées." if sans_adresse else ""))
    return sortie


async def enregistrer_relance(data: dict, user) -> dict:
    """Note qu'une relance est PARTIE : l'étape avance, la date est posée."""
    reference = str(data.get("reference") or data.get("facture") or "").strip()
    if not reference:
        raise FactureInvalide("Donne la référence de la facture relancée.")
    async with get_db() as conn:
        ligne = await conn.fetchrow(
            """UPDATE factures_suivies
               SET etape = etape + 1, derniere_relance = $3, updated_at = NOW()
               WHERE user_id = $1::uuid AND reference = $2 AND statut = 'en_cours'
               RETURNING *""", str(user.id), reference, maintenant_utc())
    if ligne is None:
        raise FactureInvalide(f"Aucune facture en cours sous la référence « {reference} ». "
                              "Appelle `factures_suivies` pour la liste exacte.")
    f = _ligne(ligne)
    role, _ = destinataire_de(f["regime"], int(f["etape"]) + 1, f["contacts"])
    return {"facture": f,
            "message_final": (f"Relance {f['etape']} notée pour la facture {reference}. "
                              f"La prochaine, dans {INTERVALLE_JOURS} jours au plus tôt, ira à {ROLES[role]}."),
            "a_faire": "Dis-le en une phrase."}


async def facture_reglee(data: dict, user) -> dict:
    """La facture est réglée (ou close) : elle sort des relances, rien n'est supprimé."""
    reference = str(data.get("reference") or data.get("facture") or "").strip()
    if not reference:
        raise FactureInvalide("Donne la référence de la facture réglée.")
    statut = "close" if str(data.get("statut") or "").strip().lower() == "close" else "reglee"
    async with get_db() as conn:
        ligne = await conn.fetchrow(
            """UPDATE factures_suivies SET statut = $3, updated_at = NOW()
               WHERE user_id = $1::uuid AND reference = $2 RETURNING *""",
            str(user.id), reference, statut)
    if ligne is None:
        raise FactureInvalide(f"Aucune facture suivie sous la référence « {reference} ».")
    return {"facture": _ligne(ligne),
            "message_final": f"Facture {reference} marquée {statut} : plus aucune relance ne partira.",
            "a_faire": "Dis-le en une phrase."}


SKILLS = {
    "suivre_facture": Declaration(
        fonction=suivre_facture,
        description=(
            "MET UNE FACTURE SOUS SUIVI de relances. `reference`, `client` (nom), "
            "`echeance` (date) obligatoires ; `montant`, `chantier` ; `regime` : « public » "
            "(marché public : relance 1 au maître d'œuvre, puis l'architecte, puis l'architecte "
            "encore) ou « prive » (le client) ; contacts : `email_client`, `maitre_oeuvre`, "
            "`architecte` (adresses). Une référence déjà suivie est mise à jour. À appeler dès "
            "qu'on parle de suivre, surveiller ou relancer une facture précise."),
        requis=["reference", "client", "echeance"],
        optionnels=["montant", "chantier", "regime", "email_client", "maitre_oeuvre", "architecte", "notes"],
        effet="ecriture_interne", libelle="je mets la facture sous suivi"),
    "factures_suivies": Declaration(
        fonction=factures_suivies,
        description=("LISTE les factures suivies : régime, échéance, relances faites, qui recevra "
                     "la prochaine, et si une relance est due aujourd'hui. `tout: true` pour "
                     "voir aussi les réglées."),
        requis=[], optionnels=["tout"], effet="lecture", libelle="je regarde les factures suivies"),
    "relancer_factures": Declaration(
        fonction=relancer_factures,
        description=(
            "PRÉPARE les relances de facturation DUES (échues, non réglées, dernière relance "
            "de plus de 7 jours) en CARTES éditables, chacune au destinataire imposé par la "
            "chaîne du régime (public : maître d'œuvre → architecte → architecte ; privé : le "
            "client), ton qui monte à chaque étape. Rien ne part : chaque carte s'envoie par "
            "`envoyer_email` (accord humain), puis `enregistrer_relance` note l'étape. "
            "`reference` pour une seule facture ; `forcer: true` pour relancer sans attendre "
            "le délai. C'est CE geste qu'une tâche planifiée « tous les 7 jours, relance les "
            "factures impayées » appelle : même chaîne, mêmes accords."),
        requis=[], optionnels=["reference", "forcer"], effet="lecture",
        libelle="je prépare les relances de facturation"),
    "enregistrer_relance": Declaration(
        fonction=enregistrer_relance,
        description=("NOTE qu'une relance est PARTIE pour cette facture (`reference`) : l'étape "
                     "avance, la date est posée. À appeler juste après chaque `envoyer_email` "
                     "d'une relance réussi — sinon la même relance repartira."),
        requis=["reference"], optionnels=[], effet="ecriture_interne",
        libelle="je note la relance envoyée"),
    "facture_reglee": Declaration(
        fonction=facture_reglee,
        description=("MARQUE une facture suivie comme RÉGLÉE (`reference`) : elle sort des "
                     "relances. Rien n'est supprimé. `statut: close` pour l'abandonner sans paiement."),
        requis=["reference"], optionnels=["statut"], effet="ecriture_interne",
        libelle="je marque la facture réglée"),
}
