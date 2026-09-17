"""Consulter et préciser le travail en cours, sans remplacer l'historique."""
import asyncio
from skills.registre import Declaration
from ressources import travail

def _identite(data,user):
    fil=str(data.get('_fil') or '')
    if not fil or not getattr(user,'id',None):raise ValueError('Conversation courante requise.')
    return str(user.id),fil

async def consulter(data,user):
    uid,fil=_identite(data,user);etat=await asyncio.to_thread(travail.lire,uid,fil)
    page=max(1,int(data.get('page') or 1));taille=20
    contraintes=etat.get('contraintes',[]);debut=(page-1)*taille
    return {**etat,'contraintes':contraintes[debut:debut+taille],
            'page':page,'total_contraintes':len(contraintes),'page_suivante':page+1 if debut+taille<len(contraintes) else None,
            'resultats':etat.get('resultats',[])[-20:],'references':etat.get('references',[])[-30:]}

async def retenir(data,user):
    uid,fil=_identite(data,user)
    etat=await asyncio.to_thread(travail.retenir,uid,fil,str(data.get('citation') or ''),str(data.get('source') or ''),data.get('remplace'))
    return {'ok':True,'retenu':True,'revision':etat['revision'],'contraintes':etat['contraintes']}

SKILLS={
 'consulter_travail':Declaration(consulter,'Relire l’objectif, les contraintes citées par l’utilisateur, le plan accepté et les résultats observés de CETTE conversation. Paginer les contraintes si nécessaire.',optionnels=['page'],effet='lecture',libelle='je relis le travail en cours'),
 'retenir_contrainte_travail':Declaration(retenir,'Retenir une citation exacte d’une demande de ce fil comme contrainte ; source est la ref de la demande. remplace désactive une ancienne contrainte explicitement corrigée, sans effacer son historique.',requis=['citation','source'],optionnels=['remplace'],effet='ecriture_interne',libelle='je retiens la précision pour ce travail'),
}
