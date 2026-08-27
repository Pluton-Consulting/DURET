"""
MESURE DE LA CASCADE — qui répond, en combien de temps, et qui coûte pour rien.

Ce projet a déjà payé une fois le réglage au jugé : Groq avait été mis en tête
du palier léger sur une mesure faite avec le MAUVAIS modèle (le 70B), alors que
le petit modèle du palier rendait 404 sur la clé. Le chemin court était devenu
le plus long. La leçon tient en une phrase : on ne réordonne pas une cascade
sans l'avoir mesurée, candidat par candidat, avec le modèle réellement appelé.

Ce banc appelle CHAQUE candidat de CHAQUE palier avec une question courte et
identique, et rend un tableau : durée, verdict, et le motif quand ça échoue
(clé absente, 404, 401, quota, délai dépassé). Il dit aussi, pour chaque palier,
combien de temps coûtent les candidats qui échouent AVANT le premier qui répond
— c'est ce chiffre-là, et lui seul, qui justifie de changer l'ordre.

  ⚠ CE BANC APPELLE DE VRAIS FOURNISSEURS. Il consomme donc des jetons (une
    poignée par candidat) et doit tourner LÀ OÙ LES CLÉS SONT, c'est-à-dire
    dans le conteneur :

      docker compose exec backend python scripts/mesure_cascade.py

    Aucune clé n'est affichée : seuls les noms de fournisseur et de modèle.
"""
import asyncio, sys, time, pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

VERT, ROUGE, JAUNE, GRIS, RAZ = "\x1b[92m", "\x1b[91m", "\x1b[93m", "\x1b[90m", "\x1b[0m"

QUESTION = "Réponds exactement ceci, sans rien ajouter : OK"


def _motif(err: Exception) -> str:
    """Le POURQUOI d'un échec, en clair — jamais l'URL, qui porte la clé."""
    m = str(err).lower()
    for aiguille, libelle in (
        ("404", "modèle absent de ce compte (404)"),
        ("model_not_found", "modèle absent de ce compte"),
        ("401", "clé refusée (401)"),
        ("403", "clé refusée (403)"),
        ("invalid api key", "clé refusée"),
        ("429", "quota atteint (429)"),
        ("rate limit", "quota atteint"),
        ("quota", "quota atteint"),
        ("timeout", "délai dépassé"),
        ("timed out", "délai dépassé"),
        ("connection", "connexion refusée"),
        ("api key", "clé absente"),
    ):
        if aiguille in m:
            return libelle
    return type(err).__name__


async def mesurer(provider, model, tier) -> dict:
    from llm.router import _build_model, tier_max_tokens, tier_timeout
    label = f"{provider}:{model or '(défaut)'}"
    debut = time.monotonic()
    try:
        llm = _build_model(provider, model, tier_max_tokens(tier), tier_timeout(tier))
    except Exception as e:  # noqa: BLE001 — clé absente, dépendance manquante
        return {"label": label, "ok": False, "secondes": 0.0,
                "motif": _motif(e), "sans_appel": True}
    try:
        from langchain_core.messages import HumanMessage
        rep = await llm.ainvoke([HumanMessage(content=QUESTION)])
        secondes = time.monotonic() - debut
        vide = not str(getattr(rep, "content", "") or "").strip()
        # UNE RÉPONSE VIDE N'EST PAS UNE RÉPONSE : le routeur le sait déjà, ce
        # banc doit le savoir aussi, sinon il classerait premier un candidat qui
        # ne rend rien.
        return {"label": label, "ok": not vide, "secondes": secondes,
                "motif": "réponse vide" if vide else "", "sans_appel": False}
    except Exception as e:  # noqa: BLE001
        return {"label": label, "ok": False, "secondes": time.monotonic() - debut,
                "motif": _motif(e), "sans_appel": False}


async def main() -> int:
    from llm.router import _tier_chain, LLMTier

    print("\n\x1b[1mMESURE DE LA CASCADE\x1b[0m")
    print(f"{GRIS}Une question courte, le même prompt pour tous. "
          f"Aucune clé n'est affichée.{RAZ}\n")

    verdict = 0
    for tier in (LLMTier.LIGHT, LLMTier.STANDARD, LLMTier.COMPLEX):
        chain = _tier_chain(tier)
        print(f"\x1b[1m{tier.value.upper()}\x1b[0m  {GRIS}{len(chain)} candidat(s), "
              f"délai accordé à chacun : {__import__('llm.router', fromlist=['x']).tier_timeout(tier.value)} s{RAZ}")

        perdu, premier = 0.0, None
        for provider, model in chain:
            r = await mesurer(provider, model, tier.value)
            if r["ok"]:
                marque, detail = f"{VERT}✓{RAZ}", f"{r['secondes']:.1f} s"
                if premier is None:
                    premier = r
            elif r["sans_appel"]:
                marque, detail = f"{GRIS}·{RAZ}", f"{GRIS}{r['motif']} — écarté sans appel{RAZ}"
            else:
                marque = f"{ROUGE}✗{RAZ}"
                detail = f"{ROUGE}{r['motif']}{RAZ} {GRIS}après {r['secondes']:.1f} s{RAZ}"
                if premier is None:
                    perdu += r["secondes"]
            print(f"   {marque} {r['label']:<46} {detail}")

        if premier is None:
            print(f"   {ROUGE}Aucun candidat ne répond sur ce palier.{RAZ}")
            verdict = 1
        elif perdu > 0:
            print(f"   {JAUNE}→ {perdu:.1f} s perdues avant la première réponse "
                  f"({premier['label']}).{RAZ}")
            print(f"   {JAUNE}  Mettre ce candidat plus haut ferait gagner ce temps "
                  f"À CHAQUE APPEL de ce palier.{RAZ}")
        else:
            print(f"   {VERT}→ le premier candidat répond : rien à gagner sur l'ordre.{RAZ}")
        print()

    print(f"{GRIS}Rappel : un candidat « écarté sans appel » ne coûte RIEN (sa clé "
          f"manque, l'instanciation échoue avant le réseau).\n"
          f"Seules les lignes rouges coûtent du temps réel.{RAZ}\n")
    return verdict


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
