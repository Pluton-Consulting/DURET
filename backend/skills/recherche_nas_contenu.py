"""Recherche de contenu NAS reprenable : parcours et lectures avec les droits actuels."""
import asyncio,json,os,secrets,sqlite3,time,unicodedata
from contextlib import closing
from skills.registre import Declaration


def _db():
    from ressources.registre import _chemin
    p=_chemin().parent/'recherches-nas.sqlite3';p.parent.mkdir(parents=True,exist_ok=True)
    fd=os.open(p,os.O_CREAT|os.O_RDWR,0o600);os.close(fd)
    c=sqlite3.connect(p,timeout=5);c.execute('CREATE TABLE IF NOT EXISTS scans(ref TEXT PRIMARY KEY,user_id TEXT NOT NULL,etat TEXT NOT NULL)');return c

def _lire(ref,uid):
    with closing(_db()) as c:r=c.execute('SELECT etat FROM scans WHERE ref=? AND user_id=?',(ref,str(uid))).fetchone()
    if not r:raise ValueError('Recherche inconnue ou appartenant à une autre personne.')
    return json.loads(r[0])

def _sauver(ref,uid,etat):
    with closing(_db()) as c,c:c.execute('INSERT INTO scans VALUES(?,?,?) ON CONFLICT(ref) DO UPDATE SET etat=excluded.etat',(ref,str(uid),json.dumps(etat)))

def _normaliser(texte):return ''.join(c for c in unicodedata.normalize('NFKD',texte.casefold()) if not unicodedata.combining(c))

async def chercher(data,user):
    from nas.acces import verifier_role,verifier,connexion,_lister_ouvert,_lire_ouvert
    from stockage.processus import VerrouProcessus,Occupe
    from skills.chiffres_sources import textes
    verifier_role(user)
    ref=str(data.get('reprise') or '')
    if ref:etat=await asyncio.to_thread(_lire,ref,user.id)
    else:
        dossier=verifier(str(data.get('dossier') or ''));motif=str(data.get('motif') or '').strip()
        if not motif:raise ValueError('Précise le texte à rechercher.')
        ref=secrets.token_urlsafe(24)
        etat={'motif':motif,'dossier':dossier,'attente':[{'chemin':dossier,'dossier':True}],'vus':[], 'lus':0,'erreurs':0,'tronques':0}
        await asyncio.to_thread(_sauver,ref,user.id,etat)
    verrou=VerrouProcessus('scan-nas:'+ref)
    try:verrou.__enter__()
    except Occupe:return {'ok':False,'reprise':ref,'message':'Cette recherche est déjà en cours.'}
    budget=max(1,min(45,float(data.get('budget_s',45))))
    resultats=[];anomalies=[];debut=time.monotonic();traites=0
    try:
        # Relire après prise du verrou : deux appels simultanés ne perdent pas
        # l'avancement déjà écrit par le premier.
        etat=await asyncio.to_thread(_lire,ref,user.id)
        verifier(etat['dossier'])
        async with connexion() as (client,base,sid):
            while etat['attente'] and traites<20 and time.monotonic()-debut<budget:
                entree=etat['attente'][0];chemin=entree['chemin']
                if chemin in etat['vus']:
                    etat['attente'].pop(0);continue
                try:
                    async with asyncio.timeout(max(.1,min(20,budget-(time.monotonic()-debut)))):
                        if entree['dossier']:
                            lu=await _lister_ouvert(client,base,sid,chemin,tout=True)
                            etat['attente'].extend(e for e in lu['entrees'] if e['chemin'] not in etat['vus'])
                            if lu.get('tronque'):etat['tronques']+=1
                        else:
                            lu=await _lire_ouvert(client,base,sid,chemin,str(user.id))
                            contenu='\n'.join(textes(lu));etat['lus']+=1
                            mots=_normaliser(etat['motif']).split()
                            if contenu and all(m in _normaliser(contenu) for m in mots):
                                lignes=[l for l in contenu.splitlines() if any(m in _normaliser(l) for m in mots)]
                                resultats.append({'nom':entree.get('nom') or chemin.rsplit('/',1)[-1],'chemin':chemin,'dossier':False,'extraits':'\n'.join(lignes)[:4000]})
                            if not contenu:etat['erreurs']+=1;anomalies.append({'chemin':chemin,'raison':'Aucun texte exploitable retourné'})
                except Exception as e:
                    etat['erreurs']+=1;anomalies.append({'chemin':chemin,'raison':type(e).__name__})
                etat['vus'].append(chemin);etat['attente'].pop(0);traites+=1
                await asyncio.to_thread(_sauver,ref,user.id,etat)
        return {'ok':True,'resultats':resultats,'anomalies':anomalies,'fichiers_lus':etat['lus'],
                'reprise':ref if etat['attente'] else None,'termine':not etat['attente'],'partiel':True,
                'couverture':{'dossier':etat['dossier'],'en_attente':len(etat['attente']),'erreurs_lecture':etat['erreurs'],'dossiers_tronques':etat['tronques'],'exhaustive':False},
                'a_faire':'Continue avec reprise tant qu’elle existe. Le parcours examine le texte retourné par les lecteurs, qui peut être un extrait : une absence ne prouve pas l’absence dans tous les formats ou scans. Cite uniquement les extraits rendus. Les droits sont revérifiés à chaque page.'}
    finally:verrou.__exit__()

SKILLS={'nas_chercher_contenu':Declaration(chercher,'Chercher du texte dans un dossier NAS et ses sous-dossiers en lisant les fichiers réels. Parcours reprenable par lots, droits actuels, erreurs et couverture explicites. Pour continuer, fournir uniquement reprise.',optionnels=['dossier','motif','reprise','budget_s'],effet='lecture',libelle='je cherche dans le contenu des fichiers du NAS')}
