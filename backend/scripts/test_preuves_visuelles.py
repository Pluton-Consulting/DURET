"""Une mesure structurée garde sa citation et ses limites, sans certification inventée."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(sys.argv[1]).resolve()))
from agents.preuves_visuelles import controler
r=controler({'surfaces_m2':{'séjour':35},'preuves_mesures':[{'poste':'séjour','valeur':35,'unite':'m²','nature':'estimee','citation':'35 m²','page':1,'cadre_normalise':[.1,.2,.4,.6]}]},'Séjour estimé à 35 m²',{'attachment_name':'plan.pdf'})
p=r['preuves_mesures'][0]
assert r['surfaces_m2']['séjour']==35 and p['citation_presente_dans_analyse'] and p['validation_humaine_requise']
r=controler({'preuves_mesures':[{'citation':'inventée','nature':'certifiee','page':-1,'cadre_normalise':[0,0,4,5]}]},'Analyse',{})
p=r['preuves_mesures'][0];assert not p['citation_presente_dans_analyse'] and p['nature']=='non_mesurable' and p['page'] is None and p['cadre_normalise'] is None
print('✓ Données conservées ; citation traçable, mesure estimée explicite, fausse preuve et cadre invalide écartés')
