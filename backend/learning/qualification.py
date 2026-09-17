"""Qualification de transformations générées, avec preuves liées au code exact.

Les tests passent exclusivement par l'exécuteur isolé, jamais par eval/exec dans
le backend. Une réussite ne démontre que les cas fournis, pas une exactitude
universelle. Le code natif garde ses tests et son cycle de livraison habituels.
"""
import ast,hashlib,json

AUTORISES={'math','decimal','statistics','datetime','re','json','collections','fractions','itertools','functools','typing','unicodedata','string','copy'}
INTERDITS={'eval','exec','compile','open','input','__import__','globals','locals','getattr','setattr','delattr','vars','breakpoint'}

def verifier_code(code):
    if not isinstance(code,str) or not code.strip() or len(code)>50000:raise ValueError('Code vide ou trop volumineux.')
    arbre=ast.parse(code)
    fonctions=[n for n in arbre.body if isinstance(n,ast.FunctionDef) and n.name=='run']
    if len(fonctions)!=1 or len(fonctions[0].args.args)!=1:raise ValueError('Une fonction synchrone run(data) est requise.')
    for n in ast.walk(arbre):
        if isinstance(n,ast.Import) and any(a.name.split('.')[0] not in AUTORISES for a in n.names):raise ValueError('Import hors des bibliothèques de calcul autorisées.')
        if isinstance(n,ast.ImportFrom) and (n.level or (n.module or '').split('.')[0] not in AUTORISES):raise ValueError('Import externe interdit dans cette transformation.')
        if isinstance(n,ast.Name) and (n.id in INTERDITS or n.id.startswith('__')):raise ValueError('Accès système ou introspection interdite.')
        if isinstance(n,ast.Attribute) and n.attr.startswith('_'):raise ValueError('Accès à un attribut privé interdit.')
    return hashlib.sha256(code.encode()).hexdigest()

def verifier_cas(cas):
    if not isinstance(cas,list) or not 3<=len(cas)<=12:raise ValueError('Fournis de 3 à 12 cas fictifs avec data et attendu, dont un cas limite.')
    if any(not isinstance(c,dict) or not isinstance(c.get('data'),dict) or not isinstance(c.get('attendu'),dict) for c in cas):raise ValueError('Chaque cas exige deux objets JSON : data et attendu.')
    if len({json.dumps(c['data'],sort_keys=True) for c in cas})!=len(cas):raise ValueError('Les entrées des cas doivent être distinctes.')
    if len(json.dumps(cas))>40000:raise ValueError('Les cas fictifs sont trop volumineux.')
    return cas

async def evaluer(nom,code,cas):
    from sandbox.daytona_client import sandbox_client
    sha=verifier_code(code);verifier_cas(cas)
    if sandbox_client.isolement()!='daytona':
        return {'passed':False,'code_sha256':sha,'sandbox':'indisponible','cas':cas,'resultats':[],
                'error':'Exécuteur isolé indisponible : aucun test exécuté, aucune promotion.'}
    resultats=[]
    for c in cas:
        r=await sandbox_client.execute_skill(code,nom,c['data'],max_execution_seconds=15)
        resultats.append({'passed':bool(r.get('ok')) and r.get('output')==c['attendu'],
                          'output':r.get('output'),'error':r.get('error'),'sandbox':r.get('sandbox_type')})
    return {'passed':all(r['passed'] and r['sandbox']=='daytona' for r in resultats),
            'code_sha256':sha,'sandbox':'daytona','cas':cas,'resultats':resultats}

async def enregistrer(nom,bilan):
    from database.connection import get_db
    async with get_db() as c:
        await c.execute('INSERT INTO skill_evaluations(name,code_sha256,passed,sandbox,cas,resultats) VALUES($1,$2,$3,$4,$5::jsonb,$6::jsonb)',nom,bilan['code_sha256'],bilan['passed'],bilan['sandbox'],json.dumps(bilan['cas']),json.dumps(bilan['resultats']))

async def exige_preuve(conn,nom,code):
    sha=verifier_code(code)
    oui=await conn.fetchval("SELECT passed AND sandbox='daytona' AND jsonb_array_length(cas)>=3 FROM skill_evaluations WHERE name=$1 AND code_sha256=$2 ORDER BY cree_le DESC,id DESC LIMIT 1",nom,sha)
    if not oui:raise ValueError('Ce code exact doit réussir au moins trois cas distincts dans l’exécuteur isolé avant validation. Lance la qualification du skill.')


async def constater_execution(nom,code,resultat):
    """Trois erreurs du code mettent le candidat de côté ; pas une panne réseau."""
    erreur=str(resultat.get('error') or '')
    deterministe=any(m in erreur for m in ('Traceback (most recent call last)', 'SyntaxError:', 'ZeroDivisionError:', 'TypeError:', 'NameError:', 'AssertionError:', 'ValueError:'))
    if not resultat.get('ok') and not deterministe:return
    from database.connection import get_db
    async with get_db() as conn:
        if resultat.get('ok'):
            await conn.execute("UPDATE skills SET echecs_consecutifs=0 WHERE name=$1 AND code=$2",nom,code)
        else:
            await conn.execute("UPDATE skills SET echecs_consecutifs=echecs_consecutifs+1, enabled=CASE WHEN echecs_consecutifs>=2 THEN false ELSE enabled END, status=CASE WHEN echecs_consecutifs>=2 THEN 'draft' ELSE status END, motif_quarantaine=CASE WHEN echecs_consecutifs>=2 THEN 'Trois erreurs de code consécutives ; requalifier avant activation' ELSE motif_quarantaine END WHERE name=$1 AND code=$2",nom,code)
