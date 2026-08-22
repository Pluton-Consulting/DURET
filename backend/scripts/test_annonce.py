"""
Banc du détecteur d'annonces — les phrases EXACTES sur lesquelles des tours se
sont arrêtés le 22/08, et les phrases qui ne doivent surtout PAS déclencher.
"""
import sys, pathlib, importlib.util
BACKEND = sys.argv[1] if len(sys.argv) > 1 else "backend"
spec = importlib.util.spec_from_file_location("annonce", pathlib.Path(BACKEND)/"agents"/"annonce.py")
annonce = importlib.util.module_from_spec(spec); spec.loader.exec_module(annonce)
echecs = []
def verifier(nom, cond, detail=""):
    print(f"  {'✓' if cond else '✗'} {nom}" + (f"  → {detail}" if detail and not cond else ""))
    if not cond: echecs.append(nom)
print(f"\n═══ DÉTECTEUR D'ANNONCES — {BACKEND}\n")
print("1. Des promesses, relevées mot pour mot")
for p in ["Je recherche les informations sur ASL Clément Thomas.",
          "Je relance la consultation des clients pour vous donner ce chiffre.",
          "Je retente la consultation de la liste des clients.",
          "Je vais lire les mails de la semaine pour vous les afficher.",
          "Je vais modifier le visuel pour changer les montants gris de la maison en rouge vif.",
          "Je consulte les mails de la semaine.",
          "Je vérifie dans la base et je reviens vers vous."]:
    verifier(f"« {p[:60]} »", annonce.est_une_annonce(p))
print("\n2. Pas des promesses")
for p in ["Voici la liste des clients :", "Souhaitez-vous que je rédige une réponse ?",
          "Je n'ai pas trouvé de client à ce nom. Voulez-vous vérifier l'orthographe ?",
          "Il y a 478 clients en base.", "J'ai besoin du nom du client pour continuer.",
          "Les 28 messages de la semaine sont ci-dessous.", "Bonjour ! Comment puis-je vous aider ?"]:
    verifier(f"« {p[:60]} »", not annonce.est_une_annonce(p))
print(f"\n═══ {len(echecs)} échec(s)" + (f" : {', '.join(echecs)}" if echecs else " — tout passe"))
sys.exit(1 if echecs else 0)
