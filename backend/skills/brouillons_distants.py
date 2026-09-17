"""Retoucher un brouillon existant en conservant ses pièces et son fil.

Gmail remplace le MIME via drafts.update. IMAP utilise APPENDUID puis UID
EXPUNGE exclusivement sur l'ancien brouillon ; sans UIDPLUS aucune mutation.
Outlook utilise PATCH et If-Match quand le serveur expose une version.
"""
import asyncio,base64,hashlib,html as html_lib,re
from email import policy
from email.parser import BytesParser
from urllib.parse import quote
from skills.registre import Declaration


def charge(data):
    valeurs={k:data[k] for k in ('objet','corps','destinataire','cc') if k in data}
    if not valeurs and not data.get('pieces'):raise ValueError('Précise le champ à retoucher ou les pièces à ajouter.')
    from mail.expedition import porte_un_jeton
    for k,v in valeurs.items():
        if not isinstance(v,str):raise ValueError(k+' doit être un texte.')
        if porte_un_jeton(v):raise ValueError('Une balise de masquage subsiste dans '+k+'.')
        if k!='corps' and ('\r' in v or '\n' in v):raise ValueError('En-tête de message invalide.')
    return valeurs


def retoucher_mime(brut,valeurs,pieces):
    message=BytesParser(policy=policy.SMTP).parsebytes(brut)
    for k,entete in (('objet','Subject'),('destinataire','To'),('cc','Cc')):
        if k in valeurs:
            del message[entete]
            if valeurs[k]:message[entete]=valeurs[k]
    if 'corps' in valeurs:
        change=False
        # get_body exclut les pièces texte jointes et les messages attachés.
        for sous_type in ('plain','html'):
            partie=message.get_body(preferencelist=(sous_type,))
            if partie is not None:
                corps=valeurs['corps'] if sous_type=='plain' else '<div>'+html_lib.escape(valeurs['corps']).replace('\n','<br>')+'</div>'
                partie.set_content(corps,subtype=sous_type,charset='utf-8');change=True
        if not change:raise ValueError('Structure de brouillon sans corps texte modifiable ; aucune modification.')
    for p in pieces:
        majeur,_,mineur=(p.get('mime') or 'application/octet-stream').partition('/')
        message.add_attachment(p['octets'],maintype=majeur,subtype=mineur or 'octet-stream',filename=p['nom'])
    return message.as_bytes()


def _gmail(boite,identifiant,valeurs,pieces):
    from skills.gestion_mail import _service_gmail
    s=_service_gmail(boite,'gmail_brouillon')
    avant=s.users().drafts().get(userId='me',id=identifiant,format='raw').execute()
    m=avant.get('message') or {};brut=base64.urlsafe_b64decode(m.get('raw',''))
    if not brut:raise ValueError('Brouillon Gmail illisible ; aucune modification.')
    contenu=retoucher_mime(brut,valeurs,pieces)
    # Ne pas écraser une retouche détectable effectuée pendant la préparation.
    actuel=s.users().drafts().get(userId='me',id=identifiant,format='raw').execute()
    if (actuel.get('message') or {}).get('raw')!=m.get('raw'):raise ValueError('Le brouillon a changé ; relis-le avant de retoucher.')
    corps={'raw':base64.urlsafe_b64encode(contenu).decode()}
    if m.get('threadId'):corps['threadId']=m['threadId']
    recu=s.users().drafts().update(userId='me',id=identifiant,body={'message':corps}).execute()
    if recu.get('id')!=identifiant:raise RuntimeError('Mise à jour non confirmée ; vérifier la boîte avant de reprendre.')
    return {'id_brouillon':identifiant,'effect_status':'accepted','revision':hashlib.sha256(contenu).hexdigest()}


def _imap(identifiant,valeurs,pieces,autorises,uidvalidity=None):
    from mail import imap
    from mail.lecture import _controler_identifiant
    _controler_identifiant(identifiant,autorises)
    dossier,sep,uid=identifiant.partition('|')
    if not sep or not uid.isdigit():raise ValueError('Référence IMAP attendue : dossier|UID, obtenue à la lecture.')
    c=imap._connexion()
    try:
        if b'UIDPLUS' not in {v.upper() if isinstance(v,bytes) else v.upper().encode() for v in c.capabilities}:raise ValueError('Le serveur IMAP ne permet pas une retouche sûre (UIDPLUS absent). Le brouillon est conservé.')
        code=imap.utf7_encoder(dossier).replace('\\','\\\\').replace('"','\\"')
        statut,_=c.select('"'+code+'"',readonly=False)
        if statut!='OK':raise ValueError('Dossier non modifiable.')
        if uidvalidity is not None:
            _,validite=c.response('UIDVALIDITY')
            courant=b' '.join(v for v in validite or [] if isinstance(v,bytes)).decode().strip()
            if courant!=str(uidvalidity):raise ValueError('Le dossier IMAP a été recréé ou sa validité ne peut pas être confirmée. Relire le brouillon ; aucune retouche effectuée.')
        statut,lignes=c.uid('FETCH',uid,'(BODY.PEEK[] FLAGS)')
        morceaux=[x for x in lignes or [] if isinstance(x,tuple) and len(x)>1 and isinstance(x[1],bytes)]
        if statut!='OK' or len(morceaux)!=1 or b'\\Draft' not in morceaux[0][0]:raise ValueError('Le message doit être un brouillon existant ; aucune modification.')
        contenu=retoucher_mime(morceaux[0][1],valeurs,pieces)
        statut,reponse=c.append('"'+code+'"','(\\Draft)',None,contenu)
        if statut!='OK':raise RuntimeError('Le serveur a refusé la nouvelle version du brouillon.')
        preuve=b' '.join(v for v in reponse or [] if isinstance(v,bytes))
        m=re.search(rb'APPENDUID\s+(\d+)\s+(\d+)',preuve,re.I)
        if not m:
            _,supplement=c.response('APPENDUID');preuve=b' '.join(v for v in supplement or [] if isinstance(v,bytes));m=re.search(rb'(\d+)\s+(\d+)',preuve)
        if not m:raise RuntimeError('Nouvelle version déposée mais UID non confirmé : ancien brouillon conservé. Vérifier les deux avant de reprendre.')
        nouveau=dossier+'|'+m.group(2).decode()
        statut,_=c.uid('STORE',uid,'+FLAGS.SILENT','(\\Deleted)')
        if statut!='OK':raise RuntimeError('Nouvelle version '+nouveau+' déposée ; ancien brouillon conservé, nettoyage manuel nécessaire.')
        statut,_=c.uid('EXPUNGE',uid)
        if statut!='OK':raise RuntimeError('Nouvelle version '+nouveau+' déposée ; ancien brouillon marqué supprimé, vérification nécessaire.')
        return {'id_brouillon':nouveau,'effect_status':'accepted','uidvalidity':m.group(1).decode()}
    finally:
        try:c.logout()
        except Exception:pass


