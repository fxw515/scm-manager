#!/usr/bin/env python3
"""Read-only checks of the installed Chinese UI. No accounts/repos are created.
SPDX-License-Identifier: AGPL-3.0-only
"""
import argparse
import json
import urllib.request

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--url', required=True, help='例如 http://192.168.1.20:8090/scm')
args = parser.parse_args()
base = args.url.rstrip('/')
if not base.startswith(('http://', 'https://')):
    parser.error('URL 必须以 http:// 或 https:// 开头')
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
for name in ('admin', 'commons', 'config', 'groups', 'initialization',
             'namespaces', 'permissions', 'repos', 'users', 'plugins'):
    with opener.open(base + '/locales/zh/' + name + '.json', timeout=20) as response:
        data = json.loads(response.read().decode('utf-8'))
    if name == 'commons':
        assert data['login']['title'] == '登录', '登录词条不匹配'
    if name == 'plugins':
        assert data['scm-svn-plugin']['information']['checkout'] == '检出仓库'
        assert data['scm-git-plugin']['information']['clone'] == '克隆仓库'
    print('PASS:', name)
with opener.open(base + '/', timeout=20) as response:
    assert response.status == 200
print('PASS: 首页与 10 组中文资源可访问。账号、检出提交、锁及重启持久化请继续按 README 验收。')
