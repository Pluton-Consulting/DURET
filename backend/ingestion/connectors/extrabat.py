"""
Connecteur Extrabat (ERP/CRM).

Deux voies :
  1. IMMÉDIATE, sans éditeur — import des exports CSV/Excel (bulle « Exports » d'Extrabat :
     clients, gestion commerciale, factures, articles). Voir import_export().
  2. API REST partenaire (base https://api.extrabat.com/v1) — nécessite un couple
     identifiant/mot de passe API généré dans Extrabat (Paramètres > Magasin > Coordonnées),
     DIFFÉRENT du login email, et une ACTIVATION par le support Extrabat (doc non publique).

Aucun connecteur Make/Zapier natif. Voir SETUP_CONNECTEURS.md.
"""
import logging

from config import settings
from ingestion.pipeline import ingest_document

logger = logging.getLogger("duret.ingestion.extrabat")

# ⚠ Entités confirmées publiquement. « devis » / « chantiers » plausibles mais à valider avec l'éditeur.
_ENTITIES = ("clients", "factures", "articles", "bons-commande", "collaborateurs", "agenda")


def _flatten(obj: dict) -> str:
    return "\n".join(f"{k}: {v}" for k, v in obj.items() if v not in (None, "", []))


async def sync() -> dict:
    """Interroge l'API REST Extrabat (une fois les identifiants API activés)."""
    if not (settings.extrabat_api_login and settings.extrabat_api_password):
        raise NotImplementedError(
            "Extrabat API non configurée : génère les identifiants API dans Extrabat "
            "(Paramètres > Magasin > Coordonnées). L'activation par le support Extrabat est requise. "
            "En attendant, ingère les exports CSV/Excel via extrabat.import_export(path, source_type).")

    import httpx

    auth = (settings.extrabat_api_login, settings.extrabat_api_password)
    ingested = 0
    async with httpx.AsyncClient(base_url=settings.extrabat_base_url, auth=auth, timeout=30) as client:
        for entity in _ENTITIES:
            try:
                r = await client.get(f"/{entity}")
                r.raise_for_status()
                payload = r.json()
                items = payload if isinstance(payload, list) else payload.get("data", [])
                for item in items:
                    if await ingest_document(text=_flatten(item), source_type=entity,
                                             source_id=str(item.get("id", "")),
                                             source_filename=entity, anonymize=True):
                        ingested += 1
            except Exception as e:
                logger.warning("Extrabat /%s : %s (endpoint à confirmer avec l'éditeur)", entity, e)
    return {"ingérés": ingested}


async def import_export(file_path: str, source_type: str = "extrabat") -> dict:
    """Ingère un export CSV/Excel Extrabat — voie immédiate sans API."""
    import pandas as pd

    if file_path.lower().endswith((".xlsx", ".xls")):
        df = pd.read_excel(file_path)
    else:
        df = pd.read_csv(file_path, sep=None, engine="python")  # auto-détection du séparateur

    ingested = 0
    for idx, row in df.iterrows():
        text = "\n".join(f"{c}: {row[c]}" for c in df.columns if str(row[c]) not in ("nan", ""))
        if await ingest_document(text=text, source_type=source_type, source_id=f"{source_type}-{idx}",
                                 source_filename=file_path.replace("\\", "/").split("/")[-1],
                                 anonymize=True):
            ingested += 1
    return {"lignes": len(df), "ingérées": ingested}
