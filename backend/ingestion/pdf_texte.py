"""Extraction PDF isolée : aucun moteur PDF natif partagé entre threads.

Le parent borne et termine ce processus. Les octets et le texte circulent dans
des tubes privés, sans fichier temporaire ni journal contenant le document.
"""
import io
import json
import sys


def extraire(brut, maximum):
    try:
        try:
            import pymupdf as fitz
        except ImportError:
            import fitz
        with fitz.open(stream=brut, filetype='pdf') as doc:
            total=len(doc)
            morceaux=[doc[i].get_text('text',sort=True) for i in range(min(total,maximum))]
        return {'texte':'\n\n'.join(morceaux).strip(),'pages_lues':min(total,maximum),'pages_total':total}
    except Exception:
        # Le moteur historique reste disponible pour les PDF que le lecteur
        # rapide refuse. Il est soumis au même délai de processus.
        import pdfplumber
        with pdfplumber.open(io.BytesIO(brut)) as doc:
            total=len(doc.pages);morceaux=[]
            for page in doc.pages[:maximum]:
                morceaux.append(page.extract_text() or '')
                page.close()
        return {'texte':'\n\n'.join(morceaux).strip(),'pages_lues':min(total,maximum),'pages_total':total}


if __name__=='__main__':
    try:
        maximum=int(sys.argv[1])
        if not 1<=maximum<=2000:raise ValueError('Limite de pages invalide')
        resultat=extraire(sys.stdin.buffer.read(),maximum)
        sys.stdout.buffer.write(json.dumps(resultat,ensure_ascii=False).encode('utf-8'))
    except Exception as e:
        # Aucun texte du document dans stderr, même pour un PDF malformé.
        sys.stderr.write(type(e).__name__)
        sys.exit(1)
