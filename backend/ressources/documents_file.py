"""File documentaire persistante : reprise après arrêt, un document à la fois.

Le rôle est rechargé à chaque tentative. Les messages sont insérés dans le fil
possédé avec dédoublonnage transactionnel. Aucun envoi de mail ni dépôt externe.
"""
import asyncio,hashlib,json,logging,time
from ressources import dossiers
from contextvars import ContextVar
_COURANTE=ContextVar('redaction_courante',default=None)
logger=logging.getLogger('infra.documents')
_task=None

def _table(c):
    c.execute('CREATE TABLE IF NOT EXISTS file_documentaire (id TEXT PRIMARY KEY, utilisateur TEXT NOT NULL, fil TEXT NOT NULL, genre TEXT NOT NULL, donnees TEXT NOT NULL, statut TEXT NOT NULL, essais INTEGER NOT NULL DEFAULT 0, prochain REAL NOT NULL DEFAULT 0, resultat TEXT, annonce INTEGER NOT NULL DEFAULT 0)')

def soumettre(uid,fil,genre,data):
    uid,fil=dossiers.identite(uid,fil)
    data=dossiers.normaliser_selection(uid,fil,data);data['_fil']=fil
    # Figer les sources au dépôt : une pièce ajoutée plus tard ne change pas une commande en cours.
    if not data.get('sources') and not data.get('tache'):data['sources']=[s['id'] for s in dossiers.manifeste(uid,fil)]
    cle=hashlib.sha256(json.dumps([uid,fil,genre,data],sort_keys=True,ensure_ascii=False).encode()).hexdigest()[:24]
    with dossiers.base() as c:
        _table(c);c.execute('BEGIN IMMEDIATE')
        # Une reprise par l'identifiant moteur retrouve la file d'origine ;
        # son JSON différent ne doit pas créer une seconde notification.
        if data.get('tache'):
            anciens=c.execute('SELECT id,donnees FROM file_documentaire WHERE utilisateur=? AND fil=? AND genre=? ORDER BY rowid',(uid,fil,genre)).fetchall()
            ancien=next((r for r in anciens if json.loads(r['donnees']).get('tache')==data['tache']),None)
            if ancien:cle=ancien['id']
        c.execute('INSERT OR IGNORE INTO file_documentaire(id,utilisateur,fil,genre,donnees,statut) VALUES(?,?,?,?,?,?)',(cle,uid,fil,genre,json.dumps(data,ensure_ascii=False),'attente'))
        r=dict(c.execute('SELECT * FROM file_documentaire WHERE id=? AND utilisateur=? AND fil=?',(cle,uid,fil)).fetchone())
    if r['statut']=='termine':
        resultat=json.loads(r['resultat'])
        from bureautique.atelier import chemin_fichier
        if resultat.get('document_id') and not chemin_fichier(resultat['document_id'],uid):raise ValueError('Le livrable sauvegardé n’est plus disponible ; demande une nouvelle révision.')
        return resultat
    if r['statut']=='bloque':return {'ok':True,'outcome':'partial','production_verifiee':False,'tache_documentaire':cle,'note':json.loads(r['resultat']).get('note','Rédaction suspendue ; consulte les réserves dans cette conversation.')}
    return {'ok':True,'en_cours':True,'statut':'pending','tache_documentaire':cle,'production_verifiee':False,
            'note':'La rédaction est enregistrée et se poursuit en arrière-plan. Les étapes sont conservées après fermeture du chat et redémarrage. Le résultat ou les points bloquants seront ajoutés à cette conversation.',
            'a_faire':'Annonce le travail en cours. Ne recrée pas un autre document et ne présente pas les sources comme le livrable. Ne prétends pas que le document est déjà prêt.'}

def etats(uid,fil):
    uid,fil=dossiers.identite(uid,fil)
    with dossiers.base() as c:
        _table(c)
        return [dict(r) for r in c.execute('SELECT id,genre,statut,essais FROM file_documentaire WHERE utilisateur=? AND fil=? ORDER BY rowid DESC LIMIT 30',(uid,fil))]

def associer_tache(uid,fil,tache):
    """Rendre les étapes visibles dès le premier essai, sans attendre son issue."""
    cle=_COURANTE.get()
    if not cle:return
    uid,fil=dossiers.identite(uid,fil)
    with dossiers.base() as c:
        r=c.execute('SELECT donnees FROM file_documentaire WHERE id=? AND utilisateur=? AND fil=?',(cle,uid,fil)).fetchone()
        if not r:raise ValueError('Rédaction étrangère à cette conversation.')
        data=json.loads(r[0]);data['tache']=tache
        c.execute('UPDATE file_documentaire SET donnees=? WHERE id=?',(json.dumps(data,ensure_ascii=False),cle))

