"""Chercher les références de la maison avant de choisir comment produire un document."""
import re
from skills.registre import Declaration

async def preparer(data,user):
    from skills.trames import travail_en_cours
    from database.connection import get_db
    demande=str(data.get('demande') or '').strip()
    if not demande:raise ValueError('Précise le type de document à préparer.')
    fil=data.get('_fil')
    reference=travail_en_cours(user,fil)
    mots=[m.casefold() for m in re.findall(r"[\wà-ÿ-]{3,}",demande) if m.casefold() not in {'une','des','pour','avec','dans','les','document','prépare','preparer','créer','nouveau'}][:12]
    async with get_db() as c:
        lignes=await c.fetch("SELECT nom,genre,description,type_fichier FROM trames WHERE actif AND genre='document' AND lower(nom||' '||coalesce(description,'')) LIKE ANY($1::text[]) ORDER BY nom LIMIT 12",['%'+m+'%' for m in mots] or ['%'])
    resultat={'ok':True,'reference_du_fil':reference,'trames_candidates':[dict(r) for r in lignes], 'exhaustive':False}
    if not lignes and not reference:
        from skills.executor import execute_skill
        recherche=await execute_skill('rechercher_documents',{'requete':'modèle '+demande,'limite':5},user_id=str(user.id),user=user)
        resultat['recherche_sources']=recherche.get('output');resultat['recherche_aboutie']=bool(recherche.get('ok'))
    resultat['a_faire']=("Réutilise la référence explicitement choisie si elle correspond à cette demande. Examine les trames candidates avant de choisir ; plusieurs candidats ne prouvent pas une préférence. Pour une trame, utiliser_trame ; pour un fichier trouvé, reproduire_document sans remplacements permet de lire sa structure, puis avec les remplacements de produire une copie fidèle. Ne recrée pas une présentation existante avec creer_document. Si aucun modèle adapté n’est accessible, indique la limite et crée le document demandé avec la charte ; ne prétends pas avoir copié un modèle absent. Les références externes se rouvrent avec les droits actuels.")
    return resultat

SKILLS={'preparer_document_maison':Declaration(preparer,'Avant de produire un document de la maison, retrouver la référence du fil, chercher les trames du même type puis les modèles dans la mémoire et les sources autorisées. Rend des candidats réels et la manière de les réutiliser, sans inventer un style.',requis=['demande'],effet='lecture',libelle='je retrouve le modèle de document adapté')}
