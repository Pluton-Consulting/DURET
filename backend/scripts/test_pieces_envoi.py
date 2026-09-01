"""
Banc « joindre, insérer une image, signer » — 01/09.

Noa, journaux de production à l'appui : « les pièces jointes ne fonctionnent
pas, il faut pouvoir envoyer des pièces jointes de tout format, insérer des
images, récupérer et appliquer les signatures ». L'assistant le disait lui-même,
mot pour mot : « Je ne peux pas joindre directement un fichier à un email via
mes actions », et « les corps contiennent des références cid: internes, sans
fichier rattachable ».

Trois causes, toutes lues dans le code livré d'avant :
  · `_message_graph` ne portait AUCUNE clé `attachments` ;
  · `_mime_gmail` fabriquait un `MIMEText`, mono-partie PAR CONSTRUCTION ;
  · `lecture.py` JETAIT les pièces `isInline` — c'est-à-dire, précisément, les
    images d'une signature.

Ce banc exerce les constructeurs (purs), la reconnaissance des références, la
découpe d'une signature et son apposition — sans base, sans réseau, sans
qu'aucun message ne parte.
"""
import ast
import base64
import importlib.util
import pathlib
import re
import sys
import types

BACKEND = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "backend")
echecs = []


def verifier(nom, cond, detail=""):
    print(f"  {'✓' if cond else '✗'} {nom}" + (f"  → {detail}" if detail and not cond else ""))
    if not cond:
        echecs.append(nom)


def extraire(chemin, noms, espace=None):
    """Les définitions du module LIVRÉ, sans importer ses dépendances."""
    espace = espace if espace is not None else {}
    arbre = ast.parse(pathlib.Path(chemin).read_text(encoding="utf-8"))
    gardes = []
    for n in arbre.body:
        if isinstance(n, ast.ImportFrom) and n.module == "__future__":
            gardes.append(n)
        elif isinstance(n, (ast.Import, ast.ImportFrom)):
            continue
        elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in noms:
            gardes.append(n)
        elif isinstance(n, (ast.Assign, ast.AnnAssign)):
            cibles = (n.targets if isinstance(n, ast.Assign) else [n.target])
            if any(isinstance(c, ast.Name) and c.id in noms for c in cibles):
                gardes.append(n)
    exec(compile(ast.Module(body=gardes, type_ignores=[]), str(chemin), "exec"), espace)
    manquants = [x for x in noms if x not in espace]
    assert not manquants, f"absent du module livré : {manquants}"
    return espace


print(f"\n═══ PIÈCES JOINTES, IMAGES EN LIGNE, SIGNATURE — {BACKEND.resolve().parent}\n")

# ── 1. Les constructeurs Graph ───────────────────────────────────────────
exp = extraire(BACKEND / "mail" / "expedition.py",
               {"_adresses", "_piece_graph", "_message_graph", "_mime_gmail",
                "octets_des_pieces", "SEUIL_TELEVERSEMENT", "TRONCON",
                "_JETON_ORPHELIN", "porte_un_jeton"},
               {"re": re, "base64": base64})

PDF = b"%PDF-1.4 faux devis"
charge = exp["_message_graph"]("client@x.fr", "Devis", "Bonjour", None,
                               [{"nom": "Devis été.pdf", "mime": "application/pdf",
                                 "octets": PDF}])
piece = charge["message"]["attachments"][0]
verifier("Graph : la clé `attachments` existe enfin",
         len(charge["message"]["attachments"]) == 1)
verifier("Graph : le type de pièce est celui que l'API attend",
         piece["@odata.type"] == "#microsoft.graph.fileAttachment")
verifier("Graph : le contenu est du base64 STANDARD, décodable tel quel",
         base64.b64decode(piece["contentBytes"]) == PDF)
verifier("Graph : le nom accentué survit", piece["name"] == "Devis été.pdf")
verifier("Graph : sans image en ligne, le corps reste du TEXTE",
         charge["message"]["body"]["contentType"] == "Text")
verifier("Graph : le message envoyé se range toujours dans les envoyés",
         charge["saveToSentItems"] is True)

