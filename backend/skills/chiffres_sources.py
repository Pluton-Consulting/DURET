"""Chiffres extraits d'une lecture autorisée et calculs décimaux traçables."""
import asyncio,ast,hashlib,json,re,secrets,sqlite3,os
from contextlib import closing
from decimal import Decimal,localcontext
from skills.registre import Declaration

LECTEURS={'nas':'nas_ouvrir','drive':'drive_ouvrir','mail':'lire_mail','piece_jointe':'lire_piece_jointe'}
NOMBRE=re.compile(r'(?<![\w])[-+]?\d+(?:[ \u00a0\u202f]\d{3})*(?:[,.]\d+)?(?:\s*(?:€|EUR|euros?|m²|m2|m³|m3|mm|cm|ml|kg|%|m)(?!\w))?',re.I)
VALEUR=re.compile(r'^([-+]?\d+(?:[ \u00a0\u202f]\d{3})*(?:[,.]\d+)?)(.*)$',re.S)

def _db():
    from ressources.registre import _chemin
    p=_chemin().parent/'chiffres.sqlite3';p.parent.mkdir(parents=True,exist_ok=True)
    fd=os.open(p,os.O_CREAT|os.O_RDWR,0o600);os.close(fd)
    c=sqlite3.connect(p,timeout=5)
    c.execute('CREATE TABLE IF NOT EXISTS chiffres(ref TEXT PRIMARY KEY,user_id TEXT NOT NULL,source TEXT NOT NULL,lecture_sha256 TEXT NOT NULL,valeur TEXT NOT NULL,unite TEXT NOT NULL,citation TEXT NOT NULL,ligne INTEGER NOT NULL)')
    return c

def textes(v):
    if isinstance(v,dict):
        for cle in ('apercu','lignes','rows'):
            if isinstance(v.get(cle),list):
                for numero,ligne in enumerate(v[cle],1):
                    if isinstance(ligne,dict):yield f'Ligne {numero} : '+ ' | '.join(f'{k} : {x}' for k,x in ligne.items())
                    elif isinstance(ligne,list):yield f'Ligne {numero} : '+ ' | '.join(str(x) for x in ligne)
        for k,x in v.items():
            if k in ('contenu','texte','corps','body','text','content') and isinstance(x,str):yield x
            elif isinstance(x,(dict,list)):yield from textes(x)
    elif isinstance(v,list):
        for x in v:yield from textes(x)

def extraire(contenu,source,uid,page=1):
    sha=hashlib.sha256(contenu.encode()).hexdigest();trouves=[]
    for numero,ligne in enumerate(contenu.splitlines(),1):
        for match in NOMBRE.finditer(ligne):
            v=VALEUR.match(match.group());nombre=v[1].replace(' ','').replace('\u00a0','').replace('\u202f','').replace(',','.')
            unite=v[2].strip().lower();unite={'eur':'€','euro':'€','euros':'€','m2':'m²','m3':'m³'}.get(unite,unite)
            ref=hashlib.sha256((str(uid)+'\0'+json.dumps(source,sort_keys=True)+'\0'+sha+'\0'+str(numero)+':'+str(match.start())).encode()).hexdigest()[:24]
            trouves.append({'ref':ref,'valeur':str(Decimal(nombre)),'unite':unite,'citation':ligne[max(0,match.start()-120):match.end()+120],'ligne':numero})
    total=len(trouves);page=max(1,int(page));selection=trouves[(page-1)*50:page*50]
    with closing(_db()) as c,c:
        for v in selection:c.execute('INSERT OR IGNORE INTO chiffres VALUES(?,?,?,?,?,?,?,?)',(v['ref'],str(uid),json.dumps(source,sort_keys=True),sha,v['valeur'],v['unite'],v['citation'],v['ligne']))
    return {'chiffres':selection,'total':total,'page':page,'page_suivante':page+1 if page*50<total else None,'lecture_sha256':sha}

async def lecture(source,user):
    if isinstance(source,dict) and source.get('type')=='dossier':
        from ressources.dossiers import sources
        from security.conversation import fil_courant
        fil=fil_courant.get()
        # Le fil courant vient de l'exécuteur, jamais d'une valeur de calcul.
        if not fil or source.get('fil')!=fil:raise ValueError('Source de chiffres hors de la conversation courante.')
        return sources(str(user.id),fil,[source.get('id')])[0]['contenu']
    if not isinstance(source,dict) or source.get('type') not in LECTEURS or not isinstance(source.get('args'),dict):raise ValueError('Source attendue : type nas/drive/mail/piece_jointe et args de lecture.')
    from skills.executor import execute_skill
    r=await execute_skill(LECTEURS[source['type']],source['args'],user=user,user_id=str(user.id))
    if not r.get('ok'):raise ValueError('La source ne peut pas être lue avec vos droits actuels.')
    contenu='\n'.join(textes(r.get('output')))
    if not contenu.strip():raise ValueError('Aucun texte exploitable rendu par cette source. Aucun chiffre inféré de l’image.')
    return contenu

