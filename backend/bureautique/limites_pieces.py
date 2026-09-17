"""Plafond des originaux, commun aux transports HTTP et WebSocket du chat."""

def taille_base64(texte):
    if not isinstance(texte,str) or len(texte)%4:
        raise ValueError("Encodage de pièce jointe invalide.")
    return len(texte)//4*3-(2 if texte.endswith("==") else 1 if texte.endswith("=") else 0)

def verifier_lot(pieces,par_fichier_mo=10,total_mo=25):
    total=0
    for piece in pieces:
        taille=taille_base64(piece.get("b64", ""))
        if taille>par_fichier_mo*1024*1024:
            raise ValueError(f"Une pièce dépasse {par_fichier_mo} Mo. Réduisez-la avant l’envoi.")
        total+=taille
    if total>total_mo*1024*1024:
        raise ValueError(f"Les pièces dépassent {total_mo} Mo au total. Répartissez-les sur plusieurs messages de la même conversation.")
    return total
