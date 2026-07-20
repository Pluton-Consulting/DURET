"""
Filtre de sécurité appliqué avant toute navigation.
Bloque les IPs privées, les domaines hors-scope,
et sanitise les requêtes pour éviter les fuites PII.
"""

import re
from urllib.parse import urlparse


BLOCKED_DOMAINS = {
    'localhost', '127.0.0.1', '0.0.0.0',
    'facebook.com', 'instagram.com', 'tiktok.com', 'twitter.com', 'x.com',
}

PRIVATE_IP_RE = [
    re.compile(r'^10\.\d+\.\d+\.\d+$'),
    re.compile(r'^172\.(1[6-9]|2\d|3[01])\.\d+\.\d+$'),
    re.compile(r'^192\.168\.\d+\.\d+$'),
    re.compile(r'^100\.(6[4-9]|[7-9]\d|1[01]\d|12[0-7])\.\d+\.\d+$'),
]

PII_PATTERNS = [
    (re.compile(r'\S+@\S+\.\S+'), '[email]'),
    (re.compile(r'\b0[1-9][\s.-]?(?:\d{2}[\s.-]?){4}\b'), '[tel]'),
    (re.compile(r'\d+[\s ]?[€$]\b'), '[montant]'),
    (re.compile(r'\b\d{14}\b'), '[siret]'),
]


class SandboxFilter:

    def is_blocked(self, url: str) -> tuple[bool, str]:
        try:
            parsed = urlparse(url)
        except Exception:
            return True, "URL invalide"

        if parsed.scheme not in ('http', 'https'):
            return True, f"Protocole non autorisé : {parsed.scheme}"

        hostname = parsed.hostname or ''

        for pattern in PRIVATE_IP_RE:
            if pattern.match(hostname):
                return True, f"IP privée bloquée : {hostname}"

        for domain in BLOCKED_DOMAINS:
            if hostname == domain or hostname.endswith(f'.{domain}'):
                return True, f"Domaine bloqué : {domain}"

        if parsed.port and parsed.port not in (80, 443, 8080, 8443):
            return True, f"Port non standard : {parsed.port}"

        return False, ""

    def sanitize_query(self, query: str) -> str:
        """Supprime les PII d'une requête avant envoi vers un moteur externe."""
        for pattern, replacement in PII_PATTERNS:
            query = re.sub(pattern, replacement, query)
        return query[:200].strip()
