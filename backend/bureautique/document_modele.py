"""Réutiliser la présentation d'un Word pour un contenu nouveau, puis paginer.

Le corps du chantier précédent est remplacé ; styles, mise en page et en-têtes
proviennent du modèle original. Les images du corps ne sont pas automatiquement
attribuées au nouveau projet : elles se sélectionnent explicitement comme sources.
"""
import io,os,shutil,subprocess,tempfile
from pathlib import Path

def preparer_modele(jeton,uid,octets):
    from docx import Document
    from docx.oxml.ns import qn
    from bureautique import atelier
    if not atelier.fiche(jeton,uid):raise ValueError('Document inconnu.')
    doc=Document(io.BytesIO(octets))
    # Matérialiser l’héritage avant d’enlever les anciennes sections du corps.
    # Sinon le dernier sectPr reste lié à une section qui n’existe plus.
    from docx.opc.constants import RELATIONSHIP_TYPE as RT
    from docx.enum.section import WD_HEADER_FOOTER
    derniere=doc.sections[-1]
    for genre,relation in (('header',RT.HEADER),('footer',RT.FOOTER)):
        for prefixe,index in (('',WD_HEADER_FOOTER.PRIMARY),('first_page_',WD_HEADER_FOOTER.FIRST_PAGE),('even_page_',WD_HEADER_FOOTER.EVEN_PAGE)):
            histoire=getattr(derniere,prefixe+genre)
            if histoire.is_linked_to_previous:
                rid=doc.part.relate_to(histoire.part,relation)
                getattr(derniere._sectPr,'add_'+genre+'Reference')(index,rid)
    for element in list(doc.element.body):
        if element.tag!=qn('w:sectPr'):doc.element.body.remove(element)
    # Les styles nécessaires à la composition restent ceux du modèle lorsqu'ils
    # existent ; les seuls styles absents reçoivent un défaut Word standard.
    # Retirer les données cachées de l’ancien dossier : corps vide ne suffit pas
    # si commentaires, pièces incorporées ou anciennes images restent dans le ZIP.
    conserves={'styles','stylesWithEffects','settings','webSettings','fontTable','theme','numbering','header','footer'}
    for rid,relation in list(doc.part.rels.items()):
        if relation.reltype.rsplit('/',1)[-1] not in conserves or relation.is_external:del doc.part.rels[rid]
    for partie in (getattr(s,nom).part for s in doc.sections for nom in ('header','footer','first_page_header','first_page_footer','even_page_header','even_page_footer')):
        for rid,relation in list(partie.rels.items()):
            if relation.is_external and relation.reltype.rsplit('/',1)[-1]!='hyperlink':del partie.rels[rid]
    for rid,relation in list(doc.part.package.rels.items()):
        if relation.reltype.rsplit('/',1)[-1]=='custom-properties':del doc.part.package.rels[rid]
    for nom in ('title','subject','keywords','comments','category','content_status','identifier','last_modified_by'):
        setattr(doc.core_properties,nom,'')
    standard=Document()
    from copy import deepcopy
    for nom in ('Normal','Title','Subtitle','Heading 1','Heading 2','Heading 3','Heading 4','List Bullet','List Number','Table Grid'):
        if nom not in doc.styles and nom in standard.styles:doc.styles.element.append(deepcopy(standard.styles[nom].element))
    chemin=atelier._chemin(jeton,'modele.docx')
    tmp=chemin+'.tmp';doc.save(tmp);os.replace(tmp,chemin)
    return chemin

def convertir_pdf(chemin):
    binaire=shutil.which('libreoffice') or shutil.which('soffice')
    if not binaire and Path('/Applications/LibreOffice.app/Contents/MacOS/soffice').exists():binaire='/Applications/LibreOffice.app/Contents/MacOS/soffice'
    if not binaire:raise ValueError('Le moteur LibreOffice n’est pas installé ; reconstruis l’image backend.')
    with tempfile.TemporaryDirectory(prefix='pagination-document-') as dossier:
        dossier=Path(dossier);source=dossier/'document.docx';shutil.copyfile(chemin,source)
        profil=dossier/'profil';(profil/'user').mkdir(parents=True)
        (profil/'user/registrymodifications.xcu').write_text('<?xml version="1.0" encoding="UTF-8"?><oor:items xmlns:oor="http://openoffice.org/2001/registry"><item oor:path="/org.openoffice.Office.Common/Security/Scripting"><prop oor:name="MacroSecurityLevel" oor:op="fuse"><value>3</value></prop></item><item oor:path="/org.openoffice.Office.Writer/Content/Update"><prop oor:name="Link" oor:op="fuse"><value>2</value></prop></item></oor:items>')
        try:
            r=subprocess.run([binaire,'-env:UserInstallation='+profil.as_uri(),'--headless','--nologo','--nodefault','--norestore','--convert-to','pdf','--outdir',str(dossier),str(source)],capture_output=True,timeout=75)
        except subprocess.TimeoutExpired:raise ValueError('Le moteur de pagination a dépassé son délai.') from None
        pdf=dossier/'document.pdf'
        if r.returncode or not pdf.exists():raise ValueError('Le rendu PDF de contrôle a échoué.')
        return pdf.read_bytes()

def verifier_pages(chemin,maximum=None):
    if maximum is None:return {'conforme':True,'pages':None,'note':'Aucune limite de pages demandée ; aucune pagination prétendue.'}
    if type(maximum) is not int or not 1<=maximum<=2000:raise ValueError('Limite de pages invalide.')
    try:pdf=convertir_pdf(chemin)
    except ValueError as e:return {'conforme':False,'pages':None,'note':str(e)}
    import fitz
    with fitz.open(stream=pdf,filetype='pdf') as f:n=f.page_count
    return {'conforme':n<=maximum,'pages':n,'maximum':maximum,'note':f'{n} pages rendues, maximum {maximum}.'}
