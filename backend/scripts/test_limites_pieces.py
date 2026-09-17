import base64,unittest
from bureautique.limites_pieces import verifier_lot,taille_base64
class Limites(unittest.TestCase):
 def test_taille_exacte(self):
  for n in range(20):self.assertEqual(taille_base64(base64.b64encode(b'x'*n).decode()),n)
 def test_total_borne(self):
  p={'b64':base64.b64encode(b'x'*(5*1024*1024)).decode()}
  self.assertEqual(verifier_lot([p]*5),25*1024*1024)
  with self.assertRaises(ValueError):verifier_lot([p]*6)
 def test_fichier_borne(self):
  p={'b64':base64.b64encode(b'x'*(10*1024*1024+1)).decode()}
  with self.assertRaises(ValueError):verifier_lot([p])
 def test_encodage_invalide(self):
  with self.assertRaises(ValueError):verifier_lot([{'b64':'abc'}])
unittest.main()