avec_html = exp["_message_graph"]("c@x.fr", "O", "corps", None,
                                  [{"nom": "logo.png", "mime": "image/png",
                                    "octets": b"PNG", "inline": True,
                                    "content_id": "logo@sig"}],
                                  html="<html><img src='cid:logo@sig'></html>")
verifier("Graph : une image DANS le corps fait passer le corps en HTML",
         avec_html["message"]["body"]["contentType"] == "HTML")
verifier("Graph : l'image en ligne porte isInline ET son contentId",
         avec_html["message"]["attachments"][0]["isInline"] is True
         and avec_html["message"]["attachments"][0]["contentId"] == "logo@sig")
verifier("Graph : sans pièce, aucune clé `attachments` parasite",
         "attachments" not in exp["_message_graph"]("a@b.fr", "o", "c")["message"])

# ── 2. Le constructeur Gmail : la structure MIME ─────────────────────────
brut = base64.urlsafe_b64decode(exp["_mime_gmail"](
    "moi@x.fr", "client@x.fr", "Devis été", "Bonjour", ["copie@x.fr"],
    [{"nom": "Devis été.pdf", "mime": "application/pdf", "octets": PDF},
     {"nom": "logo.png", "mime": "image/png", "octets": b"PNG",
      "inline": True, "content_id": "logo@sig"}],
    html="<html><img src='cid:logo@sig'>Bonjour</html>"))
import email as _email  # noqa: E402
message = _email.message_from_bytes(brut)
verifier("Gmail : la racine porte les pièces jointes (`mixed`)",
         message.get_content_subtype() == "mixed")
parties = list(message.walk())
sous_types = [p.get_content_type() for p in parties]
verifier("Gmail : le corps et son image vivent DANS un `related`",
         "multipart/related" in sous_types)
verifier("Gmail : l'image en ligne n'est pas remontée au niveau des pièces",
         next(p for p in parties if p.get_content_type() == "image/png")
         .get("Content-Disposition", "").startswith("inline"))
verifier("Gmail : le Content-ID est ENTRE CHEVRONS dans l'en-tête",
         next(p for p in parties if p.get_content_type() == "image/png")
         .get("Content-ID") == "<logo@sig>")
verifier("Gmail : le corps HTML cite le cid SANS chevrons",
         "cid:logo@sig" in next(p for p in parties
                                if p.get_content_type() == "text/html")
         .get_payload(decode=True).decode())
pdf = next(p for p in parties if p.get_content_type() == "application/pdf")
verifier("Gmail : la pièce est décodable à l'identique",
         pdf.get_payload(decode=True) == PDF)
verifier("Gmail : le nom accentué traverse l'encodage RFC 2231",
         "été" in str(pdf.get_filename() or ""))
# L'objet accentué est encodé RFC 2047 dans l'en-tête : c'est CORRECT, et
# c'est ce qu'on veut vérifier — qu'il se décode à l'identique.
from email.header import decode_header, make_header  # noqa: E402
verifier("Gmail : la copie est posée, l'objet accentué se décode à l'identique",
         message["Cc"] == "copie@x.fr"
         and str(make_header(decode_header(message["Subject"]))) == "Devis été")
sans = _email.message_from_bytes(base64.urlsafe_b64decode(
    exp["_mime_gmail"]("a@x.fr", "b@x.fr", "o", "corps")))
verifier("Gmail : sans pièce, le message reste simple (aucun multipart inutile)",
         sans.get_content_type() == "text/plain")

# ── 3. Le poids, et le chemin des pièces lourdes ─────────────────────────
verifier("le poids des pièces se compte",
         exp["octets_des_pieces"]([{"octets": b"x" * 10}, {"octets": b"y" * 5}]) == 15)
verifier("le seuil de bascule et le tronçon respectent les bornes de Graph",
         exp["SEUIL_TELEVERSEMENT"] <= 3 * 1024 * 1024
         and exp["TRONCON"] % (320 * 1024) == 0)
source = (BACKEND / "mail" / "expedition.py").read_text(encoding="utf-8")
verifier("au-delà du seuil, on passe par un BROUILLON téléversé",
         "_envoyer_par_brouillon" in source
         and "createUploadSession" in source and "Content-Range" in source)