def progression(uid,fil):
    """État public limité au compte/fil ; aucun contenu de pièce ou erreur brute."""
    uid,fil=dossiers.identite(uid,fil);sortie=[]
    with dossiers.base() as c:
        _table(c)
        for r in c.execute('SELECT id,genre,statut,donnees,annonce FROM file_documentaire WHERE utilisateur=? AND fil=? ORDER BY rowid DESC LIMIT 30',(uid,fil)).fetchall():
            data=json.loads(r['donnees']);tache=data.get('tache')
            etapes={x[0]:json.loads(x[1]) if x[0] in ('plan','suivi_controle') else True for x in c.execute("SELECT cle,CASE WHEN cle IN ('plan','suivi_controle') THEN valeur ELSE 'null' END FROM etapes_documentaires WHERE utilisateur=? AND fil=? AND tache=?",(uid,fil,tache or ''))}
            total=len(etapes.get('plan',{}).get('sections',[]))
            sections=sum(k.startswith('section:') for k in etapes)
            lectures=sum(k.startswith('analyse:') for k in etapes)
            controles=etapes.get('suivi_controle',{}).get('cles',[])
            controles_faits=sum(k in etapes for k in controles)
            statut=r['statut']
            if statut=='termine':phase='Document prêt' if r['annonce'] else 'Ajout du document à la conversation'
            elif statut=='suspendu':phase='Rédaction suspendue — étapes conservées'
            elif statut=='bloque':phase='Rédaction à reprendre — étapes conservées'
            elif 'correction' in etapes:phase='Correction après vérification finale'
            elif controles and controles_faits<len(controles):phase=f'Vérification des informations : {controles_faits}/{len(controles)} étapes'
            elif total and sections>=total:phase='Vérification finale et mise en page'
            elif total:phase=f'Rédaction et contrôle : {sections}/{total} rubriques'
            elif lectures:phase=f'Lecture des pièces : {lectures} parties analysées'
            elif statut=='en_cours':phase='Lecture et préparation des pièces'
            else:phase='Rédaction enregistrée — démarrage en attente'
            sortie.append({'id':r['id'],'genre':r['genre'],'statut':statut,'phase':phase,
                           'sections':sections,'sections_total':total,'lectures':lectures,
                           'annonce':bool(r['annonce'])})
    return sortie

def _candidats():
    with dossiers.base() as c:
        _table(c)
        return [dict(r) for r in c.execute("SELECT * FROM file_documentaire WHERE (statut IN ('attente','en_cours') AND prochain<=?) OR (statut IN ('termine','bloque') AND annonce=0 AND prochain<=?) ORDER BY rowid LIMIT 20",(time.time(),time.time()))]

def _maj(cle,**valeurs):
    autorises={'statut','essais','prochain','resultat','annonce','donnees'}
    if not valeurs or set(valeurs)-autorises:raise ValueError('Champ de file invalide.')
    with dossiers.base() as c:
        _table(c);c.execute('UPDATE file_documentaire SET '+','.join(k+'=?' for k in valeurs)+' WHERE id=?',(*valeurs.values(),cle))

async def annoncer(job,user,resultat):
    from database.connection import get_rls_db
    texte=('Le document est prêt.' if resultat.get('production_verifiee') else 'La rédaction nécessite une vérification avant livraison.')
    reserves=resultat.get('reserves') or []
    if reserves:texte+='\n\nPoints à vérifier :\n'+'\n'.join('- '+str(r) for r in reserves[:30])
    if not resultat.get('production_verifiee'):texte+='\n\n'+str(resultat.get('note') or 'Les étapes déjà contrôlées sont conservées.')
    if resultat.get('bloc_ui'):texte+='\n\n```ui\n'+json.dumps(resultat['bloc_ui'],ensure_ascii=False)+'\n```'
    meta=json.dumps({'tache_planifiee':'document:'+job['id'],'tache_documentaire':job['id'],'statut':job['statut']})
    async with get_rls_db(str(user.id),user.role) as conn:
        async with conn.transaction():
            # Verrou PostgreSQL partagé entre processus ; notification exactement une fois.
            await conn.execute('SELECT pg_advisory_xact_lock(hashtextextended($1,0))','document:'+job['id'])
            pk=await conn.fetchval('SELECT id FROM threads WHERE langgraph_thread_id=$1 AND user_id=$2::uuid',job['fil'],str(user.id))
            if not pk:return
            existe=await conn.fetchval("SELECT 1 FROM messages WHERE thread_id=$1 AND metadata->>'tache_documentaire'=$2 AND metadata->>'statut'=$3",pk,job['id'],job['statut'])
            if not existe:
                await conn.execute("INSERT INTO messages(thread_id,role,content,metadata) VALUES($1,'assistant',$2,$3::jsonb)",pk,texte,meta)
                await conn.execute('UPDATE threads SET updated_at=NOW() WHERE id=$1',pk)

