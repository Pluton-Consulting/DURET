"""Vérifications simples d'accès : un geste réel avant d'affirmer une capacité.

Les formulations non ambiguës évitent une inférence inutile. Le catalogue du
rôle borne les choix ; l'exécution passe toujours par les gardes habituels.
"""
import re,unicodedata

def premiere_lecture(state,disponibles):
    if any(state.get(k) for k in ('tool_results','tools_finished','redaction_forcee','plan_valide','pending_action','attachments')):return None
    q=''.join(c for c in unicodedata.normalize('NFKD',str(state.get('query') or '').lower()) if not unicodedata.combining(c))
    q=re.sub(r"[?!.,]+$",'',q.strip()).strip()
    acces=re.fullmatch(r"(?:tu as|as-tu|vous avez|avez-vous|est-ce que tu as) acces (?:au|aux|a mes|a la|a mon) (nas|drive|dossiers|mails|mail|messagerie)",q)
    if acces and acces[1] in ('mails','mail','messagerie'):
        return {'skill':'lire_mails','args':{'limite':1}} if 'lire_mails' in disponibles else None
    racine=re.fullmatch(r"(?:j'ai quoi comme dossiers?|liste(?: moi)? (?:les|mes) dossiers?) (?:dans le|du|sur le) (nas|drive)",q)
    if not acces and not racine:return None
    demande=acces[1] if acces else racine[1]
    # Sur Duret, « Drive » désigne aussi le partage Drive du NAS.
    candidats=['nas_arborescence'] if demande=='nas' else ['drive_arborescence','nas_arborescence']
    for nom in candidats:
        if nom in disponibles:return {'skill':nom,'args':{'profondeur':1}}
    return None
