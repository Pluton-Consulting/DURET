"""Contrôle après déploiement : outils, stockage documentaire et pagination.

N'appelle aucun fournisseur IA ni connecteur métier. Le document de contrôle
est temporaire. La base documentaire additive est initialisée si nécessaire.
"""
import os,sys,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from skills.registre import collecte
from ressources.dossiers import base
from bureautique.document_modele import verifier_pages
from docx import Document
attendus={'lister_sources_dossier','lire_source_dossier','chercher_source_dossier','ajouter_source_dossier',
          'composer_document_dossier','produire_quantitatif','analyser_plan_source','suspendre_redaction','reprendre_redaction'}
r=collecte();manquants=attendus-r.keys()
assert not manquants,'Outils absents : '+', '.join(sorted(manquants))
assert all(r[n].effet in ('lecture','ecriture_interne') for n in attendus),'Effet de skill incohérent'
with base() as c:assert c.execute('SELECT 1 FROM sources_dossier LIMIT 0').description
with tempfile.TemporaryDirectory(prefix='controle-documents-') as d:
 p=Path(d)/'controle.docx';doc=Document();doc.add_paragraph('Contrôle temporaire du moteur de documents.');doc.save(p)
 pages=verifier_pages(p,1);assert pages['conforme'],pages['note']
from config import settings
role=getattr(settings,'role_processus','complet')
print('OK : neuf outils, base documentaire accessible, Word paginé en une page.')
print('Rôle du processus :',role)
if role not in ('complet','fond'):print('À vérifier : le worker documentaire doit tourner dans le processus de fond partageant DOCUMENTS_DIR.')