async def relever(data,user):
    source=data.get('source');contenu=await lecture(source,user)
    r=await asyncio.to_thread(extraire,contenu,source,str(user.id),data.get('page') or 1)
    return {'ok':True,**r,'source':source,'exhaustive':False,
            'a_faire':'Les valeurs sont des occurrences du texte réellement retourné, parfois un extrait. Sélectionne celles correspondant au libellé demandé ; une date ou une référence numérique n’est pas un montant. Unité vide signifie inconnue. Cite source, citation et ligne. Pour calculer utilise calculer_chiffres_sources ; ne déduis pas une dimension non écrite.'}

def calculer(expression,valeurs):
    if not isinstance(expression,str) or len(expression)>300:raise ValueError('Expression trop longue.')
    def visite(n):
        if isinstance(n,ast.Name) and n.id in valeurs:return Decimal(valeurs[n.id])
        if isinstance(n,ast.BinOp) and isinstance(n.op,(ast.Add,ast.Sub,ast.Mult,ast.Div)):
            a,b=visite(n.left),visite(n.right)
            return a+b if isinstance(n.op,ast.Add) else a-b if isinstance(n.op,ast.Sub) else a*b if isinstance(n.op,ast.Mult) else a/b
        if isinstance(n,ast.UnaryOp) and isinstance(n.op,(ast.USub,ast.UAdd)):return -visite(n.operand) if isinstance(n.op,ast.USub) else visite(n.operand)
        raise ValueError('Utilise uniquement c1, c2… et + - * / ; chaque opérande doit venir d’une source.')
    try:
        arbre=ast.parse(expression,mode='eval').body
    except SyntaxError as e:
        raise ValueError('Formule invalide : utilise c1*c2, c1+c2 ou c1-c2 avec les opérandes sourcés ; pas de mots comme longueur x largeur.') from e
    with localcontext() as ctx:
        ctx.prec=28
        r=visite(arbre)
    if not r.is_finite():raise ValueError('Résultat non fini.')
    return format(r,'f')

async def calcul(data,user):
    refs=data.get('references')
    if not isinstance(refs,list) or not 1<=len(refs)<=12 or any(not isinstance(x,str) for x in refs):raise ValueError('Fournis de 1 à 12 références de chiffres déjà relevés.')
    def charger():
        with closing(_db()) as c:
            c.row_factory=sqlite3.Row
            return [dict(l) if (l:=c.execute('SELECT * FROM chiffres WHERE ref=? AND user_id=?',(ref,str(user.id))).fetchone()) else None for ref in refs]
    preuves=await asyncio.to_thread(charger)
    if any(p is None for p in preuves):raise ValueError('Référence inconnue ou appartenant à un autre utilisateur.')
    lectures={}
    for p in preuves:
        if p['source'] not in lectures:lectures[p['source']]=hashlib.sha256((await lecture(json.loads(p['source']),user)).encode()).hexdigest()
        if lectures[p['source']]!=p['lecture_sha256']:raise ValueError('Une source a changé depuis le relevé : relève ses chiffres à nouveau avant de calculer.')
    valeurs={'c'+str(i+1):p['valeur'] for i,p in enumerate(preuves)}
    r=calculer(data.get('expression'),valeurs)
    return {'ok':True,'resultat_decimal':r,'expression':data['expression'],
            'operandes':[{'variable':'c'+str(i+1),'valeur':p['valeur'],'unite_source':p['unite'],'citation':p['citation'],'ligne':p['ligne'],'source':json.loads(p['source'])} for i,p in enumerate(preuves)],
            'evidence_refs':[{'ref':p['ref'],'lecture_sha256':p['lecture_sha256']} for p in preuves],
            'a_faire':'Calcul arithmétique vérifié sur les valeurs citées. Les unités et le choix métier des lignes doivent être cohérents ; aucun changement automatique d’unité ni de pourcentage (20 % reste la valeur écrite 20). Ne présente pas ce calcul comme un métré validé. Montre la formule, les opérandes et leurs citations.'}

SKILLS={
 'relever_chiffres_source':Declaration(relever,'Lire une source autorisée puis relever ses occurrences numériques avec citation, ligne et empreinte. Les images sans texte ne fournissent aucun chiffre inventé.',requis=['source'],optionnels=['page'],effet='lecture',libelle='je relève les chiffres dans la source'),
 'calculer_chiffres_sources':Declaration(calcul,'Calculer en décimal à partir de références de chiffres relevés : expression c1*c2 ou c1+c2. Relit les sources et les droits avant calcul. Pas de constantes inventées, ni conversion implicite d’unité.',requis=['references','expression'],effet='lecture',libelle='je vérifie le calcul et ses sources')}
