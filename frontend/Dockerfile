FROM node:20-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm ci

FROM node:20-alpine AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
# URL publique de l'API, injectée au BUILD (les variables NEXT_PUBLIC_* sont gelées à la
# compilation). Passée par docker-compose.prod.yml (build.args). Défaut = localhost (dev).
ARG NEXT_PUBLIC_API_URL=http://localhost:8000
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL
RUN npm run build

FROM node:20-alpine AS runner
WORKDIR /app
ENV NODE_ENV production
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static
COPY --from=builder /app/public ./public
# ── Correctif bug Next.js 14.2.0 + output:standalone + groupes de routes ──
# La sortie standalone OMET les *_client-reference-manifest.js des routes en groupe
# ((app)/(auth)) → erreur runtime "Cannot read properties of undefined (reading
# 'clientModules')". On restaure le dossier .next/server complet du builder (superset
# identique + les manifests manquants).
COPY --from=builder /app/.next/server ./.next/server
EXPOSE 3000
CMD ["node", "server.js"]
