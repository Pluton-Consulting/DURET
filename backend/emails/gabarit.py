"""
LE GABARIT DES MAILS — une seule structure, pour les deux clients.

Ce fichier est du SOCLE : il est identique d'un projet à l'autre, au caractère
près. Tout ce qui distingue une marque de l'autre — le nom, le logo, la
couleur, l'expéditeur — vit dans `emails/marque.py`, et NULLE PART ailleurs.
Changer de client, c'est remplacer ce seul fichier.

POURQUOI CE DÉCOUPAGE. Les deux mails de connexion avaient dérivé chacun de
leur côté : titres différents, expéditeurs différents, mise en page différente,
l'un signé « PLUTON », l'autre du nom du client. Un destinataire ne pouvait pas
reconnaître qu'il s'agissait du même produit, et corriger une faute obligeait à
la corriger deux fois — donc à l'oublier une fois sur deux.

TROIS CONTRAINTES DE MESSAGERIE, apprises à la dure et respectées ici :
  1. pas de CSS externe ni de balise <style> — Gmail les jette : tout est en
     attribut `style` sur chaque élément ;
  2. pas d'image distante pour le logo — la plupart des clients bloquent les
     images par défaut, et le destinataire verrait un cadre vide à la place de
     la marque : le logo est DESSINÉ en cellules de tableau bordées, qui
     s'affichent partout, Outlook compris ;
  3. la mise en page est faite de <table>, pas de flex ni de grid — Outlook
     rend encore avec le moteur de Word.

L'APERÇU (le texte gris que la boîte de réception affiche après l'objet) n'est
pas décoratif : sans lui, les clients de messagerie y recopient le début du
HTML, c'est-à-dire n'importe quoi. On le pose donc explicitement, masqué en
tête de corps.
"""
from __future__ import annotations

from emails.marque import (LOGO_CONTENT_ID, LOGO_PORTE_LE_NOM, MARQUE,
                           logo_image)


def _entete_html() -> str:
    """Le bandeau de marque du mail, dans la forme que le logo disponible permet.

    DEUX FORMES, ET C'EST UNE QUESTION DE LISIBILITÉ, PAS DE GOÛT.

    · AVEC LE VRAI LOGO (`emails/logo.png`) : fond CLAIR et logotype seul, comme
      dans l'en-tête de l'application. Le logotype de la maison est un MOT écrit
      en vert forêt : posé sur le vert très foncé du bandeau, il serait
      illisible. Et le nom n'est pas répété à côté, puisque le logotype le
      contient déjà — c'est précisément ce qui le distingue d'un symbole.

    · SANS LUI : le bandeau sombre et la pastille dessinée, tels qu'avant. Cette
      forme ne dépend d'aucun fichier, elle est donc le repli sûr.
    """
    if logo_image() is None:
        return (
            f'<tr><td style="background:{MARQUE["fond"]};padding:28px 40px">'
            f'<table cellpadding="0" cellspacing="0" border="0"><tr>'
            f'<td style="vertical-align:middle;padding-right:14px">{MARQUE["logo"]}</td>'
            f'<td style="vertical-align:middle">'
            f'<div style="color:#ffffff;font-size:18px;font-weight:800;'
            f'letter-spacing:-0.3px;line-height:1.15">{MARQUE["nom"]}</div>'
            f'<div style="color:{MARQUE["baseline"]};font-size:11px;font-weight:500;'
            f'margin-top:4px">Assistant IA interne</div>'
            f'</td></tr></table></td></tr>')
    # Le nom n'est répété QUE si le logo ne le porte pas : un logotype qui
    # contient déjà le mot ferait doublon, un symbole seul laisserait le
    # destinataire sans savoir de qui vient le message.
    nom_ecrit = "" if LOGO_PORTE_LE_NOM else (
        f'<div style="color:{MARQUE["fond"]};font-size:17px;font-weight:800;'
        f'letter-spacing:-0.3px;margin-top:10px">{MARQUE["nom"]}</div>')
    return (
        f'<tr><td style="background:#ffffff;padding:26px 40px 22px;'
        f'border-bottom:1px solid {_BORDURE}">'
        f'{_logo_html()}'
        f'{nom_ecrit}'
        f'<div style="color:{_TEXTE_DOUX};font-size:11px;font-weight:500;'
        f'margin-top:8px">Assistant IA interne</div>'
        f'</td></tr>')


