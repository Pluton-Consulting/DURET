"""
LA MARQUE — Duret & Sols.

LE SEUL fichier des mails qui diffère d'un client à l'autre. Quatre valeurs :
le nom, la couleur d'accent (le bouton), le fond de l'en-tête, et le logo.
Dupliquer le produit pour un nouveau client, c'est réécrire ce fichier — et
rien d'autre dans `emails/`.

LE LOGO EST DESSINÉ EN CELLULES DE TABLEAU BORDÉES, pas en SVG ni en image :
les clients de messagerie n'affichent pas le SVG, et une image distante est
bloquée par défaut chez la plupart — le destinataire verrait un cadre vide à
la place de la marque. Des bordures, elles, s'affichent partout, Outlook
compris. La composition est celle du logo : jaune au-dessus du rouge à gauche,
grand carré bleu à droite.
"""

_LOGO = """<table cellpadding="0" cellspacing="0" border="0" style="font-size:0;line-height:0">
                    <tr>
                      <td style="width:24px"></td>
                      <td style="padding-bottom:5px">
                        <div style="width:8px;height:8px;border:3px solid #FFE202;font-size:0;line-height:0"></div>
                      </td>
                      <td rowspan="2" style="padding-left:7px;vertical-align:middle">
                        <div style="width:32px;height:32px;border:3px solid #0687DA;font-size:0;line-height:0"></div>
                      </td>
                    </tr>
                    <tr>
                      <td colspan="2">
                        <div style="width:15px;height:15px;border:3px solid #F41122;font-size:0;line-height:0"></div>
                      </td>
                    </tr>
                  </table>"""

# LE VRAI LOGO, quand il est fourni. Le fichier est cherché à côté de ce
# module ; s'il manque, on garde la pastille dessinée ci-dessus — un mail sans
# logo reste lisible, un mail avec un cadre vide fait négligé.
#
# POURQUOI UN PNG ET PAS UN SVG : aucun client de messagerie ne rend le SVG. Et
# pourquoi pas une image distante : la plupart les bloquent par défaut, et
# celle-ci vivrait de toute façon derrière le VPN, donc inatteignable depuis un
# téléphone hors réseau.
LOGO_FICHIER = "logo.png"
LOGO_CONTENT_ID = "logo-marque"

MARQUE = {
    "nom": "Duret & Sols",
    "couleur": "#0A6FB4",          # le bouton : bleu de la charte
    "fond": "#0B0E11",             # l'en-tête : le noir de la marque
    "baseline": "#9DD1F2",         # la ligne « Assistant IA interne »
    "logo": _LOGO,
    "expediteur_defaut": "Duret & Sols <Duret-Sols@duret-sols.fr>",
}


def logo_image():
    """Les octets du vrai logo, ou None. Ne lève jamais.

    Rendre None n'est pas une panne : le gabarit retombe sur la pastille
    dessinée en HTML, qui ne dépend d'aucun fichier.
    """
    import pathlib as _p

    chemin = _p.Path(__file__).with_name(LOGO_FICHIER)
    try:
        if chemin.exists() and chemin.stat().st_size > 0:
            return {"content_id": LOGO_CONTENT_ID, "nom": LOGO_FICHIER,
                    "mime": "image/png", "octets": chemin.read_bytes()}
    except OSError:
        pass
    return None
