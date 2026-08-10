# Image Caddy personnalisée : Caddy + module DNS Gandi (pour le challenge ACME DNS-01).
# Le challenge DNS-01 permet d'obtenir un certificat Let's Encrypt VALIDE pour un service
# qui n'est PAS joignable publiquement (ici l'app est sur une IP privée du VPN).
# Le DNS de pluton-consulting.fr est géré par Gandi (LiveDNS) → module caddy-dns/gandi.
#
# ⚠ caddy-dns/gandi exige Go >= 1.24. On utilise donc le builder Caddy le plus récent
# (caddy:2-builder, Go >= 1.24) + GOTOOLCHAIN=auto pour laisser Go récupérer au besoin la
# toolchain requise (l'image builder est bloquée en GOTOOLCHAIN=local par défaut).
FROM caddy:2-builder AS builder
ENV GOTOOLCHAIN=auto
RUN xcaddy build --with github.com/caddy-dns/gandi

FROM caddy:2
COPY --from=builder /usr/bin/caddy /usr/bin/caddy
