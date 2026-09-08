"""
LES RELANCES DE FACTURATION — la chaîne des relances, en code, pour qu'elle
soit la même à chaque fois, dans le chat comme dans une tâche planifiée.

Demande de Noa du 08/09 : « prépare des skills de facturation ; les demandes
doivent s'appuyer sur ces skills ; si c'est du public, d'abord relancer le
maître d'œuvre, puis l'architecte, puis si le deuxième n'a pas répondu que ça
continue de relancer lui ; le même process même quand c'est planifié ».

POURQUOI DU CODE ET PAS UNE CONSIGNE. Une chaîne de relances est une règle de
gestion : qui reçoit la première relance, qui reçoit la suivante, à partir de
quand une facture est en retard, combien de jours entre deux relances. Confiée
au modèle, elle se réinvente à chaque tour — un maître d'œuvre relancé deux
fois, un architecte oublié, une relance envoyée trois jours après la
précédente. Ici, `destinataire_de` et `relances_dues` sont des FONCTIONS
PURES : le banc les exécute, et une tâche planifiée obtient exactement la
même décision qu'un « relance les factures » tapé dans le chat.

DEUX RÉGIMES :
  · PUBLIC (marché public, maîtrise d'œuvre) : relance 1 → le maître d'œuvre ;
    relance 2 → l'architecte ; relance 3 et suivantes → l'architecte encore,
    tant qu'il n'a pas répondu (Noa : « que ça continue de relancer lui ») ;
  · PRIVÉ : le client, à chaque relance, avec un ton qui monte (courtoise,
    ferme, mise en demeure annoncée avec proposition d'échéancier).

RIEN NE PART D'ICI. Le skill rend des CARTES (bloc `reponses_mail`,
éditables) ; chaque envoi passe par `envoyer_email` et son accord humain, et
`enregistrer_relance` note l'étape franchie. Le texte proposé est un gabarit
de gestion (référence, montant, échéance, à qui l'on écrit) : la personne le
relit sur la carte, le modèle peut l'adapter, les FAITS ne changent pas.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Optional

REGIMES = ("public", "prive")
INTERVALLE_JOURS = 7          # entre deux relances d'une même facture
ROLES = {"client": "le client", "maitre_oeuvre": "le maître d'œuvre", "architecte": "l'architecte"}
TONS = {1: "courtoise", 2: "ferme", 3: "mise en demeure"}


def _nu(texte) -> str:
    return str(texte or "").strip().lower()


def regime_de(brut) -> str:
    """« public », « marché public », « MOE » → public ; tout le reste → privé."""
    t = _nu(brut).replace("é", "e")
    if any(m in t for m in ("public", "marche", "moe", "maitrise", "collectiv", "mairie", "commune")):
        return "public"
    return "prive"


def role_de_relance(regime: str, etape: int) -> str:
    """Qui reçoit la relance numéro `etape` (1 = la première).

    Public : maître d'œuvre, puis l'architecte, puis l'architecte encore — la
    chaîne s'arrête sur le dernier maillon et y reste.
    """
    etape = max(int(etape or 1), 1)
    if regime == "public":
        return "maitre_oeuvre" if etape == 1 else "architecte"
    return "client"


def destinataire_de(regime: str, etape: int, contacts: dict) -> tuple[str, Optional[str]]:
    """(rôle, adresse) de la relance à envoyer. L'adresse est None quand le
    contact du rôle manque — le skill le DIT, il ne relance pas quelqu'un
    d'autre à la place (relancer le client d'un marché public à la place du
    maître d'œuvre serait une faute)."""
    role = role_de_relance(regime, etape)
    adresse = _nu((contacts or {}).get(role)) or None
    return role, adresse


def ton_de(etape: int) -> str:
    return TONS.get(max(int(etape or 1), 1), TONS[3])


def _date(valeur) -> Optional[date]:
    if isinstance(valeur, datetime):
        return valeur.date()
    if isinstance(valeur, date):
        return valeur
    try:
        from skills.lecture import lire_date
        d, _ = lire_date(valeur)
        return d.date() if isinstance(d, datetime) else d
    except Exception:  # noqa: BLE001 — sans lecteur, on tente l'ISO
        try:
            return date.fromisoformat(str(valeur)[:10])
        except Exception:  # noqa: BLE001
            return None


def _montant(valeur) -> str:
    try:
        m = float(valeur)
    except (TypeError, ValueError):
        return str(valeur or "").strip()
    return f"{m:,.2f} €".replace(",", " ").replace(".", ",")


