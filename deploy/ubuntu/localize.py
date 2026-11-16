#!/usr/bin/env python3
"""Validate Chinese resources and package them with the upstream 3.12.2 WAR.

Only locale JSON and compiled frontend assets are changed; backend classes and
bundled plugin archives are copied byte-for-byte. No third-party Python modules.
SPDX-License-Identifier: AGPL-3.0-only
"""
import argparse
from collections import Counter
import io
import json
from pathlib import Path
import re
import zipfile

VERSION = '3.12.2'
ROOT = Path(__file__).resolve().parents[2]
UI = Path('scm-ui/ui-webapp/public/locales')
SERVER = Path('scm-webapp/src/main/resources/locales')
PLUGINS = [Path(f'scm-plugins/scm-{name}-plugin/src/main/resources/locales')
           for name in ('git', 'svn', 'hg')]
# Product names, format strings, URLs and executable search examples stay intact.
UNCHANGED = {'SCM-Manager', 'Git', 'Subversion', 'Mercurial', 'scm-manager',
             'cloudogu', 'admin', 'admin@hitchhiker.com', '1628077286',
             '1623057235', 'yyyy-mm-dd hh:mm:ss',
             'https://platform.cloudogu.com/en/support/',
             'name:ultimate?Repository',
             'nameSpace:ultimate AND lastModified:[1609459200000 TO 1612137600000]'}


def no_duplicates(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f'Duplicate JSON key: {key}')
        result[key] = value
    return result


def read_json(data):
    return json.loads(data, object_pairs_hook=no_duplicates)


def leaves(value, path=()):
    if isinstance(value, dict):
        for key, child in value.items():
            yield from leaves(child, path + (key,))
    elif isinstance(value, list):
        for key, child in enumerate(value):
            yield from leaves(child, path + (key,))
    else:
        yield path, value


def merge(target, incoming):
    for key, value in incoming.items():
        if key not in target:
            target[key] = value
        elif isinstance(value, dict) and isinstance(target[key], dict):
            merge(target[key], value)
        elif target[key] != value:
            raise ValueError(f'Conflicting plugin translation: {key}')


def resources(root=ROOT):
    pairs = [(p, p.parent.parent / 'zh' / p.name)
             for p in sorted((root / UI / 'en').glob('*.json'))]
    pairs += [(root / p / 'en/plugins.json', root / p / 'zh/plugins.json')
              for p in [SERVER, *PLUGINS]]
    if len(pairs) != 13:
        raise ValueError('Expected 13 core locale files for SCM-Manager 3.12.2')
    total = 0
    for en_path, zh_path in pairs:
        en = dict(leaves(read_json(en_path.read_text(encoding='utf-8'))))
        zh = dict(leaves(read_json(zh_path.read_text(encoding='utf-8'))))
        if en.keys() != zh.keys():
            raise ValueError(f'{zh_path}: missing or extra translation keys')
        for key, original in en.items():
            translated = zh[key]
            if not isinstance(translated, str) or not translated.strip():
                raise ValueError(f'{zh_path}: empty/non-string value: {key}')
            # Preserve interpolation variables and React Trans markup exactly.
            for pattern in (r'\{\{.*?\}\}', r'</?[\w]+\s*/?>'):
                if Counter(re.findall(pattern, original)) != Counter(re.findall(pattern, translated)):
                    raise ValueError(f'{zh_path}: placeholder mismatch: {key}')
            if original == translated and original not in UNCHANGED:
                raise ValueError(f'{zh_path}: untranslated value: {key}')
            if original not in UNCHANGED and not re.search(r'[\u4e00-\u9fff]', translated):
                raise ValueError(f'{zh_path}: missing Chinese text: {key}')
        total += len(en)
    return pairs, total


def package(input_war, output_war, assets, root=ROOT):
    pairs, total = resources(root)
    if input_war.resolve() == output_war.resolve():
        raise ValueError('Input and output WAR must differ')
    additions = {}
    plugin_zh = {}
    with zipfile.ZipFile(input_war) as source:
        if f'WEB-INF/lib/scm-core-{VERSION}.jar' not in source.namelist():
            raise ValueError(f'Expected upstream SCM-Manager {VERSION}')
        for en_path, zh_path in pairs:
            relative = en_path.relative_to(root).as_posix()
            en = read_json(en_path.read_text(encoding='utf-8'))
            if relative.startswith(UI.as_posix()):
                upstream = read_json(source.read('locales/en/' + en_path.name))
                additions['locales/zh/' + zh_path.name] = zh_path.read_bytes()
            elif relative.startswith(SERVER.as_posix()):
                upstream = read_json(source.read('WEB-INF/classes/locales/en/plugins.json'))
                merge(plugin_zh, read_json(zh_path.read_text(encoding='utf-8')))
            else:
                plugin_name = en_path.relative_to(root).parts[1]
                with zipfile.ZipFile(io.BytesIO(source.read(f'WEB-INF/plugins/{plugin_name}.smp'))) as plugin:
                    upstream = read_json(plugin.read('classes/locales/en/plugins.json'))
                merge(plugin_zh, read_json(zh_path.read_text(encoding='utf-8')))
            if en != upstream:
                raise ValueError(f'Upstream locale differs from source: {en_path}')
        additions['WEB-INF/classes/locales/zh/plugins.json'] = (
            json.dumps(plugin_zh, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
        if not (assets / 'webapp.bundle.js').is_file():
            raise ValueError('Build the localized frontend before packaging')
        for path in assets.rglob('*'):
            if path.is_symlink():
                raise ValueError(f'Symlink in assets: {path}')
            if path.is_file():
                additions['assets/' + path.relative_to(assets).as_posix()] = path.read_bytes()
        output_war.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(output_war, 'w', compression=zipfile.ZIP_DEFLATED) as target:
            seen = set()
            for entry in source.infolist():
                if entry.filename not in additions and entry.filename not in seen:
                    # Upstream has duplicate README entries. Zip name lookup
                    # selects the last entry; preserve that effective content.
                    target.writestr(entry, source.read(entry.filename))
                    seen.add(entry.filename)
            for name, data in sorted(additions.items()):
                target.writestr(name, data)
    print(f'Packaged {total} locale values; backend and bundled plugins preserved')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--input-war', type=Path)
    parser.add_argument('--output-war', type=Path)
    parser.add_argument('--assets', type=Path, default=ROOT / 'scm-ui/build/webapp/assets')
    args = parser.parse_args()
    if args.check:
        pairs, total = resources()
        print(f'PASS: {len(pairs)} files, {total} values, matching keys/placeholders/markup')
    elif args.input_war and args.output_war:
        package(args.input_war, args.output_war, args.assets)
    else:
        parser.error('Use --check or --input-war and --output-war')


if __name__ == '__main__':
    main()
