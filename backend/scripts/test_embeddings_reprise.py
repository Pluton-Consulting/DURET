"""
Banc du garde-fou d'embeddings — « un 429 se lit, la cadence s'adapte, la file se vide ».

POURQUOI. Le 31/08, journaux du VPS : « Gemini 429 — pause 1800s » toutes les
trente minutes depuis le matin, et 3 390 morceaux sur 6 401 sans vecteur (dont
1 011 des 1 029 du Drive) — la recherche documentaire ne les voyait que par
pg_trgm. Une requête d'un texte passait pourtant : c'était le DÉBIT. Le worker
prenait un 429 à la première rafale, dormait une demi-heure, recommençait à
l'identique ; et le détail du 429 (retryDelay, quotaId) n'était pas lu.

CE QUE CE BANC PROUVE, sans réseau : la classe `_GeminiThrottle` (extraite du
source livré et exécutée avec des réglages de banc) lit le délai et le quota
dans un 429 de Google ; attend ce délai-là quand il est donné, sinon une pause
courte qui double à chaque récidive et plafonne au réglage ; ralentit sa cadence
à chaque 429 et la détend au fil des succès sans passer sous le réglage ; et que
`_embed_gemini` passe le corps du 429 et signale les succès.
"""
import asyncio
import pathlib
import re
import sys
import time
import types
from typing import Optional

BACKEND = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "backend")
echecs = []
# Une seule boucle pour tout le banc : `asyncio.Lock()` se lie à la boucle
# courante sur les Python d'avant 3.10, et `asyncio.run` la ferme à chaque appel.
_boucle = asyncio.new_event_loop()
asyncio.set_event_loop(_boucle)
run = _boucle.run_until_complete


def verifier(nom, cond, detail=""):
    print(f"  {'✓' if cond else '✗'} {nom}" + (f"  → {detail}" if detail and not cond else ""))
    if not cond:
        echecs.append(nom)


src = (BACKEND / "vectorstore" / "embeddings.py").read_text(encoding="utf-8")
debut = src.index("class _GeminiThrottle:")
fin = src.index("\n\n\n", debut)
import datetime
reglages = types.SimpleNamespace(embedding_min_interval_s=0.8, embedding_daily_request_cap=900,
                                 embedding_cooldown_s=1800)
espace = {"asyncio": asyncio, "time": time, "datetime": datetime, "Optional": Optional,
          "settings": reglages}
exec(src[debut:fin], espace)  # noqa: S102 — code du dépôt
Throttle = espace["_GeminiThrottle"]

CORPS_429 = ('{"error": {"code": 429, "message": "You exceeded your current quota, please check your '
             'plan and billing details.", "status": "RESOURCE_EXHAUSTED", "details": ['
             '{"@type": "type.googleapis.com/google.rpc.QuotaFailure", "violations": ['
             '{"quotaMetric": "generativelanguage.googleapis.com/embed_content_requests", '
             '"quotaId": "EmbedContentRequestsPerMinutePerProjectPerModel-FreeTier"}]}, '
             '{"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "18s"}]}}')

print(f"\n═══ EMBEDDINGS : REPRISE APRÈS 429 — {BACKEND.parent}\n")

print("1. Le 429 est LU")
delai, diag = Throttle.lire_429(CORPS_429)
verifier("retryDelay « 18s » → 18 secondes", delai == 18.0, str(delai))
verifier("le quotaId est dans le diagnostic (FreeTier visible : la cause se lit)",
         "EmbedContentRequestsPerMinutePerProjectPerModel-FreeTier" in diag)
delai, diag = Throttle.lire_429("<html>Bad gateway</html>")
verifier("corps illisible : pas de délai, diagnostic honnête", delai is None and "illisible" in diag)
delai, diag = Throttle.lire_429('{"error": {"message": "Resource has been exhausted"}}')
verifier("sans détails : le message sert de diagnostic", delai is None and "exhausted" in diag)

print("\n2. La pause est celle demandée par Google — sinon courte et progressive")
t = Throttle()
pause, _ = run(t.hit_quota(CORPS_429))
verifier("délai annoncé 18 s → pause ≈ 20 s (marge de 2 s), pas 1800", 19.5 <= pause <= 20.5, str(pause))
t = Throttle()
pauses = [run(t.hit_quota(""))[0] for _ in range(7)]
verifier("sans délai annoncé : 30, 60, 120, 240, 480, 960 puis plafond 1800",
         pauses == [30.0, 60.0, 120.0, 240.0, 480.0, 960.0, 1800.0], str(pauses))
verifier("le plafond est celui du réglage (embedding_cooldown_s)", max(pauses) == reglages.embedding_cooldown_s)

print("\n3. La cadence ralentit à chaque 429 et se détend avec les succès")
t = Throttle()
verifier("au départ : la cadence du réglage", t.cadence == 0.8)
run(t.hit_quota(""))
verifier("un 429 double la cadence", t.cadence == 1.6)
for _ in range(10):
    run(t.hit_quota(""))
verifier("elle plafonne (CADENCE_MAX_S) : on ne s'endort pas indéfiniment", t.cadence == Throttle.CADENCE_MAX_S)
for _ in range(200):
    run(t.succes())
verifier("des succès la ramènent à la cadence du réglage, jamais en dessous", t.cadence == 0.8)
verifier("un succès efface les récidives (la prochaine pause repart de 30 s)",
         run(t.hit_quota(""))[0] == 30.0)

print("\n4. La porte respecte la pause")
t = Throttle()
run(t.hit_quota(""))
ok, raison = run(t.gate())
verifier("pendant la pause, la porte est fermée avec sa raison", ok is False and "429" in raison)
t = Throttle()
ok, raison = run(t.gate())
verifier("sans 429, la porte s'ouvre", ok is True)

print("\n5. _embed_gemini passe le corps du 429 et signale les succès")
corps = src[src.index("async def _embed_gemini("):]
corps = corps[:corps.index("\n# ── Ollama")]
verifier("hit_quota reçoit r.text (sans quoi rien ne se lit)", "hit_quota(r.text)" in corps)
verifier("le journal porte le diagnostic, la pause et la cadence",
         'logger.warning("Gemini 429 (%s) — pause %.0f s, cadence %.1f s' in corps)
verifier("un succès est signalé au garde-fou", "await _gemini_throttle.succes()" in corps)
verifier("les stats exposent la cadence et le dernier 429 (supervision)",
         '"cadence_s"' in src and '"dernier_429"' in src)
config = (BACKEND / "config.py").read_text(encoding="utf-8")
verifier("le lot du worker est ramené à 16", re.search(r"^\s*embedding_worker_batch: int = 16", config, re.M) is not None)

print(f"\n═══ {len(echecs)} échec(s)" + (f" : {', '.join(echecs)}" if echecs else " — tout passe"))
sys.exit(1 if echecs else 0)