def _logo_html() -> str:
    """Le vrai logo s'il est fourni, la pastille dessinée sinon.

    L'image est référencée par `cid:` : elle voyage AVEC le message, en pièce
    jointe « inline ». C'est la seule façon d'afficher un logo qui s'affiche
    vraiment — le SVG du site n'est rendu par aucun client de messagerie, et une
    image distante est bloquée par défaut (et ici inatteignable, le site vivant
    derrière le VPN).

    La hauteur est fixée en attribut ET en style : les vieux clients ignorent
    l'un ou l'autre, et une image sans dimension casse la mise en page.
    """
    if logo_image() is None:
        return MARQUE["logo"]
    return (f'<img src="cid:{LOGO_CONTENT_ID}" alt="{MARQUE["nom"]}" '
            f'height="30" style="height:30px;width:auto;display:block;border:0" />')

# Les gris sont communs aux deux marques : seule la couleur d'accent change.
# Les figer ici plutôt que dans `marque.py` évite qu'une duplication de projet
# fasse dériver la lisibilité du texte en même temps que la charte.
_FOND_PAGE = "#F4F6F8"
_TEXTE = "#2E3742"
_TEXTE_DOUX = "#6B7785"
_TITRE = "#0B0E11"
_BORDURE = "#E6EAEF"

_ENVELOPPE = """<!DOCTYPE html>
<html lang="fr">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:{fond_page};font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif">

  <!-- Aperçu de la boîte de réception : masqué à l'écran, lu par le client de
       messagerie. Les espaces insécables qui suivent l'empêchent d'aller
       chercher la suite du HTML pour compléter la ligne. -->
  <div style="display:none;font-size:1px;color:{fond_page};line-height:1px;max-height:0;max-width:0;opacity:0;overflow:hidden">
    {apercu}&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;
  </div>

  <table width="100%" cellpadding="0" cellspacing="0" border="0" style="background:{fond_page};padding:40px 12px">
    <tr><td align="center">
      <table width="520" cellpadding="0" cellspacing="0" border="0" style="max-width:520px;background:#ffffff;border-radius:16px;overflow:hidden;box-shadow:0 2px 16px rgba(11,14,17,0.08)">

        <!-- ── En-tête : le SEUL endroit qui porte la marque ── -->
        {entete_marque}

        <!-- ── Corps ── -->
        <tr>
          <td style="padding:36px 40px 8px">
            <h1 style="margin:0 0 14px;font-size:22px;font-weight:700;color:{titre};letter-spacing:-0.4px;line-height:1.3">{titre_mail}</h1>
            {corps}
          </td>
        </tr>

        {bloc_cta}

        <!-- ── Pied ── -->
        <tr>
          <td style="padding:8px 40px 32px">
            <div style="border-top:1px solid {bordure};padding-top:20px">
              {pied}
            </div>
          </td>
        </tr>

      </table>

      <div style="max-width:520px;margin:18px auto 0;font-size:11px;color:{texte_doux};line-height:1.5;text-align:center">
        {nom} · assistant interne. Message automatique, merci de ne pas y répondre.
      </div>

    </td></tr>
  </table>
</body>
</html>"""

