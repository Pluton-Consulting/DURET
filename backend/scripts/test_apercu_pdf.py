"""
Banc « L'APERÇU PDF NE CHARGE PLUS À L'INFINI » (08/09).

Relevé de Noa sur Duret : « les PDF se mettent bien dans le chat et sont
téléchargeables, mais leur prévisualisation charge à l'infini ».

LE MÉCANISME, lu dans le moteur livré (`@embedpdf/engines`) : le worker est
créé depuis un Blob et reçoit l'adresse du binaire ; si le chargement échoue
dans le worker, il répond `{ type: "wasmError" }` SANS identifiant de tâche,
et `handleWorkerMessage` l'écarte comme « tâche inconnue ». La promesse du
moteur ne se règle jamais : `!engine` → « chargement » pour toujours. Toute
panne devient donc invisible — adresse relative (un worker Blob a pour base
une adresse `blob:` qui ne résout pas « /pdfium/… »), 404, mauvais MIME,
réseau lent sur le VPN.

CE QUE CE BANC PROUVE (contrat sur le code livré, aucun navigateur ici — il
le dit) : le binaire est dans le dépôt et dans l'image ; le chargeur passe une
adresse ABSOLUE, VÉRIFIE le binaire avant (404, MIME), pose un CHIEN DE GARDE
qui rejette avec un message, et oublie l'échec pour permettre un nouvel
essai ; la visionneuse dit la cause en français. Tombe sur la version
d'avant. Le piège du moteur lui-même est vérifié sur le paquet installé.
"""
import pathlib
import re
import sys

BACKEND = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "backend").resolve()
FRONTEND = BACKEND.parent / "frontend"
echecs = []


def verifier(nom, cond, detail=""):
    print(f"  {'✓' if cond else '✗'} {nom}" + (f"  → {detail}" if detail and not cond else ""))
    if not cond:
        echecs.append(nom)


print(f"\n═══ L'APERÇU PDF NE CHARGE PLUS À L'INFINI — {FRONTEND.parent}\n")

wasm = FRONTEND / "public" / "pdfium" / "pdfium.wasm"
verifier("le binaire pdfium.wasm est dans le dépôt (public/pdfium), 4,6 Mo",
         wasm.exists() and wasm.stat().st_size > 4_000_000)
dockerfile = (FRONTEND / "Dockerfile").read_text(encoding="utf-8")
verifier("l'image copie public/ (le binaire voyage avec l'application)",
         "COPY --from=builder /app/public ./public" in dockerfile)

moteur = FRONTEND / "node_modules" / "@embedpdf" / "engines" / "dist" / "lib" / "pdfium" / "web" / "worker-engine.js"
if moteur.exists():
    src = moteur.read_text(encoding="utf-8")
    verifier("le piège existe dans le paquet installé : « wasmError » est émis par le worker…",
             'type: "wasmError"' in src)
    verifier("…et n'est traité NULLE PART sur le fil principal (une seule occurrence : l'émission)",
             src.count("wasmError") == 1)
    verifier("…parce que le worker est créé depuis un Blob (base `blob:`, adresse relative impossible)",
             "new Worker(" in src and "URL.createObjectURL(new Blob(" in src)
else:
    print("  (paquet @embedpdf non installé ici : le piège du moteur n'est pas revérifié)")

chargeur = (FRONTEND / "lib" / "pdf-thumbnail-utils.ts").read_text(encoding="utf-8")
verifier("le chargeur passe une adresse ABSOLUE au moteur (new URL(…, window.location.origin))",
         "new URL(PDFIUM_WASM_URL, window.location.origin).href" in chargeur
         and "createPdfiumEngine(url, {})" in chargeur)
verifier("il VÉRIFIE le binaire avant (HEAD) : 404 et MIME se disent avec leur cause",
         'method: "HEAD"' in chargeur and "introuvable (réponse" in chargeur
         and 'au lieu de application/wasm' in chargeur)
verifier("un chien de garde rejette la promesse au lieu de la laisser pendre",
         "DELAI_MOTEUR_MS" in chargeur and "Promise.race([createPdfiumEngine(url, {}), chienDeGarde])" in chargeur
         and "n'a pas répondu en" in chargeur)
verifier("un échec n'est pas gravé : la promesse partagée est remise à zéro pour un nouvel essai",
         re.search(r"\.catch\(\(e\) => \{\s*(//[^\n]*\n\s*)?sharedEnginePromise = null\s*\n\s*throw e", chargeur) is not None)
verifier("le délai est raisonnable pour un VPN (30 à 90 s)",
         30_000 <= int(re.search(r"DELAI_MOTEUR_MS = (\d[\d_]*)", chargeur).group(1).replace("_", "")) <= 90_000)

visionneuse = (FRONTEND / "components" / "extend" / "pdf-viewer.tsx").read_text(encoding="utf-8")
verifier("la visionneuse dit la cause en FRANÇAIS, et que le fichier reste téléchargeable",
         "Le moteur PDF n'a pas pu être chargé (${engineError.message})" in visionneuse
         and "Unable to load the PDF engine." not in visionneuse)
verifier("l'erreur du moteur est bien un état rendu (pas seulement journalisé)",
         "if (engineError) {" in visionneuse and 'state="error"' in visionneuse)

print("\n  (aucun navigateur ici : l'aperçu RENDU se juge à l'écran — ouvrir un PDF du serveur,"
      " l'aperçu doit apparaître, ou un message dire pourquoi)")
print(f"\n{'═' * 72}")
if echecs:
    print(f"✗ {len(echecs)} échec(s) : " + ", ".join(echecs))
    sys.exit(1)
print("✓ 0 échec")
