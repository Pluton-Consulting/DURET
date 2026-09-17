"""Lecture analytique : pages et cellules identifiables, distincte de l’aperçu UI."""
import io,json

def lire(nom,octets,texte_secours=''):
    ext=nom.rsplit('.',1)[-1].lower()
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
                    if len(pdf)<=5 and len(contenu.strip())<2000:
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
