"""
Connecteur Outlook / Microsoft 365 (Microsoft Graph, flux app-only) — voie API directe.

Le domaine duret-sols.fr est hébergé sur Microsoft 365 (Exchange Online).
Le mot de passe seul NE suffit PAS (basic auth désactivée par Microsoft).

Alternative RECOMMANDÉE : Make.com (connecteur natif « Microsoft 365 Email ») → webhook.
Voie directe (ce module) — prérequis (voir SETUP_CONNECTEURS.md) :
  1. App Azure AD (Entra) : ms_tenant_id / ms_client_id / ms_client_secret.
  2. Permission d'application Mail.Read + « Grant admin consent » (admin M365 requis).
  3. Restreindre à la boîte cible via ApplicationAccessPolicy (RGPD).
"""
import logging

from config import settings
from ingestion.pipeline import ingest_document

logger = logging.getLogger("duret.ingestion.outlook")


async def sync(top: int = 50) -> dict:
    """Lit les derniers emails de la boîte cible et ingère leur contenu (anonymisé)."""
    if not (settings.ms_tenant_id and settings.ms_client_id
            and settings.ms_client_secret and settings.ms_mailbox):
        raise NotImplementedError(
            "Outlook/M365 non configuré : renseigne MS_TENANT_ID, MS_CLIENT_ID, "
            "MS_CLIENT_SECRET, MS_MAILBOX (app Azure + Mail.Read + consentement admin). "
            "Voie la plus simple : Make.com → POST /api/ingestion/webhook.")

    import msal
    import httpx

    app = msal.ConfidentialClientApplication(
        settings.ms_client_id,
        authority=f"https://login.microsoftonline.com/{settings.ms_tenant_id}",
        client_credential=settings.ms_client_secret,
    )
    tok = app.acquire_token_for_client(scopes=["https://graph.microsoft.com/.default"])
    if "access_token" not in tok:
        raise RuntimeError(tok.get("error_description", "Authentification Graph échouée"))

    headers = {"Authorization": f"Bearer {tok['access_token']}"}
    url = (f"https://graph.microsoft.com/v1.0/users/{settings.ms_mailbox}/messages"
           f"?$top={top}&$select=id,subject,from,receivedDateTime,bodyPreview,body")

    ingested = 0
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(url, headers=headers)
        r.raise_for_status()
        for m in r.json().get("value", []):
            body = (m.get("body") or {}).get("content") or m.get("bodyPreview") or ""
            sender = (m.get("from") or {}).get("emailAddress", {}).get("address", "")
            text = f"Sujet : {m.get('subject','')}\nDe : {sender}\nDate : {m.get('receivedDateTime','')}\n\n{body}"
            if await ingest_document(text=text, source_type="email", source_id=m["id"],
                                     source_filename=m.get("subject"), anonymize=True):
                ingested += 1
    return {"emails": ingested}
