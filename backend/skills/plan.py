"""
LE PLAN D'UN GROS TRAVAIL — montré, validé, puis exécuté d'un seul tenant.

POURQUOI CE GESTE EXISTE.

Une demande qui tient en une phrase peut occuper vingt minutes et quarante
actions : « le client m'envoie ce plan, analyse-le, retrouve son historique et
prépare-moi un pré-devis avec le mail de réponse ». Jusqu'ici, l'assistant
partait droit devant. Deux ennuis, toujours les mêmes :

  * on ne savait pas ce qu'il avait compris AVANT qu'il ait tout fait. Une
    demande mal lue coûtait alors le travail entier, et se corrigeait après ;
  * l'écran ne montrait qu'une ligne d'activité qui se remplace, puis le
    résultat. Entre les deux, vingt minutes d'opacité.

On remet donc l'accord humain là où il vaut quelque chose : AVANT le travail,
sur le plan, pas après sur le résultat. L'assistant annonce ce qu'il compte
faire, en étapes ; la personne lit, approuve ou refuse ; et ce n'est qu'ensuite
que le travail part, d'un seul tenant, pour rendre UNE réponse. Le détail de ce
qui se passe pendant reste visible dans le journal d'activité (« je lis la
fiche du client », « je produis le document ») : le plan dit l'intention, le
journal dit l'avancement, la réponse dit le résultat.

CE QUE CE GESTE NE FAIT PAS. Il n'exécute rien, ne calcule rien, n'appelle
personne. Il n'écrit qu'un plan à l'écran. Son effet est pourtant `externe` :
non parce qu'il sort de l'entreprise, mais parce que c'est la SEULE porte du
système qui suspend le graphe et demande un accord. C'est cette porte que l'on
emprunte pour faire trancher un humain, et l'accord porte ici sur le plan
lui-même, dont l'empreinte est vérifiée comme pour toute action validée : ce
qui est approuvé est exactement ce qui sera exécuté.
"""
from __future__ import annotations

import logging

logger = logging.getLogger("pluton.skills.plan")

# UN PLAN QUI NE TIENT PAS À L'ÉCRAN N'EST PAS UN PLAN, C'EST UNE LISTE DE
# COURSES. On borne à ce qu'un dirigeant lit avant de cliquer : au-delà de dix
# étapes, la personne approuve sans lire, et l'accord ne vaut plus rien.
MAX_ETAPES = 10
MAX_TITRE_ETAPE = 120


def _etapes(brut) -> list:
    """Les étapes, quelle que soit la façon dont le modèle les a écrites.

    Il les envoie tantôt en liste de chaînes, tantôt en liste d'objets
    `{titre: ...}`, tantôt en un seul texte à puces. Les trois se valent : ce
    qui compte est qu'un humain lise des phrases, pas que le modèle ait deviné
    la forme attendue.
    """
    if isinstance(brut, str):
        import re
        brut = [l.strip(" -*•\t") for l in re.split(r"[\n;]", brut)]
    if not isinstance(brut, (list, tuple)):
        return []
    sorties = []
    for e in brut:
        titre = (e.get("titre") or e.get("etape") or e.get("libelle") or ""
                 if isinstance(e, dict) else str(e or ""))
        titre = str(titre).strip()
        if titre:
            sorties.append(titre[:MAX_TITRE_ETAPE])
    return sorties[:MAX_ETAPES]


def bloc_du_plan(data: dict) -> dict:
    """Le bloc d'écran, construit MÉCANIQUEMENT depuis les arguments.

    Il sert deux fois, et c'est voulu : pour montrer le plan à l'humain AVANT
    sa décision (l'armement de la validation l'appelle sans rien exécuter), et
    pour le réafficher après l'accord. Deux chemins, un seul rendu : le plan
    approuvé est visuellement le plan exécuté, sans qu'un modèle repasse entre
    les deux pour le reformuler.
    """
    etapes = _etapes(data.get("etapes") or data.get("plan") or data.get("steps"))
    return {
        "type": "plan",
        "titre": str(data.get("titre") or "Ce que je vais faire")[:80],
        "resume": str(data.get("resume") or "")[:280],
        # `a_faire` pour toutes : rien n'est commencé au moment où on demande
        # l'accord. Cocher une étape d'avance serait mentir sur l'avancement,
        # et c'est exactement le travers déjà corrigé sur la frise de validation.
        "etapes": [{"titre": t, "etat": "a_faire"} for t in etapes],
    }