async def _outlook(boite,identifiant,valeurs,pieces):
    import httpx
    from ingestion.connectors.outlook import _jeton
    from mail.expedition import _televerser_pieces
    base='https://graph.microsoft.com/v1.0/users/'+quote(boite,safe='')+'/messages'
    url=base+'/'+quote(identifiant,safe='');h={'Authorization':'Bearer '+await _jeton()}
    async with httpx.AsyncClient(timeout=180) as c:
        r=await c.get(url,headers=h,params={'$select':'id,isDraft,subject,body,toRecipients,ccRecipients'});r.raise_for_status();avant=r.json()
        if not avant.get('isDraft'):raise ValueError('Ce message n’est plus un brouillon ; aucune modification.')
        v={}
        if 'objet' in valeurs:v['subject']=valeurs['objet']
        if 'corps' in valeurs:v['body']={'contentType':'Text','content':valeurs['corps']}
        for k,cible in (('destinataire','toRecipients'),('cc','ccRecipients')):
            if k in valeurs:v[cible]=[{'emailAddress':{'address':a.strip()}} for a in re.split('[;,]',valeurs[k]) if a.strip()]
        if avant.get('@odata.etag'):h['If-Match']=avant['@odata.etag']
        if v:
            r=await c.patch(url,headers=h,json=v);r.raise_for_status()
        # Les pièces déjà présentes restent intactes ; les nouvelles sont ajoutées.
        await _televerser_pieces(c,base,quote(identifiant,safe=''),pieces,{'Authorization':h['Authorization']})
        r=await c.get(url,headers={'Authorization':h['Authorization']},params={'$select':'id,isDraft,subject'});r.raise_for_status();apres=r.json()
        if not apres.get('isDraft') or ('objet' in valeurs and apres.get('subject')!=valeurs['objet']):raise RuntimeError('Retouche non confirmée ; vérifier la boîte avant de reprendre.')
        return {'id_brouillon':identifiant,'effect_status':'accepted'}


async def modifier(data,user):
    from skills.gestion_mail import _contexte
    from mail.attaches import resoudre
    from mail.instantanes import verifier
    boite,nom,autorises=await _contexte(data,user,True)
    identifiant=str(data.get('id_brouillon') or '').strip();valeurs=charge(data)
    if not identifiant:raise ValueError('Utilise l’identifiant du brouillon retourné par son dépôt, jamais son objet seul.')
    pieces,refusees=await resoudre(data.get('pieces'),user,boite)
    if refusees:raise ValueError('Une pièce est inaccessible ; aucune retouche du brouillon.')
    verifier(data,pieces)
    if nom=='outlook':recu=await _outlook(boite,identifiant,valeurs,pieces)
    elif nom=='imap':recu=await asyncio.to_thread(_imap,identifiant,valeurs,pieces,autorises,data.get("uidvalidity"))
    else:
        from mail.google_perso import rafraichir
        await rafraichir();recu=await asyncio.to_thread(_gmail,boite,identifiant,valeurs,pieces)
    return {'ok':True,'modifie':True,'envoye':False,'boite':boite,**recu,
            'evidence_refs':[{'fournisseur':nom,'id':recu['id_brouillon']}],
            'message':'Le fournisseur a accepté la retouche du brouillon existant. Les anciennes pièces ont été conservées ; les pièces demandées ont été ajoutées. Aucun envoi.',
            'a_faire':'Conserve id_brouillon et, pour IMAP, uidvalidity pour les prochaines retouches. Ne redépose pas un nouveau brouillon pour modifier celui-ci. Une erreur partielle exige une relecture avant toute reprise.'}

SKILLS={'modifier_brouillon':Declaration(modifier,'Retoucher un brouillon déjà déposé en conservant son fil et ses pièces existantes. Seuls les champs fournis sont modifiés ; pieces ajoute des pièces. Corps complet requis pour remplacer le corps. Aucun envoi.',requis=['id_brouillon'],optionnels=['boite','objet','corps','destinataire','cc','pieces','uidvalidity'],effet='externe',libelle='je retouche le brouillon existant')}
