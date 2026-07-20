"""
Consentement Google Drive — À LANCER UNE SEULE FOIS, EN LOCAL (un navigateur s'ouvre).

Génère `secrets/google_token.json` (refresh token) à partir de
`secrets/google_credentials.json` (client OAuth « Desktop » téléchargé depuis Google
Cloud Console). Le backend, qui monte ./backend dans le conteneur, réutilisera ensuite
ce token automatiquement — plus aucune interaction.

Prérequis (sur ta machine, pas dans Docker) :
    pip install google-api-python-client google-auth-oauthlib

Usage (depuis le dossier backend/) :
    python scripts/gdrive_consent.py

Script volontairement autonome : ne dépend NI du .env NI de la stack backend.
"""
import os
import sys

CRED = os.environ.get("GOOGLE_CREDENTIALS_FILE", "secrets/google_credentials.json")
TOKEN = os.environ.get("GOOGLE_TOKEN_FILE", "secrets/google_token.json")
SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]


def main() -> int:
    if not os.path.exists(CRED):
        print(f"❌ Fichier introuvable : {CRED}")
        print("   → Télécharge le client OAuth « Desktop app » depuis Google Cloud Console")
        print("     (APIs & Services > Credentials) et place-le à cet emplacement.")
        return 1

    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build
    except ImportError:
        print("❌ Dépendances manquantes. Lance :")
        print("   pip install google-api-python-client google-auth-oauthlib")
        return 1

    flow = InstalledAppFlow.from_client_secrets_file(CRED, SCOPES)
    creds = flow.run_local_server(port=0)  # ouvre le navigateur pour le consentement

    os.makedirs(os.path.dirname(TOKEN) or ".", exist_ok=True)
    with open(TOKEN, "w") as f:
        f.write(creds.to_json())

    service = build("drive", "v3", credentials=creds)
    email = service.about().get(fields="user").execute().get("user", {}).get("emailAddress", "?")
    print(f"\n✅ Consentement OK — connecté en tant que : {email}")
    print(f"   Token écrit : {TOKEN}")
    print("   Le backend l'utilisera automatiquement. Déclenche ensuite :")
    print("   POST /api/ingestion/sync/google_drive")
    return 0


if __name__ == "__main__":
    sys.exit(main())