async def proposer_plan(data: dict, user) -> dict:
    """Annonce le plan, et n'exécute rien. L'accord humain est demandé par le
    graphe, cette fonction n'est appelée QU'APRÈS lui."""
    from skills.erreurs import SkillError

    bloc = bloc_du_plan(data)
    if len(bloc["etapes"]) < 2:
        # Un plan d'une seule étape n'est pas un plan : c'est l'action
        # elle-même, qu'il faut faire directement. Demander un accord pour
        # elle ajouterait un clic sans rien protéger, et le clic de trop est
        # ce qui apprend à cliquer sans lire.
        raise SkillError(
            "Un plan demande AU MOINS deux étapes. Pour un travail qui tient en "
            "un geste, n'annonce rien : exécute-le. `etapes` : la liste des "
            "étapes, en français, une phrase courte chacune.")

    logger.info("Plan validé : %d étape(s)", len(bloc["etapes"]))
    return {
        "plan": [e["titre"] for e in bloc["etapes"]],
        "bloc_ui": bloc,
        "message_final": ("C'est parti, je suis ce plan : "
                          + " ; ".join(e["titre"] for e in bloc["etapes"]) + "."),
        # Le contrat de la suite, écrit ici pour que le nœud de reprise n'ait
        # rien à deviner : le plan est accepté, le travail commence.
        "plan_accepte": True,
        "a_faire": ("AFFICHE le plan : insère un bloc ```ui contenant EXACTEMENT le "
                    "contenu de `bloc_ui`, puis EXÉCUTE les étapes les unes après les "
                    "autres SANS redemander l'accord. Une seule réponse à la fin, avec "
                    "tout ce qui a été produit."),
    }


# ═══════════════════════════════════════════════════════════════════════
#  LA PROCÉDURE — le plan d'aujourd'hui devient la marche à suivre de demain
# ═══════════════════════════════════════════════════════════════════════
#
# Une demande sans geste dédié n'est pas une demande impossible : c'est une
# demande dont personne n'a encore écrit la marche à suivre. « Liste-moi les
# dossiers où on attend une réponse depuis plus de quinze jours » se compose
# parfaitement de gestes existants — interroger les devis par statut, regarder
# les dates, trier — mais rien ne dit à l'assistant que c'est CE chemin-là
# qu'il faut prendre, ni ce que « en attente » veut dire dans cette maison.
#
# Alors il devine, et il devine différemment chaque fois. Le geste ci-dessous
# ferme cette boucle : une fois la marche à suivre établie avec la personne et
# vérifiée sur un cas réel, on l'écrit. La fois suivante, elle est là.
#
# ELLE S'ÉCRIT DANS LES CONSIGNES, à dessein. Une procédure doit être présente
# AVANT que le modèle choisisse son action, à chaque tour, et pas retrouvée par
# ressemblance quand la question a l'air d'y correspondre — c'est exactement le
# raisonnement de `learning/consignes.py`, et tous ses garde-fous valent ici :
# plafond par personne, droit d'écrire pour toute l'entreprise réservé à la
# direction, lecture par `consignes_retenues`, retrait par `oublier`. Une
# procédure qui ne s'oublierait pas aussi facilement qu'elle s'apprend serait
# une dette, pas un acquis.

MAX_ETAPES_PROCEDURE = 6
MAX_TITRE_PROCEDURE = 90


