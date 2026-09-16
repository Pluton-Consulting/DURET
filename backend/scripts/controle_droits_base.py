"""
LE CLOISONNEMENT TIENT-IL VRAIMENT ? (16/09, audit D-20/S-20 et D-00/S-00.)

`FORCE ROW LEVEL SECURITY` (migration 010) applique les politiques même au
propriétaire des tables. Mais un rôle SUPERUSER ou BYPASSRLS les ignore TOUTES :
si l'application se connecte avec un tel compte, le cloisonnement des
conversations, des documents et des mails est décoratif — sans qu'aucune ligne
de code ne soit fausse.

Ce script ne modifie RIEN. Il lit, avec la connexion réelle de l'application,
et dit ce qu'il voit :

  · qui est connecté, et si ce rôle est superuser / bypassrls ;
  · quelles tables forcent la RLS, et lesquelles ont des politiques ;
  · si le contexte (`app.current_user_id`) est bien vide hors transaction —
    une connexion du pool ne doit jamais garder le rôle de quelqu'un d'autre ;
  · un test de fuite : sous le contexte d'une personne, combien de
    conversations d'autres comptes la connexion voit-elle ?

USAGE (dans le conteneur) :
    docker compose exec backend python scripts/controle_droits_base.py
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

TABLES_SENSIBLES = ("threads", "messages", "documents", "validations", "api_usage_daily",
                    "operations_externes", "requetes_chat")


async def main() -> int:
    from database.connection import get_db, get_rls_db, init_db
    await init_db()
    alertes = []

    async with get_db() as conn:
        role = await conn.fetchrow(
            """SELECT current_user AS nom, rolsuper, rolbypassrls, rolcreatedb
                 FROM pg_roles WHERE rolname = current_user""")
        print(f"Connexion de l'application : {role['nom']}")
        print(f"  superuser  : {role['rolsuper']}")
        print(f"  bypassrls  : {role['rolbypassrls']}")
        if role["rolsuper"] or role["rolbypassrls"]:
            alertes.append("Le rôle de l'application IGNORE les politiques de cloisonnement "
                           "(superuser ou bypassrls) : la RLS ne protège rien.")

        print("\nTables sensibles :")
        for table in TABLES_SENSIBLES:
            ligne = await conn.fetchrow(
                """SELECT c.relrowsecurity AS rls, c.relforcerowsecurity AS force,
                          (SELECT count(*) FROM pg_policies p
                            WHERE p.tablename = $1) AS politiques,
                          pg_get_userbyid(c.relowner) AS proprietaire
                     FROM pg_class c WHERE c.relname = $1""", table)
            if ligne is None:
                print(f"  {table:<22} absente (migration non appliquée ?)")
                continue
            print(f"  {table:<22} rls={ligne['rls']} force={ligne['force']} "
                  f"politiques={ligne['politiques']} propriétaire={ligne['proprietaire']}")
            if table in ("threads", "messages") and not (ligne["rls"] and ligne["force"]):
                alertes.append(f"{table} : la RLS n'est pas FORCÉE (migration 010).")

        contexte = await conn.fetchval("SELECT current_setting('app.current_user_id', true)")
        print(f"\nContexte hors transaction : {contexte!r} (doit être vide ou NULL)")
        if contexte:
            alertes.append("Une connexion du pool garde un contexte utilisateur : "
                           "le prochain emprunteur hériterait des droits du précédent.")

        # Un test de FUITE, en lecture : sous le contexte d'une personne, combien
        # de conversations d'autres comptes la connexion voit-elle ?
        quelqu_un = await conn.fetchrow(
            "SELECT id::text, role FROM users WHERE role NOT IN ('super_admin','direction') "
            "AND actif = true LIMIT 1")
    if quelqu_un:
        async with get_rls_db(quelqu_un["id"], quelqu_un["role"]) as conn:
            etrangers = await conn.fetchval(
                "SELECT count(*) FROM threads WHERE user_id <> $1::uuid", quelqu_un["id"])
        print(f"\nFuite testée avec un compte {quelqu_un['role']} : "
              f"{etrangers} conversation(s) d'autrui visible(s) (attendu : 0)")
        if int(etrangers or 0) > 0:
            alertes.append(f"{etrangers} conversations d'autres comptes sont visibles sous un "
                           "contexte utilisateur : le cloisonnement ne tient pas.")
    else:
        print("\n(aucun compte métier actif : le test de fuite n'a pas été joué)")

    print()
    if alertes:
        print("À CORRIGER :")
        for a in alertes:
            print(f"  · {a}")
        print("\nProcédure : créer un rôle applicatif NOSUPERUSER NOBYPASSRLS avec les seuls")
        print("droits nécessaires, un rôle de migration séparé, puis basculer DATABASE_URL")
        print("après avoir vérifié lectures et écritures de chaque composant (audit D-20/S-20).")
        return 1
    print("Cloisonnement : rien à signaler.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
