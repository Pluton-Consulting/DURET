"""Traçabilité des mesures extraites : une citation ne vaut pas validation du plan."""
import hashlib,math

def controler(data,analyse,state):
    if not isinstance(data,dict):return None
    preuves=[]
    for brut in (data.get('preuves_mesures') or [])[:100]:
        if not isinstance(brut,dict):continue
        citation=str(brut.get('citation') or '').strip()
        nature=brut.get('nature') if brut.get('nature') in ('lue','estimee','non_mesurable') else 'non_mesurable'
        cadre=brut.get('cadre_normalise')
        if not (isinstance(cadre,list) and len(cadre)==4 and all(isinstance(x,(float,int)) and not isinstance(x,bool) and math.isfinite(x) and 0<=x<=1 for x in cadre) and cadre[0]<cadre[2] and cadre[1]<cadre[3]):cadre=None
        page=brut.get('page');page=page if isinstance(page,int) and not isinstance(page,bool) and page>0 else None
        preuves.append({'poste':str(brut.get('poste') or '')[:300],'valeur':brut.get('valeur'),'unite':str(brut.get('unite') or '')[:30],
            'nature':nature,'citation':citation[:1500],'citation_presente_dans_analyse':bool(citation and citation in analyse),
            'fichier':str(brut.get('fichier') or state.get('attachment_name') or '')[:500], 'page':page,'cadre_normalise':cadre,
            'hypothese':str(brut.get('hypothese') or '')[:1000], 'validation_humaine_requise':True})
    return {**data,'preuves_mesures':preuves,'provenance':{'analyse_sha256':hashlib.sha256(analyse.encode()).hexdigest(),
        'verification':'Extraction de l’analyse visuelle, aucune mesure certifiée automatiquement.',
        'limites':'Les quantités sans preuve restent à vérifier. Une citation dans l’analyse ne prouve pas sa présence exacte sur le plan. Vérifier cote, page, unité, échelle et hypothèses avant utilisation.'}}