verifier("l'autorisation qui manquerait est NOMMÉE, pas laissée en 403 nu",
         "Mail.ReadWrite" in source)
verifier("un message trop lourd dit quoi faire (déposer, envoyer le lien)",
         "413" in source and "Drive" in source)

# ── 4. La reconnaissance des références ──────────────────────────────────
att = extraire(BACKEND / "mail" / "attaches.py",
               {"RE_VISUEL", "RE_PIECE", "RE_DOCUMENT", "MAX_PIECE", "MAX_TOTAL",
                "MAX_NOMBRE", "_mime_du_nom", "_designations"},
               {"re": re, "mimetypes": __import__("mimetypes")})
verifier("une clé d'image se reconnaît, avec ou sans son url",
         att["RE_VISUEL"].match("a1b2c3d4e5f6a7b8c9d0e1f2")
         and att["RE_VISUEL"].match("/api/visuels/a1b2c3d4e5f6a7b8c9d0e1f2"))
verifier("une ref de pièce (16 hexa) ne se confond pas avec une clé (24)",
         att["RE_PIECE"].match("a1b2c3d4e5f6a7b8")
         and not att["RE_PIECE"].match("a1b2c3d4e5f6a7b8c9d0e1f2"))
verifier("un jeton de document se reconnaît, url comprise",
         att["RE_DOCUMENT"].match("/api/documents/" + "A" * 32))
d = att["_designations"]
verifier("le modèle peut écrire une chaîne, une liste ou un dict",
         d("abc") == [{"ref": "abc", "nom": ""}]
         and d(["a", "b"])[1]["ref"] == "b"
         and d({"ref": "x", "nom": "Devis.pdf"})[0]["nom"] == "Devis.pdf")
verifier("les alias d'un dict sont acceptés (cle, jeton, url, fichier)",
         d({"cle": "k"})[0]["ref"] == "k" and d({"url": "u"})[0]["ref"] == "u")
verifier("le type MIME se devine du nom, sans jamais lever",
         att["_mime_du_nom"]("a.pdf") == "application/pdf"
         and att["_mime_du_nom"]("") == "application/octet-stream")
verifier("les bornes sont posées : 10 pièces, 20 Mo, 22 Mo au total",
         att["MAX_NOMBRE"] == 10 and att["MAX_PIECE"] == 20 * 1024 * 1024
         and att["MAX_TOTAL"] > att["MAX_PIECE"])

src_att = (BACKEND / "mail" / "attaches.py").read_text(encoding="utf-8")
verifier("chaque forme porte SA vérification de droits (aucun chemin de fichier)",
         "chemin_fichier" in src_att and "piece_connue" in src_att
         and "from outils.nas import octets" in src_att and "open(" not in
         src_att.split("async def resoudre")[0].replace(
             'open(chemin, "rb")', ""))
verifier("une pièce impossible est REFUSÉE AVEC SA RAISON, jamais ignorée",
         "refusees.append" in src_att and "raison" in src_att)
verifier("`resoudre` ne lève jamais : un refus est une donnée",
         "noqa: BLE001 — un refus est une donnée" in src_att)

# ── 5. Le skill refuse en bloc, et le dit ────────────────────────────────
sk = (BACKEND / "mail" / "skills.py").read_text(encoding="utf-8")
verifier("une pièce refusée ARRÊTE l'envoi (pas d'envoi amputé en silence)",
         "rien n'a été envoyé" in sk)
verifier("le NOM d'une pièce est soumis à la règle du jeton orphelin",
         'porte_un_jeton(p["nom"])' in sk)
verifier("les alias de paramètre sont acceptés (le piège de `url`, 30/08)",
         'data.get("pieces_jointes")' in sk and 'data.get("fichiers")' in sk)
verifier("le compte rendu NOMME les pièces parties",
         "en pièce jointe" in sk)
proto = (BACKEND / "skills" / "protocol.py").read_text(encoding="utf-8")
verifier("le catalogue déclare `pieces` et `signature` en optionnels",
         '["mailbox", "cc", "pieces", "signature"]' in proto)
verifier("le catalogue interdit d'inventer une référence ou d'écrire un chemin",
         "N'invente JAMAIS une " in proto and "chemin de fichier" in proto)
