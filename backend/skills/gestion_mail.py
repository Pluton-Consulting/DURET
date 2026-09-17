"""Actions explicites de messagerie : capacités et indicateurs vérifiés après écriture.

Les endpoints suivent Graph v1.0 message-update et Gmail users.messages.modify.
Aucun envoi ni suppression de message dans ce module. Les écritures passent par
le registre habituel des effets et une validation humaine.
"""
import asyncio,re
from urllib.parse import quote
from skills.registre import Declaration

async def _contexte(data,user,ecriture=False):
    from mail.skills import _boite_a_lire
    from mail.authorization import verifier_acces,dossiers_autorises
    from mail.collecte import fournisseur
    boite=await verifier_acces(user,await _boite_a_lire(data,user),envoi=ecriture)
    return boite,fournisseur(),await dossiers_autorises(user)

async def capacites(data,user):
    boite,nom,_=await _contexte(data,user)
    autorise=None
    if nom=='gmail':
        from mail.google_perso import rafraichir,capacites as droits
        await rafraichir();autorise=droits(boite)
    return {'boite':boite,'fournisseur':nom,'actions':{
      'lire':True,'deposer_brouillon':True,'modifier_brouillon':True,
      'lu_non_lu':True,'indicateur_suivi':True,'categories':nom!='imap'},
      'autorisation_google_connue':sorted(autorise) if autorise is not None else None,
      'conditions':('Gmail : les indicateurs exigent gmail.modify, les brouillons gmail.compose ou gmail.modify. Les droits déjà accordés restent inchangés.' if nom=='gmail' else
                    'IMAP : les indicateurs exigent un dossier ouvert en écriture ; la mise à jour du brouillon exige UIDPLUS.' if nom=='imap' else
                    'Outlook : Mail.ReadWrite est nécessaire pour modifier les messages.'),
      'a_faire':'Utilise les capacités réellement autorisées. Une lecture ne prouve pas un droit d’écriture. Si une autorisation manque, nomme précisément laquelle ; ne demande jamais de changer une clé existante.'}

def changements(data):
    sortie={}
    if 'lu' in data:
        v=data['lu']
        if not isinstance(v,bool):raise ValueError('lu doit être vrai ou faux.')
        sortie['lu']=v
    if 'suivi' in data:
        v=str(data['suivi']).lower();correspondance={'oui':'actif','non':'aucun','true':'actif','false':'aucun','termine':'termine','terminé':'termine','actif':'actif','aucun':'aucun'}
        if v not in correspondance:raise ValueError('suivi : actif, termine ou aucun.')
        sortie['suivi']=correspondance[v]
    for cle in ('ajouter_categories','retirer_categories'):
        if cle in data:
            v=data[cle]
            if not isinstance(v,list) or any(not isinstance(x,str) or not x.strip() or len(x)>100 or '\n' in x or '\r' in x for x in v):raise ValueError('Catégories : liste de noms non vides attendue.')
            sortie[cle]=list(dict.fromkeys(v))
    if set(sortie.get('ajouter_categories',[])) & set(sortie.get('retirer_categories',[])):raise ValueError('Une même catégorie ne peut pas être ajoutée et retirée.')
    if not sortie:raise ValueError('Précise lu, suivi ou les catégories à changer.')
    return sortie

def _service_gmail(boite,capacite='gmail_modification'):
    from mail import google_perso
    from ingestion.connectors.gmail import _cle_compte_de_service
    from googleapiclient.discovery import build
    perso=google_perso.credentials_pour_boite(boite)
    if perso is not None:
        if not google_perso.peut(boite,capacite):raise ValueError(google_perso.refus_de_capacite(boite,capacite))
        return build('gmail','v1',credentials=perso,cache_discovery=False)
    from google.oauth2 import service_account
    infos=_cle_compte_de_service()
    if infos is None:raise ValueError('Aucun compte Gmail autorisé pour cette boîte.')
    scope='https://www.googleapis.com/auth/gmail.modify' if capacite=='gmail_modification' else 'https://www.googleapis.com/auth/gmail.compose'
    creds=service_account.Credentials.from_service_account_info(infos,scopes=[scope],subject=boite)
    return build('gmail','v1',credentials=creds,cache_discovery=False)

