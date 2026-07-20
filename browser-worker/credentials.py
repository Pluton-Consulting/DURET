"""
Résolution des identifiants par site → `sensitive_data` browser-use.

Le LLM ne voit JAMAIS les valeurs : browser-use n'expose que des placeholders
(x_user / x_pass) et injecte les vraies valeurs directement dans les champs.
Les secrets sont scopés par domaine (obligatoire) et `allowed_domains` sert de
garde-fou anti-exfiltration.

Format de secrets/site_credentials.json :
{
  "extrabat.com": {"x_user": "...", "x_pass": "..."},
  "deytime.fr":   {"x_user": "...", "x_pass": "..."}
}
"""
import json
import os

import wconfig


def load_site_credentials() -> dict:
    path = wconfig.SITE_CREDENTIALS_FILE
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def build_sensitive_data(allowed_domains: list[str]) -> dict:
    """
    Construit le dict sensitive_data scopé par domaine, uniquement pour les
    domaines de la tâche qui ont des identifiants enregistrés.
    """
    creds = load_site_credentials()
    sensitive: dict[str, dict] = {}
    for domain in allowed_domains:
        entry = creds.get(domain)
        if entry:
            # Scope à l'HÔTE EXACT (pas de wildcard *.{domain}) : évite l'injection des
            # identifiants sur un sous-domaine tiers (subdomain takeover / contenu tiers).
            sensitive[f"https://{domain}"] = entry
    return sensitive
