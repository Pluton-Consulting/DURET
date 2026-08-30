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

print("\n3. La livraison fantôme du 30/08 — prétendre AU PASSÉ, sans fichier")
for p in ["Voici le document avec toutes les informations de l'entreprise.",
          "C'est bon, le fichier est téléchargeable.",
          "Le document Word a été créé avec les informations demandées.",
          "J'ai créé le document Word avec toutes les infos de l'entreprise.",
          "Le rapport est prêt, vous pouvez le télécharger."]:
    verifier(f"« {p[:60]} »", annonce.pretend_avoir_livre(p))
print("\n4. Pas des livraisons fantômes")
for p in ["Voici la liste des devis du mois :",          # un tableau à l'écran
          "Je vais créer le document.",                   # le futur : annonce
          "Voulez-vous que je crée le document ?",
          "Il est disponible mardi pour le rendez-vous.",  # une personne, pas un fichier
          "Je l'ai fait suivre à la comptabilité.",
          "Le devis de M. Martin est de 3 200 euros."]:
    verifier(f"« {p[:60]} »", not annonce.pretend_avoir_livre(p))

print("\n5. La demande qui réclame un fichier")
for p in ["fais moi un word avec toutes les infos de l'entreprise",
          "produis ce document",
          "crée un excel des noms clients avec mon mail",
          "génère un pdf du compte rendu",
          "prépare-moi un rapport Word sur le chantier"]:
    verifier(f"« {p[:60]} »", annonce.demande_une_production(p))
print("\n6. Les demandes qui n'en réclament pas")
for p in ["remontre-moi la liste des fournisseurs",
          "montre-moi le document d'hier",
          "combien de devis en 2026 ?",
          "sors-moi la liste des clients",
          "envoie un mail à Jean pour confirmer le rendez-vous"]:
    verifier(f"« {p[:60]} »", not annonce.demande_une_production(p))

print(f"\n═══ {len(echecs)} échec(s)" + (f" : {', '.join(echecs)}" if echecs else " — tout passe"))
sys.exit(1 if echecs else 0)