async def enregistrer_procedure(data: dict, user) -> dict:
    """Retient une marche à suivre validée, pour les fois suivantes."""
    from learning import consignes
    from skills.erreurs import SkillError

    nom = " ".join(str(data.get("nom") or data.get("titre") or "").split())[:60]
    quand = " ".join(str(data.get("quand") or data.get("declencheur") or "").split())[:140]
    etapes = [t[:MAX_TITRE_PROCEDURE]
              for t in _etapes(data.get("etapes") or data.get("marche_a_suivre"))
              ][:MAX_ETAPES_PROCEDURE]

    if not nom or not quand or len(etapes) < 2:
        raise SkillError(
            "Il manque de quoi écrire la procédure. `nom` : comment on l'appellera. "
            "`quand` : la demande qui doit la déclencher, dans les mots de "
            "l'utilisateur. `etapes` : au moins deux étapes, chacune un geste que "
            "tu sais réellement faire. Demande-les à l'utilisateur avant "
            "d'enregistrer quoi que ce soit.")

    texte = (f"PROCÉDURE « {nom} » : {quand}, faire dans l'ordre : "
             + " ; ".join(f"{i}) {e}" for i, e in enumerate(etapes, start=1)) + ".")
    if len(texte) > consignes.MAX_CARACTERES:
        # Tronquer perdrait la FIN, donc les dernières étapes : une procédure
        # amputée est pire qu'une procédure absente, parce qu'elle sera suivie.
        raise SkillError(
            f"Cette procédure fait {len(texte)} caractères, le maximum est "
            f"{consignes.MAX_CARACTERES}. Raccourcis les étapes : une ligne "
            "chacune, sans explication.")

    pour_tous = bool(data.get("pour_tous"))
    resultat = await consignes.ajouter(texte, user, pour_tous=pour_tous)
    if not resultat.get("ok"):
        return {**resultat, "message_final": resultat.get("message")}

    portee = "pour toute l'entreprise" if pour_tous else "pour vous"
    return {
        **resultat,
        "procedure": nom, "etapes": etapes,
        "message_final": (f"C'est retenu {portee} : « {nom} ». La prochaine fois "
                          f"que vous le demanderez, je suivrai ces {len(etapes)} "
                          f"étapes sans qu'on ait à en reparler."),
        "a_faire": ("Dis en UNE phrase ce qui est retenu et pour qui. N'affiche pas "
                    "les étapes une seconde fois si tu viens de les montrer, et "
                    "rappelle qu'on peut la retirer avec « oublie la procédure "
                    "<nom> »."),
    }


# ── Déclaration ──────────────────────────────────────────────────────
from skills.registre import Declaration

SKILLS = {
    "enregistrer_procedure": Declaration(
        fonction=enregistrer_procedure,
        description=(
            "RETIENT une marche a suivre, pour ne plus avoir a la redemander. A "
            "appeler quand une demande n'avait PAS de geste dedie, que tu as "
            "etabli le chemin avec l'utilisateur et qu'il a marche : « la "
            "prochaine fois, fais comme ca ». `nom` : le nom court de la "
            "procedure. `quand` : la demande qui la declenche, dans les mots de "
            "l'utilisateur. `etapes` : 2 a 6 gestes que tu sais REELLEMENT faire, "
            "une ligne chacune. `pour_tous` : true pour toute l'entreprise "
            "(direction uniquement). Ne l'appelle jamais de ta propre initiative "
            "sur une marche a suivre qui n'a pas ete verifiee : propose-la, et "
            "attends le oui"),
        requis=["nom", "quand", "etapes"], optionnels=["pour_tous"],
        # Comme `retenir` : cela change le comportement de l'assistant, pas le
        # monde extérieur. Le droit d'écrire POUR TOUS est vérifié dans le
        # skill, sur le rôle réel de l'appelant.
        effet="ecriture_interne",
        libelle="je retiens la marche à suivre"),
    "proposer_plan": Declaration(
        fonction=proposer_plan,
        description=(
            "ANNONCE le plan d'un travail LONG et le fait valider avant de "
            "commencer. A employer quand une demande tient en plusieurs gestes "
            "distincts (analyser un plan PUIS retrouver un client PUIS produire "
            "un document PUIS rediger un mail), ou quand le travail va durer. "
            "`etapes` : 2 a 10 etapes, une phrase courte chacune, en francais, "
            "dans l'ordre. `titre` et `resume` : de quoi il s'agit. N'annonce QUE "
            "ce que tu sais faire avec tes actions. Une fois le plan approuve, "
            "execute TOUT sans redemander l'accord et ne rends qu'UNE reponse a "
            "la fin. Pour un travail qui tient en un seul geste, ne l'appelle "
            "pas : fais-le"),
        requis=["etapes"], optionnels=["titre", "resume"],
        # `externe` n'est pas ici une sortie hors de l'entreprise : c'est la
        # seule porte qui suspend le graphe et demande un accord humain. Cf. le
        # docstring du module.
        effet="externe",
        libelle="je prépare le plan de travail"),
}
