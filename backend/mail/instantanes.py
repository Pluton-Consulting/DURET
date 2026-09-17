"""Les pièces présentées à l'accord restent celles qui seront envoyées."""
import hashlib
import asyncio


def designations(data):
    return (data.get("pieces") or data.get("pieces_jointes") or data.get("fichiers")
            or data.get("attachments") or data.get("piece") or data.get("fichier"))


async def figer(data: dict, user) -> dict:
    brut = designations(data)
    if not brut:
        return data
    from mail.skills import _boite_a_lire
    from mail.authorization import verifier_acces
    from mail.attaches import resoudre
    from bureautique.atelier import deposer_fichier
    boite = await verifier_acces(user, await _boite_a_lire(data, user), envoi=True)
    from security.lecteur import au_nom_de
    with au_nom_de(user):
        pieces, refusees = await resoudre(brut, user, boite)
    if refusees:
        raise ValueError("Pièces à corriger avant accord : " + "; ".join(str(p.get("nom") or "pièce") + " : " + str(p.get("raison") or "indisponible") for p in refusees))
    references, preuves = [], []
    for p in pieces:
        octets = p["octets"]
        jeton = await asyncio.to_thread(deposer_fichier, p["nom"], octets, str(user.id), "piece_validation")
        references.append({"ref": jeton, "nom": p["nom"]})
        preuves.append({"ref": jeton, "nom": p["nom"], "sha256": hashlib.sha256(octets).hexdigest(), "octets": len(octets)})
    return {**data, "mailbox": boite, "pieces": references, "_pieces_figees": preuves}


def verifier(data: dict, pieces: list) -> None:
    preuves = data.get("_pieces_figees")
    if preuves is None:
        return  # accords antérieurs au déploiement
    if not isinstance(preuves, list) or len(preuves) != len(pieces):
        raise ValueError("Les pièces ne correspondent plus à celles de l'accord : aucun envoi.")
    for preuve, piece in zip(preuves, pieces):
        if (preuve.get("sha256") != hashlib.sha256(piece.get("octets") or b"").hexdigest()
                or preuve.get("nom") != piece.get("nom")):
            raise ValueError("Une pièce a changé depuis l'accord : reprenez la préparation avant d'envoyer.")
