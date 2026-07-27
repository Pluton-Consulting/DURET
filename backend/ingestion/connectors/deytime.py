"""
Connecteur Deytime (gestion du temps / pointage / plannings BTP).

Deytime N'EXPOSE AUCUNE API, aucun webhook, aucun connecteur Make/Zapier.
Deux voies réalistes :
  1. Import de l'export Excel « prépa paie » (backoffice manager, mensuel :
     heures, absences, heures sup, temps de chantier). Voir import_excel().
  2. Via EXTRABAT — Deytime y remonte automatiquement les temps ; les récupérer par
     l'API Extrabat (connecteur extrabat.py) est la voie pérenne si Extrabat est utilisé.

Contact éditeur (petit éditeur français, arrangement possible) : utilisateur@exemple.fr.
Voir SETUP_CONNECTEURS.md.
"""
import logging

from ingestion.pipeline import ingest_document

logger = logging.getLogger("duret.ingestion.deytime")


async def sync() -> dict:
    raise NotImplementedError(
        "Deytime n'expose aucune API. Ingère l'export Excel via deytime.import_excel(path), "
        "ou récupère les temps via le connecteur Extrabat (Deytime y est synchronisé).")


async def import_excel(file_path: str) -> dict:
    """Ingère l'export Excel Deytime (heures/absences/temps de chantier) — données RH sensibles."""
    import pandas as pd

    df = pd.read_excel(file_path)
    ingested = 0
    for idx, row in df.iterrows():
        text = "\n".join(f"{c}: {row[c]}" for c in df.columns if str(row[c]) not in ("nan", ""))
        if await ingest_document(text=text, source_type="planning", source_id=f"deytime-{idx}",
                                 source_filename=file_path.replace("\\", "/").split("/")[-1],
                                 access_level="direction_only",  # pointages = données RH
                                 anonymize=True):
            ingested += 1
    return {"lignes": len(df), "ingérées": ingested}