def _gmail_modifier(boite,identifiant,change):
    service=_service_gmail(boite);ajouts=[];retraits=[]
    if 'lu' in change:(retraits if change['lu'] else ajouts).append('UNREAD')
    if 'suivi' in change:(ajouts if change['suivi']=='actif' else retraits).append('STARRED')
    voulus=set(change.get('ajouter_categories',[])+change.get('retirer_categories',[]))
    if voulus:
        etiquettes=service.users().labels().list(userId='me').execute().get('labels',[])
        ids={e['name']:e['id'] for e in etiquettes if e.get('type')=='user'}
        for nom in change.get('ajouter_categories',[]):
            if nom not in ids:
                r=service.users().labels().create(userId='me',body={'name':nom}).execute();ids[nom]=r['id']
            ajouts.append(ids[nom])
        retraits.extend(ids[nom] for nom in change.get('retirer_categories',[]) if nom in ids)
    if set(ajouts)&set(retraits):raise ValueError('Une même catégorie ne peut pas être ajoutée et retirée.')
    service.users().messages().modify(userId='me',id=identifiant,body={'addLabelIds':ajouts,'removeLabelIds':retraits}).execute()
    observe=service.users().messages().get(userId='me',id=identifiant,format='minimal').execute()
    labels=set(observe.get('labelIds',[]))
    if not set(ajouts)<=labels or set(retraits)&labels:raise RuntimeError('Le fournisseur ne confirme pas tous les indicateurs demandés ; vérifier avant toute reprise.')
    return {'id':observe.get('id') or identifiant,'labels':sorted(labels),'equivalence_suivi':'étoile Gmail' if 'suivi' in change else None}

async def _outlook_modifier(boite,identifiant,change):
    import httpx
    from ingestion.connectors.outlook import _jeton
    base='https://graph.microsoft.com/v1.0/users/'+quote(boite,safe='')+'/messages/'+quote(identifiant,safe='')
    headers={'Authorization':'Bearer '+await _jeton()}
    async with httpx.AsyncClient(timeout=30) as c:
        r=await c.get(base,headers=headers,params={'$select':'id,isRead,flag,categories'});r.raise_for_status();avant=r.json();charge={}
        if 'lu' in change:charge['isRead']=change['lu']
        if 'suivi' in change:charge['flag']={'flagStatus':{'actif':'flagged','aucun':'notFlagged','termine':'complete'}[change['suivi']]}
        if 'ajouter_categories' in change or 'retirer_categories' in change:
            charge['categories']=sorted((set(avant.get('categories',[]))|set(change.get('ajouter_categories',[])))-set(change.get('retirer_categories',[])))
        if avant.get('@odata.etag'):headers['If-Match']=avant['@odata.etag']
        r=await c.patch(base,headers=headers,json=charge);r.raise_for_status()
        r=await c.get(base,headers={'Authorization':headers['Authorization']},params={'$select':'id,isRead,flag,categories'});r.raise_for_status();apres=r.json()
        for k,v in charge.items():
            observe=apres.get(k)
            if k=='flag':observe=(observe or {}).get('flagStatus');v=v['flagStatus']
            if k=='categories':observe=sorted(observe or [])
            if observe!=v:raise RuntimeError('Modification non confirmée par Outlook ; vérifier avant de reprendre.')
        return {'id':apres.get('id') or identifiant,'observe':charge}