a1 = (BACKEND / "agents" / "agent1.py").read_text(encoding="utf-8")
verifier("l'aperçu de validation MONTRE les pièces avant le clic",
         "Pièces jointes : " in a1.split("_apercu_avant_accord")[-1])

# ── 6. Les images EN LIGNE ne sont plus jetées ───────────────────────────
lec = (BACKEND / "mail" / "lecture.py").read_text(encoding="utf-8")
verifier("Graph : le contentId est demandé au $select",
         "isInline,contentId" in lec)
verifier("Graph : plus aucun filtre ne jette les pièces isInline",
         'if not p.get("isInline")' not in lec)
verifier("Graph : le corps HTML est récupéré (la seule forme qui porte les cid:)",
         'fiche["corps_html"] = corps_html' in lec)
verifier("Gmail : les en-têtes de partie sont lus (Content-ID, disposition)",
         "content-disposition" in lec and "content-id" in lec)
verifier("Gmail : une image en ligne SANS nom de fichier est retenue",
         'nom or (inline and not mime.startswith("text/")' in lec)
verifier("Gmail : le corps HTML existe aussi de ce côté", "_html_gmail" in lec)
verifier("les pièces EN LIGNE ne sont pas comptées comme des pièces jointes",
         "ordinaires = [p for p in brutes if not p.get(\"inline\")]" in lec)
verifier("elles ne sont LUES que sur demande (`inline`), pas à chaque mail",
         "a_lire = brutes if inline else ordinaires" in lec)

pieces_py = (BACKEND / "mail" / "pieces.py").read_text(encoding="utf-8")
esp = extraire(BACKEND / "mail" / "pieces.py", {"cids_du_html", "_RE_CID"},
               {"re": re})
cids = esp["cids_du_html"]
verifier("les cid: se lisent avec guillemets doubles, simples ou espaces",
         cids('<img src="cid:a@1"> <img src=\'cid:b@2\'> <img src = cid:c@3 >')
         == ["a@1", "b@2", "c@3"])
verifier("CID en majuscules reconnu, doublons écartés",
         cids('<img SRC="CID:x@1"><img src="cid:x@1">') == ["x@1"])
verifier("un corps sans image rend une liste vide", cids("<p>bonjour</p>") == [])
verifier("le rapprochement marque les pièces AFFICHÉES dans le corps",
         'p["dans_le_corps"] = True' in lec)

# ── 7. La signature ──────────────────────────────────────────────────────
sig = extraire(BACKEND / "mail" / "signature.py",
               {"separer", "en_texte", "_BALISES", "_SEPARATEUR", "_POLITESSE",
                "_CONTACT", "_RE_BALISE", "_RE_BR", "MAX_SIGNATURE_HTML",
                "MAX_IMAGE_SIGNATURE", "MAX_IMAGES"},
               {"re": re, "_html": __import__("html")})
separer = sig["separer"]
corps, signature = separer(
    '<p>Bonjour,</p><div class="gmail_signature">Jean Dupont<br>06 12 34 56 78</div>')
verifier("Gmail balise sa signature : on s'en sert",
         "Jean Dupont" in signature and "Bonjour" in corps
         and "Jean Dupont" not in corps)
corps, signature = separer('<p>Bonjour</p><div id="Signature">Marie<br>Directrice</div>')
verifier("Outlook Web balise la sienne aussi", "Marie" in signature)
corps, signature = separer("Bonjour<br>--<br>Paul, 05 56 00 00 00")
verifier("le séparateur normalisé « -- » est reconnu",
         "Paul" in signature and "Bonjour" in corps)
verifier("le DERNIER séparateur fait foi, pas le premier",
         "final" in separer("a<br>--<br>b<br>--<br>final")[1])
corps, signature = separer(
    "<p>Le devis est prêt.</p><p>Cordialement,<br>Luc Martin<br>05 56 11 22 33</p>")
verifier("à défaut de repère, un bloc politesse + contact est un repli",
         "Luc Martin" in signature)
verifier("RIEN de reconnu → aucune coupure inventée",
         separer("<p>Bonjour, voici le devis.</p>") == ("", "")
         and separer("") == ("", ""))