async def traiter(job):
    from ressources.registre import _chemin
    from stockage.verrous import verrou_fichier
    from tasks.identity import charger_executant
    from security.lecteur import au_nom_de
    from security.conversation import fil_courant
    from llm.budget import Budget,_courant
    with verrou_fichier(str(_chemin().parent),'file-document:'+job['id'],bloquant=False) as acquis:
        if not acquis:return
        # Relecture sous verrou : le candidat peut avoir été traité par un autre processus.
        with dossiers.base() as c:job=dict(c.execute('SELECT * FROM file_documentaire WHERE id=?',(job['id'],)).fetchone())
        if job['prochain']>time.time() or job['annonce'] or job['statut']=='suspendu':return
        user=await charger_executant(job['utilisateur'])
        if not user:
            _maj(job['id'],prochain=time.time()+300)
            return
        if job['statut'] not in ('termine','bloque'):
            essais=job['essais']+1;_maj(job['id'],statut='en_cours',essais=essais,prochain=time.time()+960)
            donnees=json.loads(job['donnees']);f=fil_courant.set(job['fil']);b=_courant.set(Budget(900));j=_COURANTE.set(job['id'])
            from llm.concurrence import PERSONNE
            from config import settings
            personne=PERSONNE.set(('fond:documents',int(getattr(settings,'llm_simultanes_fond',2) or 2)))
            from llm.compteur import _TOUR,bilan
            compteur=_TOUR.set({'entree':0,'sortie':0,'euros':0.0,'modeles':[]})
            try:
                with au_nom_de(user):
                    async with asyncio.timeout(900):
                        if job['genre']=='document':
                            from skills.documents_dossier import composer_immediat
                            resultat=await composer_immediat(donnees,user)
                        else:
                            from skills.quantitatifs import produire_immediat
                            resultat=await produire_immediat(donnees,user)
            except asyncio.CancelledError:
                with dossiers.base() as c:
                    c.execute("UPDATE file_documentaire SET statut='attente',prochain=? WHERE id=? AND statut!='suspendu'",(time.time()+10,job['id']))
                raise
            except Exception as e:
                logger.warning('Rédaction %s interrompue (%s)',job['id'],type(e).__name__)
                resultat={'production_verifiee':False,'note':'Une étape a échoué ('+type(e).__name__+'). Les étapes acquises sont conservées.'}
                if getattr(e,'tache_documentaire',None):resultat['tache']=e.tache_documentaire
            finally:
                usage=bilan();_TOUR.reset(compteur)
                fil_courant.reset(f);_courant.reset(b);PERSONNE.reset(personne);_COURANTE.reset(j)
                await asyncio.to_thread(dossiers.etape,job['utilisateur'],job['fil'],'file:'+job['id'],'consommation:'+str(essais),usage)
            await journaliser(job,user,essais,resultat,usage)
            if resultat.get('tache'):donnees['tache']=resultat['tache']
            with dossiers.base() as c:
                courant=c.execute('SELECT statut FROM file_documentaire WHERE id=?',(job['id'],)).fetchone()[0]
                # Seules les étapes métier de cette rédaction constituent un progrès.
                progression=c.execute("SELECT count(*) FROM etapes_documentaires WHERE utilisateur=? AND fil=? AND tache=? AND cle NOT LIKE 'consommation:%' AND cle NOT IN ('contrat','correction')",(job['utilisateur'],job['fil'],donnees.get('tache') or '')).fetchone()[0]
            if courant=='suspendu':return
            precedent=json.loads(job['resultat'] or '{}')
            resultat['etapes_conservees']=progression
            stagne=essais>=3 and precedent.get('note')==resultat.get('note') and precedent.get('etapes_conservees')==progression
            statut='termine' if resultat.get('production_verifiee') else 'bloque' if essais>=8 or stagne else 'attente'
            _maj(job['id'],statut=statut,donnees=json.dumps(donnees,ensure_ascii=False),resultat=json.dumps(resultat,ensure_ascii=False),prochain=time.time()+min(300,15*essais) if statut=='attente' else 0)
            job={**job,'statut':statut,'resultat':json.dumps(resultat,ensure_ascii=False)}
        if job['statut'] in ('termine','bloque'):
            try:
                await annoncer(job,user,json.loads(job['resultat']));_maj(job['id'],annonce=1)
            except Exception as e:
                _maj(job['id'],prochain=time.time()+60)
                logger.warning('Annonce documentaire à reprendre (%s)',type(e).__name__)

