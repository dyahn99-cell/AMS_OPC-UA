"""Download selected official public manuals and retain page-numbered text."""
import concurrent.futures
import hashlib
import json
import urllib.request
import threading
from pathlib import Path
import pypdfium2 as pdfium

# PDFium is not thread-safe; downloads may overlap, extraction must not.
PDF_LOCK = threading.Lock()

OUT = Path(__file__).resolve().parents[2] / 'outputs/iodd/manuals'
LABELS = '''OM_D-MH2_DOC1094990EN-1.pdf
OM_D-MP_OMU0002EN-B.pdf
OM_D-MPG_DOC1073785EN-3.pdf
OM_EQ_DOC1138459EN-1.pdf
OM_EX260-MIL1_DOC1057882EN.pdf
OM_EX260-VIL_OMZ0018EN-B.pdf
OM_EX260-IO-LINK_EN-C.pdf
OM_EX260-PIL1_DOC1070047EN-2.pdf
OM_EX430-SIL1_OMY0021EN-A.pdf
OM_EX600-TDX_O-Link_DOC1113170EN-1.pdf
OM_FC3W5_OMA1018EN-C.pdf
OM_IN502_OMY1006EN-B.pdf
OM_IN502-44-45_OMZ1003EN-A.pdf
OM_ISA3-L_OMW0009EN-E.pdf
OM_ISE79S-L2_MY0007EN-E.pdf
OM_ISE70Gx-L2_OMV0009EN-I.pdf
OM_ISE7x-L2_OMV0004EN-J.pdf
OM_ITV2_00145_EN-B.pdf
OM_IZS51_doc1092338EN-1.pdf
OM_IZT41-42-L_OMT0049EN-E.pdf
OM_IZT-L_OMZ0045EN-A.pdf
OM_JXCL1_IO-Link_OMV0005EN-D.pdf
OM_PF2M7_OMW0007EN-G.pdf
OM_PF2MC7_OMZ0002EN-D.pdf
OM_PF3A7xH-L_OMX0002EN-G.pdf
OM_PFA3A7xx_DOC1057506EN-2.pdf
OM_PF3W7_OMW0010EN-I.pdf
OM_PF3W7-X445_OMV0006EN-C.pdf
OM_PFCA7_OMA1002EN-A.pdf
OM_PFUW7_DOC1066729EN-2.pdf
OM_PSE200A_OMW0012EN-F.pdf
OM_PSE54_DOC1056909EN-4.pdf
OM_PSE57_DOC1056914EN-4.pdf
OM_PSH_DOC1060358EN-2.pdf
OM_ZSE20B-L_ISE20B-L_OMU0006EN-H.pdf
OM_ZSE20C-L_ISE20C-L_OMX0002EN-F.pdf'''.splitlines()

def fetch(entry):
    label, url = entry['label'], 'https://static.smc.eu' + entry['url']
    pdf = OUT / label
    try:
        if not pdf.exists():
            data = urllib.request.urlopen(url, timeout=45).read()
            if not data.startswith(b'%PDF-'): raise ValueError('Not a PDF')
            pdf.write_bytes(data)
        with PDF_LOCK:
            reader = pdfium.PdfDocument(str(pdf))
            pages = []
            for n in range(len(reader)):
                page = reader[n]
                textpage = page.get_textpage()
                pages.append(textpage.get_text_range())
                textpage.close()
                page.close()
            reader.close()
        pdf.with_suffix('.pages.json').write_text(json.dumps(pages, ensure_ascii=False), encoding='utf-8')
        pdf.with_suffix('.txt').write_text('\n'.join(f'\n--- PDF PAGE {n+1} ---\n{text}' for n, text in enumerate(pages)), encoding='utf-8')
        return {'file': label, 'url': url, 'sha256': hashlib.sha256(pdf.read_bytes()).hexdigest(), 'pages': len(pages), 'status': 'downloaded_not_yet_reviewed'}
    except Exception as exc:
        return {'file': label, 'url': url, 'status': 'error', 'error': str(exc)}

if __name__ == '__main__':
    items = json.loads((OUT / 'official-index.json').read_text(encoding='utf-8'))
    found = {f['label']: f for i in items for d in i['documents'] if d['lang'] == 'EN' for f in d['files'] if f['label'] in LABELS}
    assert set(found) == set(LABELS), set(LABELS) - set(found)
    found['OM_ZK2-ZB1-ZL3-ZQ_DOC1051887EN-3.pdf'] = {
        'label': 'OM_ZK2-ZB1-ZL3-ZQ_DOC1051887EN-3.pdf',
        'url': '/binaries/content/assets/smc_global/product-documentation/operation-manuals/en/om_zk2-zb1-zl3-zq_doc1051887en-3.pdf',
    }
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(fetch, found.values()))
    (OUT / 'download-manifest.json').write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
    for result in results: print(result['file'], result['status'], result.get('pages', result.get('error')))
