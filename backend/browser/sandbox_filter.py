"""
Filtre de sécurité appliqué avant toute navigation.
Bloque les IPs privées, les domaines hors-scope,
et sanitise les requêtes pour éviter les fuites PII.
"""

import ipaddress
import re
import socket
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


# LES SERVICES INTERNES QU'ON AUTORISE EXPRESSÉMENT (aucun par défaut). Un
# hôte nommé ici échappe au refus des adresses internes — c'est une décision
# d'exploitation, pas quelque chose qu'une page web peut obtenir.
HOTES_INTERNES_AUTORISES: set = set()


def _adresse_interne(ip: "ipaddress._BaseAddress") -> bool:
    """Cette adresse mène-t-elle à la machine ou au réseau privé ?"""
    return bool(ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved
                or ip.is_multicast or ip.is_unspecified
                # IPv4 déguisée en IPv6 (::ffff:10.0.0.1) : la même adresse.
                or (getattr(ip, "ipv4_mapped", None) and _adresse_interne(ip.ipv4_mapped)))


class SandboxFilter:

    def is_blocked(self, url: str) -> tuple[bool, str]:
        """(bloqué, raison). Le nom est RÉSOLU (16/09, audit D-21) : comparer
        des chaînes laissait passer `localtest.me`, `0x7f.0.0.1`, une IPv6 et
        tout nom public qui pointe vers 10.x — c'est le b.a.-ba du SSRF."""
        try:
            parsed = urlparse(url)
        except Exception:
            return True, "URL invalide"

        if parsed.scheme not in ('http', 'https'):
            return True, f"Protocole non autorisé : {parsed.scheme}"

        hostname = (parsed.hostname or '').strip().lower()
        if not hostname:
            return True, "adresse sans hôte"

        for pattern in PRIVATE_IP_RE:
            if pattern.match(hostname):
                return True, f"IP privée bloquée : {hostname}"

        for domain in BLOCKED_DOMAINS:
            if hostname == domain or hostname.endswith(f'.{domain}'):
                return True, f"Domaine bloqué : {domain}"

        if parsed.port and parsed.port not in (80, 443, 8080, 8443):
            return True, f"Port non standard : {parsed.port}"

        if hostname in HOTES_INTERNES_AUTORISES:
            return False, ""

        # L'hôte est-il une adresse écrite autrement (IPv6, hexadécimal) ?
        try:
            ip = ipaddress.ip_address(hostname.strip('[]'))
            return (True, f"adresse interne bloquée : {hostname}") if _adresse_interne(ip) else (False, "")
        except ValueError:
            pass

        # UN NOM PUBLIC PEUT POINTER VERS L'INTÉRIEUR. On résout, et l'on refuse
        # si UNE SEULE des adresses est interne : un nom à deux adresses (une
        # publique, une privée) ne doit pas passer une fois sur deux.
        try:
            infos = socket.getaddrinfo(hostname, parsed.port or (443 if parsed.scheme == "https" else 80),
                                       proto=socket.IPPROTO_TCP)
        except Exception:  # noqa: BLE001 — sans résolution, on ne sait pas où ça mène
            # FAIL-CLOSED, ET LA RAISON EST DITE : un nom qu'on ne peut pas
            # résoudre n'ouvrira pas de page non plus. Mieux vaut refuser en
            # l'expliquant que laisser passer sans savoir.
            return True, (f"« {hostname} » n'a pas pu être résolu : impossible de vérifier "
                          "où il mène (DNS indisponible ?)")
        for info in infos:
            adresse = info[4][0]
            try:
                if _adresse_interne(ipaddress.ip_address(adresse)):
                    return True, f"{hostname} mène à une adresse interne ({adresse})"
            except ValueError:
                continue
        return False, ""

    def sanitize_query(self, query: str) -> str:
        """Supprime les PII d'une requête avant envoi vers un moteur externe."""
        for pattern, replacement in PII_PATTERNS:
            query = re.sub(pattern, replacement, query)
        return query[:200].strip()
