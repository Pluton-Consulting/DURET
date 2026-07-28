#!/usr/bin/env python
"""
Import en masse d'un export CSV (Extrabat, Deytime, compta...) dans la mémoire d'entreprise.

Envoie UNE LIGNE = UN DOCUMENT vers /api/ingestion/webhook. C'est volontaire :
un export de 5 000 lignes envoyé en un seul bloc serait découpé arbitrairement et
la recherche RAG remonterait des morceaux sans rapport. Ligne par ligne, chaque
chantier / devis / client devient un document retrouvable.

Ré-import sans doublon : le pipeline supprime les chunks existants du même
`source_id` avant de réinsérer. On peut donc relancer l'import après mise à jour.

Exemples
--------
  # Aperçu sans rien envoyer (À FAIRE EN PREMIER)
  python scripts/import_csv.py export.csv --type chantier --dry-run

  # Import réel, en identifiant chaque ligne par la colonne "Code chantier"
  python scripts/import_csv.py export.csv --type chantier --id-col "Code chantier"

  # Réservé à la direction
  python scripts/import_csv.py devis.csv --type devis --access direction

Le fichier .xlsx n'est pas géré : l'exporter en CSV depuis Excel
(Fichier > Enregistrer sous > CSV UTF-8).
"""
import argparse
import asyncio
import csv
import os
import sys
from pathlib import Path

import httpx

# Encodages typiques des exports français (Excel écrit souvent en cp1252).
ENCODAGES = ("utf-8-sig", "utf-8", "cp1252", "latin-1")


def lire_csv(chemin: Path):
    """Lit le CSV en devinant l'encodage et le séparateur. Retourne (entetes, lignes)."""
    dernier = None
    for enc in ENCODAGES:
        try:
            brut = chemin.read_text(encoding=enc)
            break
        except UnicodeDecodeError as e:
            dernier = e
    else:
        raise SystemExit(f"Encodage illisible ({dernier}). Réenregistrez le fichier en CSV UTF-8.")

    echantillon = brut[:8192]
    try:
        sep = csv.Sniffer().sniff(echantillon, delimiters=";,\t|").delimiter
    except csv.Error:
        sep = ";" if echantillon.count(";") > echantillon.count(",") else ","

    lecteur = csv.DictReader(brut.splitlines(), delimiter=sep)
    lignes = [l for l in lecteur if any((v or "").strip() for v in l.values())]
    print(f"  séparateur détecté : « {sep} »  |  encodage : {enc}")
    return (lecteur.fieldnames or []), lignes


def ligne_en_texte(ligne: dict) -> str:
    """« Colonne : valeur » par ligne — lisible par le modèle, et les libellés
    servent aussi à la recherche sémantique."""
    return "\n".join(f"{(k or '').strip()} : {(v or '').strip()}"
                     for k, v in ligne.items()
                     if (v or "").strip() and (k or "").strip())


async def envoyer(client, url, secret, doc, essais=3):
    for tentative in range(essais):
        try:
            r = await client.post(url, json=doc, headers={"X-Ingestion-Secret": secret})
            if r.status_code < 300:
                return True, ""
            # 401/422 : inutile de réessayer, la cause ne changera pas.
            if r.status_code in (401, 422):
                return False, f"HTTP {r.status_code} : {r.text[:120]}"
            erreur = f"HTTP {r.status_code} : {r.text[:120]}"
        except Exception as e:  # réseau
            erreur = str(e)[:120]
        if tentative < essais - 1:
            await asyncio.sleep(2 ** tentative)
    return False, erreur


async def main() -> int:
    p = argparse.ArgumentParser(description="Import CSV vers la mémoire d'entreprise")
    p.add_argument("fichier", type=Path)
    p.add_argument("--type", required=True,
                   help="type de source : chantier, devis, client, facture, planning...")
    p.add_argument("--id-col", default=None,
                   help="colonne servant d'identifiant stable (défaut : numéro de ligne)")
    p.add_argument("--access", default="all",
                   help="niveau d'accès : all | direction (défaut : all)")
    p.add_argument("--url", default=os.environ.get("INGESTION_URL", "http://localhost:8000"),
                   help="URL du backend (défaut : http://localhost:8000)")
    p.add_argument("--secret", default=os.environ.get("INGESTION_WEBHOOK_SECRET"),
                   help="secret d'ingestion (défaut : $INGESTION_WEBHOOK_SECRET)")
    p.add_argument("--anonymize", action="store_true",
                   help="masquer les données personnelles à l'ingestion")
    p.add_argument("--parallele", type=int, default=4, help="envois simultanés (défaut : 4)")
    p.add_argument("--limite", type=int, default=0, help="n'importer que les N premières lignes")
    p.add_argument("--dry-run", action="store_true", help="afficher un aperçu sans rien envoyer")
    a = p.parse_args()

    if not a.fichier.exists():
        print(f"Fichier introuvable : {a.fichier}")
        return 1

    print(f"\nLecture de {a.fichier.name}…")
    entetes, lignes = lire_csv(a.fichier)
    if a.limite:
        lignes = lignes[:a.limite]
    print(f"  colonnes : {', '.join(entetes)}")
    print(f"  lignes   : {len(lignes)}")

    if a.id_col and a.id_col not in entetes:
        print(f"\nERREUR : colonne « {a.id_col} » absente. Colonnes disponibles : {entetes}")
        return 1

    docs = []
    for i, ligne in enumerate(lignes, 1):
        texte = ligne_en_texte(ligne)
        if not texte:
            continue
        cle = (ligne.get(a.id_col) or "").strip() if a.id_col else ""
        docs.append({
            "source_type": a.type,
            "source_id": f"{a.type}:{cle or i}",
            "filename": f"{a.fichier.name} (ligne {i})",
            "text": texte,
            "access_level": a.access,
            "anonymize": a.anonymize,
        })

    if a.dry_run:
        print(f"\n--- APERÇU (aucun envoi) — {len(docs)} documents ---")
        for d in docs[:3]:
            print(f"\n[{d['source_id']}]\n{d['text'][:400]}")
        print(f"\nRelancez sans --dry-run pour importer les {len(docs)} documents.")
        return 0

    if not a.secret:
        print("\nERREUR : secret manquant. Ajoutez --secret ou exportez INGESTION_WEBHOOK_SECRET.")
        return 1

    url = a.url.rstrip("/") + "/api/ingestion/webhook"
    print(f"\nEnvoi de {len(docs)} documents vers {url}…")
    verrou = asyncio.Semaphore(a.parallele)
    reussis, echecs = 0, []

    async with httpx.AsyncClient(timeout=60) as client:
        async def traiter(d):
            nonlocal reussis
            async with verrou:
                ok, err = await envoyer(client, url, a.secret, d)
            if ok:
                reussis += 1
                if reussis % 25 == 0 or reussis == len(docs):
                    print(f"  {reussis}/{len(docs)}…")
            else:
                echecs.append((d["source_id"], err))

        await asyncio.gather(*(traiter(d) for d in docs))

    print(f"\n{'=' * 54}")
    print(f"  Importés : {reussis}/{len(docs)}")
    if echecs:
        print(f"  Échecs   : {len(echecs)}")
        for sid, err in echecs[:5]:
            print(f"    - {sid} : {err}")
        if len(echecs) > 5:
            print(f"    … et {len(echecs) - 5} autres")
    print(f"{'=' * 54}")
    print("\nLa vectorisation tourne en tâche de fond. Suivi :")
    print("  GET /api/ingestion/status  (compteurs par source + jobs d'embedding)\n")
    return 1 if echecs else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