def _imap_modifier(identifiant,change,autorises):
    from mail import imap
    from mail.lecture import _controler_identifiant
    _controler_identifiant(identifiant,autorises)
    if change.get('ajouter_categories') or change.get('retirer_categories'):raise ValueError('Ce connecteur IMAP ne gère pas les catégories ; indicateurs et lu/non lu restent disponibles.')
    dossier,sep,uid=identifiant.partition('|')
    if not sep or not uid.isdigit():raise ValueError('Référence IMAP invalide ; relire le message.')
    c=imap._connexion()
    try:
        # Réutiliser l'encodage des noms de dossiers du connecteur existant.
        imap._selectionner(c,dossier)
        code=imap.utf7_encoder(dossier).replace('\\','\\\\')
        statut,_=c.select('"'+code.replace('"','\\"')+'"',readonly=False)
        if statut!='OK':raise ValueError('Ce dossier IMAP ne peut pas être modifié.')
        attendus={}
        if 'lu' in change:attendus['\\Seen']=change['lu']
        if 'suivi' in change:attendus['\\Flagged']=change['suivi']=='actif'
        for flag,valeur in attendus.items():
            statut,_=c.uid('STORE',uid,'+FLAGS.SILENT' if valeur else '-FLAGS.SILENT','('+flag+')')
            if statut!='OK':raise RuntimeError('Le serveur IMAP a refusé un indicateur.')
        statut,lignes=c.uid('FETCH',uid,'(FLAGS)')
        if statut!='OK' or not lignes:raise RuntimeError('Les indicateurs IMAP ne sont pas vérifiables.')
        brut=b' '.join(x for x in lignes if isinstance(x,bytes)).decode(errors='replace')
        flags=set(re.findall(r'\\[A-Za-z]+',brut))
        if any((k in flags)!=v for k,v in attendus.items()):raise RuntimeError('Les indicateurs IMAP ne correspondent pas à la demande.')
        return {'id':identifiant,'flags':sorted(flags),'equivalence_suivi':'drapeau IMAP' if 'suivi' in change else None}
    finally:
        try:c.logout()
        except Exception:pass

async def modifier(data,user):
    boite,nom,autorises=await _contexte(data,user,True);change=changements(data)
    from mail.lecture import _resoudre,_controler_identifiant
    reference=str(data.get('ref') or '')
    identifiant=_resoudre(reference,boite)
    if identifiant and nom=='imap' and '|' not in identifiant:identifiant=None   # une ref inventée par le modèle
    if not identifiant:
        # « MARQUE-LE COMME LU » SANS RECITER LE MAIL (17/09) : la conversation sait quel mail
        # elle vient de voir — par son objet, son expéditeur, ou le dernier vu.
        from mail import vus
        from security.conversation import fil_courant
        reference=vus.retrouver(data.get('_fil') or fil_courant.get(),boite,data.get('objet'),data.get('de')) or ''
        identifiant=_resoudre(reference,boite) if reference else None
    if not identifiant:raise ValueError('Ouvre d’abord le message pour obtenir sa référence.')
    if nom=='outlook':preuve=await _outlook_modifier(boite,identifiant,change)
    elif nom=='imap':preuve=await asyncio.to_thread(_imap_modifier,identifiant,change,autorises)
    else:
        from mail.google_perso import rafraichir
        await rafraichir();preuve=await asyncio.to_thread(_gmail_modifier,boite,identifiant,change)
    return {'ok':True,'modifie':True,'envoye':False,'boite':boite,'ref':reference,
            'effect_status':'verified','evidence_refs':[{'fournisseur':nom,**preuve}],
            'message':'Les indicateurs demandés ont été relus chez le fournisseur.'}

SKILLS={
 'capacites_messagerie':Declaration(capacites,'Lister les opérations de messagerie et les autorisations nécessaires de la boîte choisie.',optionnels=['boite'],effet='lecture',libelle='je vérifie les capacités de cette boîte'),
 'modifier_indicateurs_mail':Declaration(modifier,'`ref` du message si tu l’as (liste MAILS DÉJÀ VUS) ; sans elle, `objet` ou `de` le désignent, et sans rien c’est le DERNIER mail vu dans la conversation. Modifier puis vérifier les indicateurs d’un message existant : lu/non lu, suivi actif/termine/aucun, ajout ou retrait de catégories. Aucun envoi. Sur Gmail/IMAP, suivi signifie étoile/drapeau ; termine retire cet indicateur.',requis=[],optionnels=['ref','objet','de','boite','lu','suivi','ajouter_categories','retirer_categories'],effet='externe',libelle='je mets à jour les indicateurs du message'),
}
