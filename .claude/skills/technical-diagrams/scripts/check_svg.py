#!/usr/bin/env python3
"""Basic local SVG checks; no rendering, layout analysis or security guarantee."""
import argparse
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


def check(path):
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError) as exc:
        return [str(exc)]
    problems = []
    if root.tag != '{http://www.w3.org/2000/svg}svg':
        problems.append('root must be an SVG element in the SVG namespace')
    try:
        box = [float(v) for v in re.split(r'[\s,]+', root.get('viewBox', '').strip())]
        if len(box) != 4 or not all(__import__('math').isfinite(v) for v in box) or min(box[2:]) <= 0:
            raise ValueError
    except ValueError:
        problems.append('viewBox must contain four finite numbers with positive width/height')
    ids = set()
    refs = set()
    for node in root.iter():
        ident = node.get('id')
        if ident:
            if ident in ids:
                problems.append(f'duplicate id: {ident}')
            ids.add(ident)
        for key, value in node.attrib.items():
            refs.update(re.findall(r'url\(\s*[\'"]?#([^\s)\'";]+)[\'"]?\s*\)', value))
            if key in ('href', '{http://www.w3.org/1999/xlink}href') and value.startswith('#'):
                refs.add(value[1:])
        if node.tag == '{http://www.w3.org/2000/svg}style' and node.text:
            refs.update(re.findall(r'url\(\s*#([^\s)]+)\s*\)', node.text))
    problems.extend(f'missing local reference: {ref}' for ref in sorted(refs - ids))
    for tag in ('title', 'desc'):
        node = root.find('{http://www.w3.org/2000/svg}' + tag)
        if node is None or not ''.join(node.itertext()).strip():
            problems.append(f'missing nonempty {tag}')
    return problems


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('files', nargs='+', type=Path)
    args = parser.parse_args()
    failed = False
    for path in args.files:
        errors = check(path)
        failed |= bool(errors)
        print(f'{path}: ' + ('FAIL: ' + '; '.join(errors) if errors else 'OK (structure only)'))
    return int(failed)


if __name__ == '__main__':
    sys.exit(main())