def relance_due(facture: dict, aujourd_hui: Optional[date] = None,
                intervalle_jours: int = INTERVALLE_JOURS) -> tuple[bool, str]:
    """Faut-il relancer cette facture aujourd'hui ? (oui/non, raison).

    Oui si : elle n'est ni réglée ni close, son échéance est passée, et la
    dernière relance date d'au moins `intervalle_jours` (ou n'a jamais eu lieu).
    """
    aujourd_hui = aujourd_hui or date.today()
    statut = _nu(facture.get("statut") or "en_cours")
    if statut in ("reglee", "payee", "close", "cloturee"):
        return False, f"facture {statut}"
    echeance = _date(facture.get("echeance"))
    if echeance is None:
        return False, "échéance illisible"
    if echeance > aujourd_hui:
        return False, f"pas encore échue (échéance le {echeance:%d/%m/%Y})"
    derniere = facture.get("derniere_relance")
    if derniere:
        d = derniere.date() if isinstance(derniere, datetime) else _date(derniere)
        if d and (aujourd_hui - d).days < intervalle_jours:
            return False, (f"relancée il y a {(aujourd_hui - d).days} jour(s), "
                           f"prochaine possible le {d + timedelta(days=intervalle_jours):%d/%m/%Y}")
    return True, f"échue depuis {(aujourd_hui - echeance).days} jour(s)"


def relances_dues(factures: list, aujourd_hui: Optional[date] = None,
                  intervalle_jours: int = INTERVALLE_JOURS) -> tuple[list, list]:
    """(à relancer, écartées avec leur raison), du plus grand retard au plus petit."""
    aujourd_hui = aujourd_hui or date.today()
    a_relancer, ecartees = [], []
    for f in factures or []:
        due, raison = relance_due(f, aujourd_hui, intervalle_jours)
        (a_relancer if due else ecartees).append({**f, "raison": raison})
    a_relancer.sort(key=lambda f: (_date(f.get("echeance")) or aujourd_hui))
    return a_relancer, ecartees


def corps_de_relance(facture: dict, etape: int, role: str, entreprise: str,
                     signataire: str = "") -> tuple[str, str]:
    """(objet, corps) de la relance numéro `etape` à ce rôle. Gabarit de
    gestion : la référence, le montant, l'échéance et le retard — les faits.
    Le modèle peut adoucir ou préciser, il ne change pas les faits."""
    etape = max(int(etape or 1), 1)
    ref = str(facture.get("reference") or "").strip()
    client = str(facture.get("client") or "").strip()
    montant = _montant(facture.get("montant")) if facture.get("montant") not in (None, "") else ""
    echeance = _date(facture.get("echeance"))
    ech = f"{echeance:%d/%m/%Y}" if echeance else "(échéance non renseignée)"
    retard = (date.today() - echeance).days if echeance else 0
    chantier = str(facture.get("chantier") or facture.get("objet") or "").strip()
    qui = ROLES.get(role, role)
    titre = f"Relance {etape} — facture {ref}" + (f" — {client}" if client else "")
    if etape >= 3:
        titre = f"Dernière relance avant mise en demeure — facture {ref}" + (f" — {client}" if client else "")
    lignes = ["Bonjour,", ""]
    contexte = f"la facture {ref}" + (f" ({chantier})" if chantier else "") \
        + (f" d'un montant de {montant}" if montant else "") + f", échue le {ech}"
    if role == "maitre_oeuvre":
        lignes.append(f"Sauf erreur de notre part, {contexte} n'a pas encore été réglée"
                      + (f" ({retard} jours de retard)" if retard > 0 else "") + ".")
        lignes.append("En tant que maître d'œuvre du marché, pourriez-vous nous indiquer l'état "
                      "d'avancement du paiement, ou nous signaler ce qui le retient ?")
    elif role == "architecte":
        lignes.append(f"Nous revenons vers vous au sujet de {contexte}, restée sans règlement"
                      + (f" malgré notre relance précédente auprès du maître d'œuvre" if etape == 2
                         else " malgré nos relances précédentes") + ".")
        if etape >= 3:
            lignes.append("Sans retour de votre part sous huit jours, nous serons contraints d'engager "
                          "la procédure de mise en demeure prévue par le marché. Nous préférerions "
                          "l'éviter : un simple retour sur la date de règlement suffit.")
        else:
            lignes.append("Pourriez-vous intervenir pour que le règlement soit mis en paiement, "
                          "ou nous dire ce qui manque au dossier ?")
    else:
        if etape == 1:
            lignes.append(f"Sauf erreur de notre part, {contexte} n'a pas encore été réglée.")
            lignes.append("Il s'agit sans doute d'un oubli : nous vous remercions de bien vouloir "
                          "procéder au règlement, ou de nous indiquer la date prévue.")
        elif etape == 2:
            lignes.append(f"Malgré notre relance précédente, {contexte} reste impayée"
                          + (f" ({retard} jours de retard)" if retard > 0 else "") + ".")
            lignes.append("Nous vous demandons de régulariser la situation sous huit jours, ou de "
                          "nous contacter si un échéancier est nécessaire.")
        else:
            lignes.append(f"Malgré nos relances, {contexte} est toujours impayée"
                          + (f" ({retard} jours de retard)" if retard > 0 else "") + ".")
            lignes.append("Sans règlement ni proposition d'échéancier sous huit jours, nous nous "
                          "verrons contraints d'engager une procédure de recouvrement. Nous "
                          "restons disponibles pour trouver une solution avant cela.")
    lignes += ["", f"Nous restons à votre disposition ({qui} reste notre interlocuteur sur ce dossier).",
               "", "Cordialement,", signataire or entreprise]
    return titre, "\n".join(lignes)


def maintenant_utc() -> datetime:
    return datetime.now(timezone.utc)