verifier("le texte de repli garde les lignes et retire les balises",
         sig["en_texte"]("<b>Jean</b><br>06 12") == "Jean\n06 12")
verifier("une signature est bornée (elle ne peut pas devenir un document)",
         sig["MAX_SIGNATURE_HTML"] <= 20_000
         and sig["MAX_IMAGE_SIGNATURE"] <= 1024 * 1024)

src_sig = (BACKEND / "mail" / "signature.py").read_text(encoding="utf-8")
# Le contrôle porte sur le CODE, pas sur la prose : le docstring cite
# `llm/cles.py` pour expliquer son cache, ce qui est le contraire d'un appel.
_code_sig = "\n".join(l for l in src_sig.splitlines()
                      if not l.strip().startswith("#"))
verifier("LA SIGNATURE NE PASSE JAMAIS PAR UN MODÈLE",
         not re.search(r"(ainvoke|appeler_llm|from llm|import llm|Tier\.)", _code_sig))
verifier("la RÉCURRENCE fait foi : ce qui revient à l'identique",
         "candidats" in src_sig and 'entree["n"] += 1' in src_sig)
verifier("les octets vivent en base ET au dépôt (survivre à un volume recréé)",
         "octets_b64" in src_sig and "deposer_octets" in src_sig)
verifier("`signature: false` la retire pour un message",
         "demandee is False" in src_sig)
verifier("sans image, on n'invente pas un corps HTML",
         'if not images:' in src_sig)
verifier("le corps de l'assistant est ÉCHAPPÉ avant d'entrer dans le HTML",
         "_html.escape(bloc)" in src_sig)
verifier("asyncpg rend le JSONB en CHAÎNE : c'est prévu (leçon du 22/08)",
         "isinstance(images, str)" in src_sig)

mig = BACKEND / "database" / "migrations" / "030_signatures_mail.sql"
verifier("migration 030 : la table, idempotente",
         mig.exists()
         and "CREATE TABLE IF NOT EXISTS mail_signatures" in mig.read_text(encoding="utf-8"))
verifier("les deux gestes sont déclarés aux QUATRE endroits",
         '"apprendre_signature": apprendre_signature' in sk
         and '"apprendre_signature": "ecriture_interne"' in sk
         and '"ma_signature": "lecture"' in sk
         and '"apprendre_signature": (' in proto
         and '"apprendre_signature": "j\'apprends la signature"'
         in (BACKEND / "agents" / "journal.py").read_text(encoding="utf-8"))
verifier("la signature relue s'affiche MÉCANIQUEMENT (bloc garanti)",
         '"bloc_garanti": True' in sk.split("async def _fiche_signature")[1][:3000])
verifier("le prompt de rédaction interdit d'écrire une signature",
         "N'ÉCRIS PAS de signature" in sk)
verifier("le catalogue dit qu'une signature ne se rédige pas",
         "elle ne se redige pas" in proto)

# ── 8. Le NAS sait rendre des octets ─────────────────────────────────────
nas = (BACKEND / "outils" / "nas.py").read_text(encoding="utf-8")
verifier("`octets()` existe, pendant exact de `drive.octets()` chez le jumeau",
         "async def octets(" in nas)
verifier("le binaire est rapatrié tel quel, sans passer par l'extracteur de "
         "texte (qui perdrait justement ce qu'on veut envoyer)",
         "_telecharger(client, base, sid, chemin)" in nas
         # Le CODE, pas la prose : le docstring cite `_lire_ouvert` pour dire
         # justement qu'on ne passe PAS par lui.
         and "await _lire_ouvert" not in nas.split("async def octets(")[1][:2000])
verifier("le périmètre est appliqué par `verifier()`, comme partout ailleurs",
         "verifier(" in nas.split("async def octets(")[1][:2000])
verifier("un fichier trop lourd pour un message est refusé en le DISANT",
         "MAX_OCTETS_PIECE" in nas)

print(f"\n{'═' * 70}\n{'✗ ' + str(len(echecs)) + ' échec(s) : ' + ', '.join(echecs) if echecs else '✓ 0 échec'}\n")
sys.exit(1 if echecs else 0)
