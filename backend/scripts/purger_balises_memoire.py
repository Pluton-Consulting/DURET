"""
Purge des balises d'anonymisation GRAVÉES dans la mémoire d'entreprise.

LE DÉGÂT. Les campagnes d'enrichissement de la mi-août ont tourné pendant que
la carte d'anonymisation se corrompait (« [LOC_2] → "[LOC_1]" », corrigé le
23/08) : des connaissances ont été écrites avec des balises que plus personne
ne saura résoudre — la carte de l'époque n'existe plus. Relevé le 30/08 dans
un Word produit depuis ces connaissances : « [PER_3] gère les devis », balise
technique dans un document remis à quelqu'un.

CE QUE FAIT CE SCRIPT. Il remplace, dans les documents de la mémoire (types
`apprentissage` et `procedure` — ceux que l'enrichissement écrit), toute
balise `[XXX_n]` par « [À COMPLÉTER] » : la donnée est perdue, l'écran le dit
honnêtement, et la tuyauterie ne ressort plus. L'écriture neuve est déjà
protégée (learning/debrief.py neutralise à l'enregistrement) ; ceci soigne le
passé. Pour RECONSTRUIRE une base complète, relancer ensuite
`lancer_enrichissement` — avec l'anonymisation coupée si c'est le choix de la
maison, les vraies valeurs s'écrivent.

USAGE (dans le conteneur, comme les migrations) :
    docker compose exec backend python scripts/purger_balises_memoire.py            # constat seul
    docker compose exec backend python scripts/purger_balises_memoire.py --purger   # remplace
"""
import asyncio
import re
import sys

BALISE = re.compile(r"\[[A-Z]{2,10}_\d+\]")
TYPES = ("apprentissage", "procedure")


async def main() -> int:
    purger = "--purger" in sys.argv

    from database.connection import init_db, get_db
    await init_db()

    async with get_db() as conn:
        lignes = await conn.fetch(
            "SELECT id, content FROM documents WHERE source_type = ANY($1::text[])",
            list(TYPES))
        touches = [(l["id"], l["content"]) for l in lignes
                   if BALISE.search(l["content"] or "")]
        print(f"{len(lignes)} entrée(s) de mémoire ({', '.join(TYPES)}), "
              f"{len(touches)} portant des balises orphelines.")
        for _, contenu in touches[:5]:
            jetons = sorted(set(BALISE.findall(contenu)))[:6]
            print("  exemple :", " ".join(jetons), "—", contenu[:80].replace("\n", " "))

        if not purger:
            print("\nConstat seul. Relancer avec --purger pour remplacer les "
                  "balises par [À COMPLÉTER].")
            return 0

        for ident, contenu in touches:
            await conn.execute(
                "UPDATE documents SET content = $2 WHERE id = $1",
                ident, BALISE.sub("[À COMPLÉTER]", contenu))
        print(f"\n{len(touches)} entrée(s) purgée(s) : les balises sont devenues "
              "[À COMPLÉTER]. Les vecteurs n'ont pas été recalculés — la "
              "recherche reste fonctionnelle, une balise n'a jamais aidé la "
              "similarité.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
