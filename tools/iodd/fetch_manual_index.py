"""Read the public SMC operation manual index. No equipment access."""
import concurrent.futures
import html
import json
import re
import urllib.request
from pathlib import Path

OUT = Path(__file__).resolve().parents[2] / 'outputs/iodd/manuals'
BASE = 'https://www.smc.eu/en-ie/products/standards-and-manuals/operation-manuals'

def page(number):
    target = OUT / f'index-{number}.html'
    if not target.exists():
        data = urllib.request.urlopen(f'{BASE}?pageSize=100&page={number}&lastPageSize=100', timeout=35).read()
        target.write_bytes(data)
    text = target.read_text(encoding='utf-8')
    body = re.search(r'<div id="js--contentLister"[^>]*>(.*?)</div>', text, re.S).group(1)
    return json.loads(html.unescape(body))['items']

if __name__ == '__main__':
    OUT.mkdir(exist_ok=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        pages = list(pool.map(page, range(1, 12)))
    items = [i for p in pages for i in p]
    (OUT / 'official-index.json').write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding='utf-8')
    pattern = re.compile(r'PF2M|PF3A|PF3W|PFCA|PFUW|D-MH|D-MP|FC3W|IN502|IZS51|IZT4|EX260|EX430|EX600-T|ITV|PSH|ISA3|ISE7|ISE20|PSE2|PSE54|PSE57|ZSE10|JXCL|EQ', re.I)
    selected = [i for i in items if pattern.search(str(i.get('series')) + ' ' + str(i.get('models')))]
    (OUT / 'candidate-manuals.json').write_text(json.dumps(selected, ensure_ascii=False, indent=2), encoding='utf-8')
    for item in selected:
        files = [f['label'] for d in item['documents'] if d['lang'] == 'EN' for f in d['files']]
        print(item['series'], item['models'], '; '.join(files))
    print('Index entries:', len(items), 'Candidate entries:', len(selected))