_CTA = """
        <tr>
          <td style="padding:20px 40px 28px">
            <table cellpadding="0" cellspacing="0" border="0">
              <tr>
                <td style="border-radius:10px;background:{couleur}">
                  <a href="{url}" style="display:inline-block;padding:14px 30px;font-size:15px;font-weight:700;color:#ffffff;text-decoration:none;border-radius:10px">{libelle}</a>
                </td>
              </tr>
            </table>
          </td>
        </tr>"""


def enveloppe(titre_mail: str, apercu: str, corps: str,
              cta_libelle: str | None = None, cta_url: str | None = None,
              pied: str = "") -> str:
    """Assemble un mail complet à partir du gabarit commun.

    `corps` et `pied` sont du HTML déjà rendu (paragraphes stylés). Le bouton
    n'apparaît que si on lui donne une adresse : un mail purement informatif
    utilise la même enveloppe, sans appel à l'action.
    """
    bloc_cta = ""
    if cta_url and cta_libelle:
        bloc_cta = _CTA.format(couleur=MARQUE["couleur"], url=cta_url, libelle=cta_libelle)
    return _ENVELOPPE.format(
        fond_page=_FOND_PAGE,
        entete_marque=_entete_html(),
        nom=MARQUE["nom"],
        titre=_TITRE,
        titre_mail=titre_mail,
        apercu=apercu,
        corps=corps,
        bloc_cta=bloc_cta,
        pied=pied,
        bordure=_BORDURE,
        texte_doux=_TEXTE_DOUX,
    )


def paragraphe(html: str, doux: bool = False) -> str:
    """Un paragraphe aux réglages du gabarit — pour ne pas réinventer la typo."""
    couleur = _TEXTE_DOUX if doux else _TEXTE
    taille = "13px" if doux else "15px"
    return (f'<p style="margin:0 0 18px;font-size:{taille};color:{couleur};line-height:1.6">'
            f'{html}</p>')


def mail_connexion(lien: str, minutes: int) -> tuple[str, str, str]:
    """Le mail de connexion : (objet, aperçu, html).

    L'objet et l'aperçu sont les MÊMES pour tous les clients, au nom près : ce
    que voit le destinataire dans sa boîte doit être reconnaissable d'un projet
    à l'autre, c'est ce qui fait qu'un mail n'est pas pris pour du hameçonnage.
    """
    objet = f"Votre lien de connexion · {MARQUE['nom']}"
    apercu = f"Lien à usage unique, valable {minutes} minutes."

    corps = (
        paragraphe("Bonjour,") +
        paragraphe(
            f"Vous avez demandé à vous connecter à <strong>{MARQUE['nom']}</strong>. "
            f"Le bouton ci-dessous vous ouvre la session directement : il n'y a "
            f"ni mot de passe à retenir, ni code à recopier."
        ) +
        paragraphe(
            f"Ce lien est à <strong>usage unique</strong> et expire dans "
            f"<strong>{minutes}&nbsp;minutes</strong>."
        )
    )

    # Le lien en clair EN PLUS du bouton : certains clients d'entreprise
    # réécrivent ou neutralisent les boutons, et le destinataire se retrouve
    # alors sans aucun moyen d'entrer.
    pied = (
        paragraphe("Le bouton ne fonctionne pas ? Copiez cette adresse dans votre navigateur :", doux=True) +
        f'<div style="font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:11.5px;'
        f'color:{_TEXTE_DOUX};background:{_FOND_PAGE};border:1px solid {_BORDURE};'
        f'border-radius:8px;padding:10px 12px;margin:0 0 16px;word-break:break-all">{lien}</div>' +
        paragraphe(
            "Vous n'êtes pas à l'origine de cette demande ? Ignorez ce message : "
            "sans clic de votre part, le lien expire seul et aucune session n'est ouverte.",
            doux=True)
    )

    html = enveloppe(
        titre_mail="Votre lien de connexion",
        apercu=apercu,
        corps=corps,
        cta_libelle="Ouvrir ma session",
        cta_url=lien,
        pied=pied,
    )
    return objet, apercu, html
