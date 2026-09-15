"""
REDONNER UN CODE À UN ADMINISTRATEUR — la porte de secours, hors de l'interface
(16/09, audit D-19).

Depuis ce correctif, le code de PREMIÈRE ENTRÉE du serveur (`CODE_ADMIN_DEFAUT`)
ne sert qu'une fois : l'écran fait poser un vrai code juste après. Si personne
ne l'a posé — fenêtre fermée trop vite, code oublié, profil bloqué —, plus
aucune carte « Admin » ne s'ouvre. C'est voulu : un code commun permanent n'est
pas un secret. La reprise se fait ICI, sur le serveur, par qui a déjà les clés
de la machine.

Ce script ne lit jamais un code existant : il en POSE un nouveau (empreinte +
version chiffrée relisible en administration), remet les essais à zéro et lève
le blocage. Le code n'apparaît qu'une fois à l'écran du serveur, jamais dans les
journaux.

USAGE (dans le conteneur, comme les migrations) :
    docker compose exec backend python scripts/code_admin.py --lister
    docker compose exec backend python scripts/code_admin.py --profil <nom|adresse|id>
    docker compose exec backend python scripts/code_admin.py --profil <…> --code 481920
"""
import argparse
import asyncio
import os
import secrets
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROLES = ("super_admin", "direction")


async def _profils(conn, role_seulement=True):
    requete = ("SELECT id, name, email, role, actif, code_pin_hash IS NOT NULL AS a_code "
               "FROM users WHERE role = ANY($1::text[]) ORDER BY role, name")
    return await conn.fetch(requete, list(ROLES) if role_seulement else list(ROLES))


def _choisir(lignes, vise: str):
    """Le profil désigné par son identifiant, son adresse ou son nom (exact,
    puis approché). Rend (ligne, message d'erreur)."""
    vise = (vise or "").strip().lower()
    exacts = [l for l in lignes if vise in (str(l["id"]).lower(), (l["email"] or "").lower(),
                                            (l["name"] or "").strip().lower())]
    if len(exacts) == 1:
        return exacts[0], None
    if len(exacts) > 1:
        return None, "Plusieurs profils portent ce nom : désignez-le par son identifiant."
    approches = [l for l in lignes if vise and vise in (l["name"] or "").strip().lower()]
    if len(approches) == 1:
        return approches[0], None
    return None, ("Aucun profil administrateur ne correspond." if not approches
                  else "Plusieurs profils correspondent : précisez.")


async def main() -> int:
    analyse = argparse.ArgumentParser(description="Redonner un code à un administrateur.")
    analyse.add_argument("--lister", action="store_true", help="les profils administrateurs")
    analyse.add_argument("--profil", help="identifiant, adresse ou nom du profil")
    analyse.add_argument("--code", help="le code (4 à 6 chiffres) ; sinon il est tiré au sort")
    args = analyse.parse_args()

    from auth import profils as _p
    from database.connection import get_db, init_db, schema_incomplet
    await init_db()

    async with get_db() as conn:
        lignes = await _profils(conn)
        if args.lister or not args.profil:
            print(f"{len(lignes)} profil(s) administrateur(s) :")
            for l in lignes:
                etat = "code posé" if l["a_code"] else "SANS code"
                print(f"  {l['id']}  {(l['name'] or '—'):<20} {l['role']:<12} "
                      f"{'actif' if l['actif'] else 'désactivé':<10} {etat}")
            if not args.profil:
                print("\nPour en poser un : --profil <nom|adresse|id> [--code 481920]")
            return 0

        ligne, erreur = _choisir(lignes, args.profil)
        if ligne is None:
            print(erreur)
            return 1
        code = (args.code or "").strip() or "".join(secrets.choice("0123456789") for _ in range(6))
        if not _p.code_valide(code):
            print("Un code fait 4 à 6 chiffres.")
            return 1
        for requete in (
            "UPDATE users SET code_pin_hash = $2, code_pin_chiffre = $3, code_pin_echecs = 0, "
            "code_pin_bloque_jusqu = NULL, code_defaut_le = NULL WHERE id = $1::uuid",
            "UPDATE users SET code_pin_hash = $2, code_pin_chiffre = $3, code_pin_echecs = 0, "
            "code_pin_bloque_jusqu = NULL WHERE id = $1::uuid",
            "UPDATE users SET code_pin_hash = $2, code_pin_echecs = 0, "
            "code_pin_bloque_jusqu = NULL WHERE id = $1::uuid",
        ):
            try:
                await conn.execute(requete, str(ligne["id"]), _p.hacher_code(code),
                                   *([_p.chiffrer_code(code)] if "code_pin_chiffre" in requete else []))
                break
            except Exception as e:  # noqa: BLE001
                if not schema_incomplet(e):
                    raise
        else:
            print("Les migrations 041/042 ne sont pas appliquées : aucun code ne peut être posé.")
            return 1

    print(f"Code posé pour {(ligne['name'] or ligne['id'])} ({ligne['role']}) : {code}")
    print("Notez-le maintenant : il ne sera plus affiché. Le blocage éventuel est levé.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
