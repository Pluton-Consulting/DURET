"""
Banc de la RECHERCHE DE MAILS PAR OBJET, ET AVEC ACCENTS (17/09, Duret).

« il y a un mail avec maxime dans l'objet ? » → 5 279 messages (la recherche
portait sur tout le corps) ; « objet : maxime - mémoire technique » → « 'ascii'
codec can't encode character '\\xe9' » : la boîte devenait inconsultable dès qu'un
accent entrait dans la recherche. Exécuté sur le module livré, IMAP doublé.

    python backend/scripts/test_recherche_mail_objet.py backend
"""
import os, sys
from pathlib import Path

BACKEND = Path(sys.argv[1] if len(sys.argv) > 1 else "backend").resolve()
sys.path.insert(0, str(BACKEND))
for k, v in {"DATABASE_URL": "postgresql://x:x@localhost/x", "JWT_SECRET_KEY": "x" * 40, "RESEND_API_KEY": "x"}.items():
    os.environ.setdefault(k, v)
ECHECS = []


def verifier(nom, condition, detail=""):
    print(("  ✓ " if condition else "  ✗ ") + nom + (f"  → {detail}" if detail and not condition else ""))
    if not condition:
        ECHECS.append(nom)


from mail import imap


class FauxIMAP:
    def __init__(self):
        self.appels, self.literal = [], None

    def uid(self, *args):
        # comme imaplib : la ligne de commande doit être ASCII, le littéral part à part
        for a in args:
            if isinstance(a, str):
                a.encode("ascii")
        self.appels.append((args, self.literal))
        self.literal = None
        return "OK", [b"3 7 9"]


c, mots = imap._criteres(None, "objet: maxime - mémoire technique", None)
verifier("« objet: … » cherche dans l'OBJET seul (SUBJECT)", c == "SUBJECT" and mots == "maxime - mémoire technique", f"{c} / {mots}")
verifier("sans préfixe : objet ET corps (TEXT), comme avant", imap._criteres(None, "terrasse bois", None) == ("TEXT", "terrasse bois"))
verifier("« sujet: » et « subject: » valent « objet: »", imap._criteres(None, "Sujet : devis", None)[0] == "SUBJECT" and imap._criteres(None, "subject:devis", None)[0] == "SUBJECT")
verifier("sans recherche : ALL, aucun texte", imap._criteres(None, None, None) == ("ALL", None) and imap._criteres(None, "objet:  ", None) == ("ALL", None))
f = FauxIMAP()
r = imap._uids(f, imap._criteres(None, "objet: maxime - mémoire technique", None))
args, litteral = f.appels[0]
verifier("un texte ACCENTUÉ ne fait plus planter la boîte : littéral UTF-8 + CHARSET", r == [b"3", b"7", b"9"] and "CHARSET" in args and "UTF-8" in args and litteral == "maxime - mémoire technique".encode("utf-8"), str(args))
verifier("la commande finit par le champ cherché (le littéral le suit)", args[-1].endswith("SUBJECT"))
f = FauxIMAP(); imap._uids(f, imap._criteres(None, "maxime", None))
verifier("un texte sans accent reste une commande simple, entre guillemets", f.appels[0][0][-1] == 'TEXT "maxime"' and f.appels[0][1] is None, str(f.appels[0]))
f = FauxIMAP(); imap._uids(f, "ALL")
verifier("les appelants qui passent une chaîne nue marchent toujours", f.appels[0][0][-1] == "ALL")

from mail import lecture
verifier("Gmail : « objet: » devient subject:(…)", "subject:(maxime mémoire)" in lecture._requete_gmail(None, "objet: maxime mémoire"))
verifier("Outlook : « objet: » devient subject: en KQL", "subject:" in str(lecture._params_outlook(10, None, "objet: maxime")))
import asyncio, types
lecture.fournisseur = lambda: "imap"
appels_imap = []
async def faux_lire_imap(boite, dossier, limite, depuis, recherche=None, avant=None, apercu=None, curseur=None):
    appels_imap.append(dossier)
    if dossier in ("recus", "INBOX"): return [], 0
    return [{"objet": "Maxime - Mémoire Technique", "date_iso": "2026-09-17T15:31:00", "de": "x@exemple-sols.fr"}], 1
lecture._lire_imap = faux_lire_imap
imap.dossier_de_tous_les_messages = lambda: "[Gmail]/Tous les messages"
r = asyncio.run(lecture.lire_boite("boite@exemple-sols.fr", "recus", 10, recherche="objet: maxime - mémoire technique"))
verifier("rien en réception : la recherche continue dans tous les messages, et le DIT", r["messages"] and r.get("trouve_hors_reception") == "[Gmail]/Tous les messages" and "Rien en boîte de réception" in r["compte"], str(r.get("compte")))
appels_imap.clear()
r = asyncio.run(lecture.lire_boite("boite@exemple-sols.fr", "recus", 10, recherche="objet: maxime", autorises=["_Maxime"]))
verifier("un profil restreint ne cherche QUE dans ses dossiers ouverts", appels_imap == ["recus", "_Maxime"] and r.get("trouve_hors_reception") == "_Maxime", str(appels_imap))
appels_imap.clear()
asyncio.run(lecture.lire_boite("boite@exemple-sols.fr", "recus", 10, recherche="objet: maxime", autorises=[]))
verifier("réception seule : on ne sort pas de la réception", appels_imap == ["recus"], str(appels_imap))
appels_imap.clear()
asyncio.run(lecture.lire_boite("boite@exemple-sols.fr", "recus", 10))
verifier("sans recherche, rien ne change : la réception seule est lue", appels_imap == ["recus"], str(appels_imap))
skills = (BACKEND / "mail" / "skills.py").read_text(encoding="utf-8")
catalogue = (BACKEND / "skills" / "protocol.py").read_text(encoding="utf-8")
verifier("le geste accepte `objet` et le catalogue le dit au modèle", '"objet: " + str(_dans_objet)' in skills and "dans l'OBJET SEUL" in catalogue and '"recherche", "objet", "avant"' in catalogue)
print(("✗ %d échec(s)" % len(ECHECS)) if ECHECS else "✓ 0 échec")
sys.exit(1 if ECHECS else 0)
