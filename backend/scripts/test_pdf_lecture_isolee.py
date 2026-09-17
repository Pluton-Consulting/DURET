"""PDF réels, arrêt réel du processus lent, et politique OCR conservée."""
import importlib.util, os, pathlib, sys, tempfile, time, unittest
from unittest.mock import patch
from types import SimpleNamespace
BACKEND=pathlib.Path(sys.argv[1] if len(sys.argv)>1 else 'backend').resolve();sys.path.insert(0,str(BACKEND));sys.argv=[sys.argv[0]]
from ingestion import parsers
import fitz

class PDF(unittest.TestCase):
 def setUp(self):
  with fitz.open() as d:
   d.new_page().insert_text((40,40),'Premiere page : chantier et quantites, 32 m2 de carrelage a verifier.')
   d.new_page().insert_text((40,40),'Deuxieme page : 18 metres de plinthes et 12 m2 de faience a verifier.')
   self.brut=d.tobytes()
 def test_texte_sur_toutes_les_pages_sans_ocr(self):
  with patch.object(parsers,'ocr_disponible',return_value=False),patch.object(parsers,'ocr_pdf') as ocr:
   t=parsers.lire_pdf(self.brut)
  self.assertIn('32 m2',t);self.assertIn('18 metres',t);self.assertIn('12 m2',t);ocr.assert_not_called()
 def test_limite_de_pages_conservee(self):
  with patch.object(parsers,'MAX_PAGES_PDF',1):r=parsers._extraire_texte_pdf(self.brut)
  self.assertEqual(r['pages_total'],2);self.assertEqual(r['pages_lues'],1);self.assertNotIn('Deuxieme',r['texte'])
 def test_scan_reste_differe_quand_ocr_interdit(self):
  with fitz.open() as d:d.new_page();brut=d.tobytes()
  jeton=parsers._OCR_PERMIS.set(False)
  try:
   with patch.object(parsers,'ocr_disponible',return_value=True),patch.object(parsers,'ocr_pdf') as ocr:
    with self.assertRaises(parsers.OcrReporte):parsers.lire_pdf(brut)
    ocr.assert_not_called()
  finally:parsers._OCR_PERMIS.reset(jeton)
 def test_moteur_historique_de_secours_lit_un_vrai_pdf(self):
  spec=importlib.util.spec_from_file_location('pdf_worker',BACKEND/'ingestion/pdf_texte.py');mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
  with patch.object(fitz,'open',side_effect=RuntimeError('moteur natif indisponible')):r=mod.extraire(self.brut,300)
  self.assertIn('32 m2',r['texte']);self.assertIn('18 metres',r['texte'])
 def test_delai_termine_effectivement_le_processus(self):
  with tempfile.TemporaryDirectory() as td:
   p=pathlib.Path(td);pid=p/'pid'
   (p/'pdf_texte.py').write_text('import os,time\nfrom pathlib import Path\nPath('+repr(str(pid))+').write_text(str(os.getpid()))\ntime.sleep(30)\n')
   debut=time.monotonic()
   with patch.object(parsers,'__file__',str(p/'parsers.py')),patch.object(parsers,'PDF_TEXTE_DELAI_S',.4):
    with self.assertRaises(parsers.DelaiDepasse):parsers._extraire_texte_pdf(self.brut)
   self.assertLess(time.monotonic()-debut,3)
   self.assertTrue(pid.exists())
   with self.assertRaises(ProcessLookupError):os.kill(int(pid.read_text()),0)
 def test_echeance_deja_depassee_ne_lance_pas_de_processus(self):
  jeton=parsers._ECHEANCE.set(time.monotonic()-1)
  try:
   with patch('subprocess.run') as run:
    with self.assertRaises(parsers.DelaiDepasse):parsers._extraire_texte_pdf(self.brut)
    run.assert_not_called()
  finally:parsers._ECHEANCE.reset(jeton)

unittest.main(verbosity=2)