async def _boucle():
    while True:
        try:
            for job in await asyncio.to_thread(_candidats):await traiter(job)
        except asyncio.CancelledError:raise
        except Exception as e:logger.warning('File documentaire temporairement indisponible (%s)',type(e).__name__)
        await asyncio.sleep(10)

async def demarrer():
    global _task
    if _task is None or _task.done():_task=asyncio.create_task(_boucle(),name='documents-durables')

async def arreter():
    global _task
    if _task:
        _task.cancel()
        try:await _task
        except asyncio.CancelledError:pass
        _task=None


def verifier_poursuite():
    cle=_COURANTE.get()
    if not cle:return
    with dossiers.base() as c:
        r=c.execute('SELECT statut FROM file_documentaire WHERE id=?',(cle,)).fetchone()
    if r and r[0]=='suspendu':raise ValueError('Rédaction suspendue à la demande de l’utilisateur ; les étapes sont conservées.')

def piloter(uid,fil,cle,reprendre=False):
    uid,fil=dossiers.identite(uid,fil)
    with dossiers.base() as c:
        _table(c);c.execute('BEGIN IMMEDIATE');r=c.execute('SELECT statut FROM file_documentaire WHERE id=? AND utilisateur=? AND fil=?',(cle,uid,fil)).fetchone()
        if not r:
            # Le chat voit aussi l’identifiant du moteur dans la progression.
            # Résoudre cet alias uniquement dans le compte et le fil courant,
            # jamais « la dernière tâche » d’une autre conversation.
            correspondances=[x for x in c.execute('SELECT id,statut,donnees FROM file_documentaire WHERE utilisateur=? AND fil=?',(uid,fil)) if json.loads(x['donnees']).get('tache')==cle]
            if len(correspondances)!=1:raise ValueError('Rédaction inconnue ou ambiguë dans cette conversation ; utilise son identifiant de file.')
            cle=correspondances[0]['id'];r=(correspondances[0]['statut'],)
        if r[0]=='termine':return {'ok':True,'statut':'termine','note':'Le document a déjà été livré.'}
        if reprendre and r[0] in ('attente','en_cours'):
            return {'ok':True,'statut':r[0],'en_cours':True,'tache_documentaire':cle,'production_verifiee':False,
                    'note':'La rédaction est déjà en cours. Ses étapes et sa progression sont conservées.'}
        statut='attente' if reprendre else 'suspendu'
        c.execute('UPDATE file_documentaire SET statut=?,essais=0,prochain=0,annonce=0 WHERE id=?',(statut,cle))
    return {'ok':True,'statut':statut,'en_cours':bool(reprendre),'tache_documentaire':cle,'production_verifiee':False,
            'note':'Reprise enregistrée ; la rédaction se poursuit dans cette conversation.' if reprendre else 'Arrêt enregistré ; un appel déjà parti peut finir, les étapes restent conservées.'}


async def journaliser(job,user,essais,resultat,usage):
    try:
        from security.audit import log_action
        await log_action(action='redaction_documentaire',user_id=str(user.id),agent_id='agent2' if job['genre']=='quantitatif' else 'agent1',
            model_used=usage.get('modele'),tokens_in=usage['tokens_in'],tokens_out=usage['tokens_out'],cost_eur=usage['cost_eur'],
            success=bool(resultat.get('production_verifiee')),metadata={'tache_documentaire':job['id'],'essai':essais},
            on_behalf_of=str(user.id),trigger_type='document',trigger_id=job['fil'])
    except Exception as e:logger.warning('Journal documentaire à relire dans les étapes sauvegardées (%s)',type(e).__name__)
