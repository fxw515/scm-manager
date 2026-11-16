# SPDX-License-Identifier: AGPL-3.0-only
import io
import json
from pathlib import Path
import shutil
import tempfile
import unittest
import zipfile

import localize


class LocalizationTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        pairs, _ = localize.resources()
        for pair in pairs:
            for source in pair:
                target = self.root / source.relative_to(localize.ROOT)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)

    def test_complete_resources(self):
        self.assertEqual(localize.resources(self.root)[1], 1342)

    def test_missing_translation_fails(self):
        path = self.root / localize.UI / 'zh/commons.json'
        data = json.loads(path.read_text(encoding='utf-8'))
        del data['login']['title']
        path.write_text(json.dumps(data), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'translation keys'):
            localize.resources(self.root)

    def test_missing_interpolation_fails(self):
        path = self.root / localize.UI / 'zh/repos.json'
        data = json.loads(path.read_text(encoding='utf-8'))
        data['branch']['delete']['confirmAlert']['message'] = '确定删除吗？'
        path.write_text(json.dumps(data), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'placeholder mismatch'):
            localize.resources(self.root)

    def test_duplicate_json_key_fails(self):
        with self.assertRaisesRegex(ValueError, 'Duplicate JSON key'):
            localize.read_json('{"title":"甲","title":"乙"}')

    def make_war(self):
        war = self.root / 'upstream.war'
        with zipfile.ZipFile(war, 'w') as z:
            z.writestr('WEB-INF/lib/scm-core-3.12.2.jar', b'upstream-core')
            z.writestr('WEB-INF/classes/Backend.class', b'backend-bytecode')
            z.writestr('locales/en/unused.json', b'{}')
            for en in (self.root / localize.UI / 'en').glob('*.json'):
                z.writestr('locales/en/' + en.name, en.read_bytes())
            z.writestr('WEB-INF/classes/locales/en/plugins.json',
                       (self.root / localize.SERVER / 'en/plugins.json').read_bytes())
            for path in localize.PLUGINS:
                buf = io.BytesIO()
                with zipfile.ZipFile(buf, 'w') as plugin:
                    plugin.writestr('classes/locales/en/plugins.json',
                                    (self.root / path / 'en/plugins.json').read_bytes())
                    plugin.writestr('classes/Plugin.class', b'plugin-bytecode')
                z.writestr(f'WEB-INF/plugins/{path.parts[1]}.smp', buf.getvalue())
        assets = self.root / 'assets'
        assets.mkdir()
        (assets / 'webapp.bundle.js').write_text('// Chinese frontend', encoding='utf-8')
        return war, assets

    def test_packaging_preserves_backend_and_plugins(self):
        original, assets = self.make_war()
        output = self.root / 'zh.war'
        localize.package(original, output, assets, self.root)
        with zipfile.ZipFile(original) as before, zipfile.ZipFile(output) as after:
            for name in before.namelist():
                self.assertEqual(before.read(name), after.read(name), name)
            self.assertEqual(json.loads(after.read('locales/zh/commons.json'))['login']['title'], '登录')
            merged = json.loads(after.read('WEB-INF/classes/locales/zh/plugins.json'))
            self.assertEqual(merged['scm-svn-plugin']['information']['checkout'], '检出仓库')
            self.assertIn('scm-git-plugin', merged)

    def test_other_upstream_version_rejected(self):
        original, assets = self.make_war()
        with zipfile.ZipFile(original, 'w') as z:
            z.writestr('WEB-INF/lib/scm-core-4.0.0.jar', b'other-version')
        with self.assertRaisesRegex(ValueError, 'Expected upstream'):
            localize.package(original, self.root / 'zh.war', assets, self.root)

    def test_changed_upstream_translations_rejected(self):
        original, assets = self.make_war()
        source = self.root / localize.UI / 'en/commons.json'
        data = json.loads(source.read_text(encoding='utf-8'))
        data['login']['title'] = 'Different upstream'
        source.write_text(json.dumps(data), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'Upstream locale differs'):
            localize.package(original, self.root / 'zh.war', assets, self.root)


if __name__ == '__main__':
    unittest.main()
