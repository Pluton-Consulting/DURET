"""Préparer un nouvel index sans retirer l'ancien ; bascule atomique et reprise."""
import asyncio, json, math
from database.connection import get_db

CLE = 734921065

async def actif():
    from vectorstore.embeddings import modele_courant
    async with get_db() as c:
        valeur = await c.fetchval('SELECT modele FROM embedding_actif WHERE id=1')
    return valeur or modele_courant()

async def conserver_actif():
    from vectorstore.embeddings import modele_courant
    async with get_db() as c:
        await c.execute('INSERT INTO embedding_actif(id,modele) VALUES(1,$1) ON CONFLICT DO NOTHING', modele_courant())

async def verifier_vecteur(c, vecteur):
    """À appeler sous verrou de lecture de la table, avant toute comparaison."""
    modele = getattr(vecteur, 'modele', None)
    if not modele: return True  # API historique / tests : vecteurs explicitement fournis.
    courant = await c.fetchval('SELECT modele FROM embedding_actif WHERE id=1')
    return not courant or courant == modele

TABLES = {'documents': 'content', 'conversation_memoire': "question || E'\\n\\n' || left(reponse,1200)"}

async def preparer(dimension, modele, progression):
    from vectorstore.embeddings import embed_texts
    from vectorstore.revectorisation import oublier_dimension
    if not isinstance(dimension,int) or not 64 <= dimension <= 16000 or not modele:
        raise ValueError('Modèle et dimension mesurés requis (64 à 16000).')
    await conserver_actif()
    async with get_db() as verrou:
        if not await verrou.fetchval('SELECT pg_try_advisory_lock($1)', CLE):
            raise RuntimeError('Une préparation vectorielle est déjà en cours.')
        try:
            await verrou.execute("INSERT INTO embedding_preparations(modele,dimension,phase) VALUES($1,$2,'en_cours') ON CONFLICT(modele,dimension) DO UPDATE SET phase='en_cours',updated_at=now(),erreur=NULL", modele,dimension)
            # Les lignes persistantes permettent de reprendre après un redémarrage.
            # Une modification de texte invalide seulement son vecteur candidat.
            for passage in range(20):
                for table,texte in TABLES.items():
                    while True:
                        async with get_db() as c:
                            lignes=await c.fetch(f"SELECT d.id, {texte} AS texte, md5({texte}) AS empreinte FROM {table} d WHERE NOT EXISTS (SELECT 1 FROM embedding_candidats v WHERE v.modele=$1 AND v.dimension=$2 AND v.source=$3 AND v.document_id=d.id AND v.empreinte=md5({texte})) ORDER BY d.id LIMIT 16", modele,dimension,table)
                        if not lignes: break
                        vecteurs=await embed_texts([r['texte'] or ' ' for r in lignes],modele_force=modele)
                        if len(vecteurs)!=len(lignes): raise RuntimeError('Réponse du fournisseur incomplète ; ancien index conservé.')
                        async with get_db() as c:
                            async with c.transaction():
                                for r,v in zip(lignes,vecteurs):
                                    if not v or len(v)!=dimension or not all(math.isfinite(float(x)) for x in v):
                                        raise RuntimeError('Vecteur absent ou invalide ; ancien index conservé. Relancer reprendra les lots terminés.')
                                    await c.execute('INSERT INTO embedding_candidats(modele,dimension,source,document_id,empreinte,vecteur) VALUES($1,$2,$3,$4,$5,$6::vector) ON CONFLICT(modele,dimension,source,document_id) DO UPDATE SET empreinte=excluded.empreinte,vecteur=excluded.vecteur',modele,dimension,table,r['id'],r['empreinte'],json.dumps(v))
                                await c.execute('UPDATE embedding_preparations SET updated_at=now() WHERE modele=$1 AND dimension=$2',modele,dimension)
                        progression['prepares']=progression.get('prepares',0)+len(lignes)
                        await asyncio.sleep(.1)
                async with get_db() as c:
                    async with c.transaction():
                        await c.execute("SET LOCAL lock_timeout='15s'")
                        await c.execute('LOCK TABLE documents, conversation_memoire, embedding_jobs IN ACCESS EXCLUSIVE MODE',timeout=30)
                        manquants=False
                        for table,texte in TABLES.items():
                            if await c.fetchval(f"SELECT EXISTS(SELECT 1 FROM {table} d WHERE NOT EXISTS(SELECT 1 FROM embedding_candidats v WHERE v.modele=$1 AND v.dimension=$2 AND v.source=$3 AND v.document_id=d.id AND v.empreinte=md5({texte})))",modele,dimension,table):manquants=True
                        if manquants: continue
                        await c.execute('DROP INDEX IF EXISTS idx_documents_embedding_hnsw')
                        for table in TABLES:
                            await c.execute(f'UPDATE {table} SET embedding=NULL WHERE embedding IS NOT NULL',timeout=3600)
                            await c.execute(f'ALTER TABLE {table} ALTER COLUMN embedding TYPE vector({dimension})',timeout=3600)
                            etiquette=', embedding_modele=$1' if table=='documents' else ''
                            await c.execute(f'UPDATE {table} d SET embedding=v.vecteur {etiquette} FROM embedding_candidats v WHERE v.modele=$1 AND v.dimension=$2 AND v.source=$3 AND v.document_id=d.id',modele,dimension,table,timeout=3600)
                        if dimension<=2000:
                            await c.execute('CREATE INDEX idx_documents_embedding_hnsw ON documents USING hnsw(embedding vector_cosine_ops)',timeout=3600)
                        await c.execute("UPDATE embedding_jobs SET status='completed',processed_at=now(),lease_until=NULL,claimed_by=NULL,error_message=NULL WHERE document_id IN(SELECT id FROM documents WHERE embedding IS NOT NULL)")
                        await c.execute('UPDATE embedding_actif SET modele=$1,updated_at=now() WHERE id=1',modele)
                        await c.execute("UPDATE embedding_preparations SET phase='terminee',updated_at=now() WHERE modele=$1 AND dimension=$2",modele,dimension)
                        total=await c.fetchval('SELECT count(*) FROM documents')
                oublier_dimension()
                return {'dimension':dimension,'morceaux_en_file':0,'morceaux_prepares':total,'index_recree':dimension<=2000}
            raise RuntimeError('Le corpus change trop vite pour basculer ; ancien index conservé. Relancer après la synchronisation.')
        except BaseException as e:
            await verrou.execute("UPDATE embedding_preparations SET phase='interrompue',erreur=$3,updated_at=now() WHERE modele=$1 AND dimension=$2",modele,dimension,type(e).__name__)
            raise
        finally: await verrou.execute('SELECT pg_advisory_unlock($1)',CLE)
