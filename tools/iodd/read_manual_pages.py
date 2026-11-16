import json
import re
import sys
from pathlib import Path

folder = Path(__file__).resolve().parents[2] / 'outputs/iodd/manuals'
for spec in sys.argv[1:]:
    name, numbers = spec.split(':')
    matches = list(folder.glob(name + '*.pages.json'))
    if len(matches) != 1:
        raise ValueError((name, matches))
    pages = json.loads(matches[0].read_text(encoding='utf-8'))
    for number in map(int, numbers.split(',')):
        print('\n' + matches[0].stem + ' PDF PAGE ' + str(number))
        print('\n'.join(re.sub(r'\s+', ' ', line).strip() for line in pages[number-1].splitlines() if line.strip()))
