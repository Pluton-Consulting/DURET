"""Lecture analytique : pages et cellules identifiables, distincte de l’aperçu UI."""
import io,json,re

def en_docx(octets,ext):
    """Un Word ancien (.doc), un .rtf ou un .odt converti en .docx par LibreOffice (déjà dans l'image).

    21/09 (prompt 1 du cahier Duret) : le RC et le CCAP de la piscine Mouriscot sont des « .doc »
    — le rédacteur les écartait (« format non lu ») et déclarait ABSENTES la date limite et les
    pénalités, qu'ils portent. Le texte converti se lit comme n'importe quel Word.
    """
    import shutil,subprocess,tempfile
    from pathlib import Path
    binaire=shutil.which('libreoffice') or shutil.which('soffice')
    if not binaire and Path('/Applications/LibreOffice.app/Contents/MacOS/soffice').exists():binaire='/Applications/LibreOffice.app/Contents/MacOS/soffice'
    if not binaire:raise ValueError('Le moteur LibreOffice n’est pas installé : ce .'+ext+' ne peut pas être lu.')
    with tempfile.TemporaryDirectory(prefix='lecture-'+ext+'-') as dossier:
        dossier=Path(dossier);source=dossier/('piece.'+ext);source.write_bytes(octets)
        profil=dossier/'profil';(profil/'user').mkdir(parents=True)
        try:
            r=subprocess.run([binaire,'-env:UserInstallation='+profil.as_uri(),'--headless','--nologo','--nodefault','--norestore','--convert-to','docx','--outdir',str(dossier),str(source)],capture_output=True,timeout=90)
        except subprocess.TimeoutExpired:raise ValueError('La conversion du .'+ext+' a dépassé son délai.') from None
        sortie=dossier/'piece.docx'
        if r.returncode or not sortie.exists():raise ValueError('La conversion du .'+ext+' a échoué.')
        return sortie.read_bytes()

def lire(nom,octets,texte_secours=''):
    ext=nom.rsplit('.',1)[-1].lower()
    if ext in ('doc','rtf','odt'):
        return lire(nom.rsplit('.',1)[0]+'.docx',en_docx(octets,ext),texte_secours)
    if ext in ('xlsx','xlsm'):
        from openpyxl import load_workbook
        valeurs=load_workbook(io.BytesIO(octets),read_only=True,data_only=True)
        formules=load_workbook(io.BytesIO(octets),read_only=True,data_only=False)
        parties=[]
        try:
            for ws in valeurs.worksheets:
                if (ws.max_row and ws.max_row>100000) or (ws.max_column and ws.max_column>2000) or (ws.max_row or 0)*(ws.max_column or 0)>2000000:raise ValueError('Feuille au-delà de 100 000 lignes ; fractionnez le classeur avant analyse.')
                wf=formules[ws.title]
                for rang,(ligne,fl) in enumerate(zip(ws.iter_rows(),wf.iter_rows()),1):
                    cellules=[]
                    for cell,formula in zip(ligne,fl):
                        value=cell.value
                        if value is None and formula.data_type=='f':value='FORMULE SANS VALEUR CALCULÉE : '+str(formula.value)
                        if value is not None:cellules.append(f'{cell.coordinate}={json.dumps(str(value),ensure_ascii=False)}')
                    if cellules:parties.append(f'Feuille {ws.title} — ligne {rang} : '+' | '.join(cellules))
            return '\n'.join(parties)
        finally:valeurs.close();formules.close()
    if ext=='pdf':
        import fitz
        with fitz.open(stream=octets,filetype='pdf') as pdf:
            pages=[];non_vides=0
            for i,page in enumerate(pdf):
                contenu=page.get_text()
                if len(contenu.strip())<20:contenu='[LECTURE VISUELLE REQUISE : page sans couche texte exploitable]'
                else:
                    non_vides+=1
                    # Un petit PDF de planning ou schéma garde souvent ses légendes en texte,
                    # mais les relations (barres, flèches, couleurs) sont graphiques.
                    # Un logo isolé ne justifie pas une lecture visuelle de chaque page.
                    # 17/09 : un plan d'architecte porte 3 000 à 5 000 caractères… de COTES
                    # en vrac (« 2,40 / 5,00 / 0,07 »), sans lien avec les pièces : du
                    # texte, mais illisible sans le dessin. Une page courte dont la
                    # majorité des lignes sont des nombres est un dessin, elle aussi.
                    lignes_page=[l.strip() for l in contenu.splitlines() if l.strip()]
                    chiffres=sum(1 for l in lignes_page if re.fullmatch(r'[\d\s,.+\-x=×%°/]*(?:NGF|m2|m²|ml|cm|mm)?',l))
                    plan_cote=len(pdf)<=5 and len(lignes_page)>=40 and chiffres>len(lignes_page)*0.5
                    if len(pdf)<=5 and (len(contenu.strip())<2000 or plan_cote):
                        dessins=page.get_drawings()
                        surface=page.rect.width*page.rect.height
                        images=page.get_image_info()
                        image_importante=any((x['bbox'][2]-x['bbox'][0])*(x['bbox'][3]-x['bbox'][1])>surface*.25 for x in images)
                        if len(dessins)>=20 or image_importante:
                            contenu='[LECTURE VISUELLE REQUISE : relations graphiques non représentées par le texte]\n'+contenu
                pages.append(f'=== Page {i+1} ===\n'+contenu)
        texte='\n\n'.join(pages)
        # Le texte OCR existant ne doit pas être remplacé par des numéros de pages vides.
        if non_vides:return texte
        if texte_secours.strip():return texte_secours
        return '[LECTURE VISUELLE REQUISE : PDF sans couche texte exploitable]'
    if ext in ('png','jpg','jpeg','webp','tif','tiff','bmp'):
        return '[LECTURE VISUELLE REQUISE : image à analyser]'
    if ext=='docx':
        from docx import Document
        from docx.oxml.ns import qn
        doc=Document(io.BytesIO(octets));parts=[]
        for i,e in enumerate(doc.element.body,1):
            t=' '.join(n.text or '' for n in e.iter(qn('w:t')))
            if t.strip():parts.append(f'Bloc Word {i} : {t}')
        for rang,section in enumerate(doc.sections,1):
            for genre,element in [('en-tête',section.header),('pied',section.footer)]:
                t=' '.join(n.text or '' for n in element._element.iter(qn('w:t')))
                if t.strip():parts.append(f'Section {rang} {genre} : {t}')
        return '\n'.join(parts)
    if texte_secours:return texte_secours
    from ingestion.parsers import analyser,ligne_en_texte
    structure=analyser(nom,octets)
    if structure.get('kind')=='tabulaire':
        return '\n'.join(f'Ligne {i+1} : {ligne_en_texte(r)}' for i,r in enumerate(structure.get('rows') or []))
    return structure.get('text') or ''
