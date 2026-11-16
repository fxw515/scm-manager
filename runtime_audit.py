"""Bounded evaluation of an owned, disposable localhost SVNAdmin4 instance.

No remote target option, no production credentials/data, no installation changes.
Only JSON measurements and test outcomes are exported; tokens/config/DB stay local.
"""
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import signal
import statistics
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

subject, results = (Path(x).resolve() for x in sys.argv[1:3])
results.mkdir(exist_ok=True)
base = 'http://127.0.0.1:18084/api'
svnbase = 'svn://127.0.0.1:13690'
report = {'source': 'c6973ecd36b19c313f4d9f8385c9d8e6e3ef85a2', 'cases': [], 'memory': {}}
password = secrets.token_hex(14)
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
temp = tempfile.TemporaryDirectory(prefix='svnadmin4-eval-')
root = Path(temp.name)
home = root / 'svn-home'
home.mkdir()
process = None
server_pid = None
sampler_stop = threading.Event()
samples = []
phase = 'startup'


def check(name, passed, evidence=None):
    item = {'name': name, 'passed': bool(passed), 'evidence': evidence}
    report['cases'].append(item)
    print(('PASS' if passed else 'FAIL') + ': ' + name, flush=True)


def api(path, data=None, token=None, raw=False):
    headers = {'Content-Type': 'application/json'}
    if token:
        headers['X-Token'] = token
    req = urllib.request.Request(base + path, headers=headers,
                                 data=json.dumps(data).encode() if data is not None else None)
    try:
        response = opener.open(req, timeout=20)
    except urllib.error.HTTPError as e:
        response = e
    with response:
        payload = response.read()
        return (response.status, payload) if raw else json.loads(payload)


def must(path, data=None, token=None):
    result = api(path, data, token)
    if not result.get('status'):
        raise RuntimeError(f'Fixture setup failed: {path}: {result.get("message")}')
    return result.get('data')


def login(name, role='svnuser', pwd=None):
    data = must('/common/login', {'userName': name, 'password': pwd or password, 'role': role})
    return data['token']


def cli(*args, user='writer', cwd=None):
    return subprocess.run(['svn', *map(str, args), '--non-interactive', '--no-auth-cache',
                           '--username', user, '--password', password,
                           '--config-dir', str(root / 'client-config')],
                          cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          timeout=45)


def grant(repo, user, perm, path='/', kind='user'):
    must('/pri/create', {'repName': repo, 'priPath': path, 'objectType': kind,
                        'objectName': user, 'perm': perm}, admin)


def family_pids():
    roots = {process.pid}
    if server_pid:
        roots.add(server_pid)
    parents = {}
    for p in Path('/proc').glob('[0-9]*/stat'):
        try:
            fields = p.read_text().rsplit(')', 1)[1].split()
            parents[int(p.parent.name)] = int(fields[1])
        except (OSError, ValueError, IndexError):
            pass
    while True:
        more = {pid for pid, parent in parents.items() if parent in roots}
        if more <= roots:
            return roots
        roots |= more


def memory_sample():
    totals = {'rss_kib': 0, 'pss_kib': 0, 'processes': 0}
    per_process = []
    for pid in family_pids():
        try:
            data = Path(f'/proc/{pid}/smaps_rollup').read_text()
            values = {line.split(':')[0]: int(line.split()[1])
                      for line in data.splitlines() if line.startswith(('Rss:', 'Pss:'))}
            totals['rss_kib'] += values.get('Rss', 0)
            totals['pss_kib'] += values.get('Pss', 0)
            totals['processes'] += 1
            per_process.append({'pid': pid, 'name': Path(f'/proc/{pid}/comm').read_text().strip(), **values})
        except (OSError, ValueError):
            pass
    return {'phase': phase, **totals, 'per_process': per_process}


def sample_loop():
    while not sampler_stop.is_set():
        samples.append(memory_sample())
        sampler_stop.wait(0.05)


try:
    # Payload measurement includes program, complete built UI, config and license.
    # No installer is made before the permission evaluation has passed.
    payload = root / 'payload'
    (payload / 'bin').mkdir(parents=True)
    shutil.copy2(subject / 'build/svnadmin4', payload / 'bin/svnadmin4')
    shutil.copytree(subject / 'web/dist', payload / 'web')
    shutil.copytree(subject / 'server/configs', payload / 'configs')
    for filename in ('LICENSE', 'NOTICE'):
        shutil.copy2(subject / filename, payload / filename)
    archive = root / 'measurement-only.tar.gz'
    with tarfile.open(archive, 'w:gz') as tar:
        tar.add(payload, arcname='svnadmin4')
    report['size'] = {
        'unstripped_binary_bytes': (subject / 'build/svnadmin4-unstripped').stat().st_size,
        'stripped_binary_bytes': (subject / 'build/svnadmin4').stat().st_size,
        'web_bytes': sum(p.stat().st_size for p in (payload / 'web').rglob('*') if p.is_file()),
        'payload_uncompressed_bytes': sum(p.stat().st_size for p in payload.rglob('*') if p.is_file()),
        'payload_gzip_bytes': archive.stat().st_size,
        'excludes': 'Subversion system packages, database/repository data and OS; no production installer exported',
    }
    configuration = {
        'server': {'host': '127.0.0.1', 'port': 18084, 'mode': 'release', 'token_expire': 7200},
        'database': {'driver': 'sqlite', 'sqlite_path': str(root / 'data/admin.db')},
        'svn': {'home_path': str(home), 'svnserve_host': '127.0.0.1', 'svnserve_port': 13690},
        'security': {'jwt_secret': secrets.token_hex(32), 'enable_verify_code': False},
        'update': {'enable': False},
    }
    config_file = root / 'config.json'
    config_file.write_text(json.dumps(configuration))
    log = (root / 'app.log').open('wb')
    process = subprocess.Popen([str(subject / 'build/svnadmin4'), '-c', str(config_file),
                                '-web', str(subject / 'web/dist')], cwd=root, stdout=log, stderr=log)
    for attempt in range(100):
        try:
            if api('/health').get('status'):
                break
        except (OSError, ValueError):
            pass
        if process.poll() is not None:
            raise RuntimeError('Application exited before health endpoint was ready')
        time.sleep(0.1)
    else:
        raise RuntimeError('Application startup timeout')
    admin = login('admin', 'admin', 'admin')
    must('/common/updatePass', {'oldPass': 'admin', 'newPass': password}, admin)
    admin = login('admin', 'admin')
    for name in ('writer', 'reader', 'outsider', 'delegate', 'receiver'):
        must('/user/create', {'svnUserName': name, 'svnUserPass': password}, admin)
    for repo in ('basic', 'grouped', 'secret', 'delegation'):
        must('/rep/create', {'repName': repo, 'initStruct': '01'}, admin)
    grant('basic', 'writer', 'rw')
    grant('basic', 'reader', 'r')
    grant('basic', 'reader', '', '/trunk/private')
    grant('secret', 'writer', 'rw')
    grant('delegation', 'delegate', 'rw')
    must('/group/create', {'svnGroupName': 'developers'}, admin)
    must('/group/updMember', {'svnGroupName': 'developers', 'users': ['writer']}, admin)
    grant('grouped', 'developers', 'rw', kind='group')
    must('/setting/svnserveStart', {}, admin)
    server_pid = int((home / 'svnserve.pid').read_text())
    phase = 'idle_empty'
    sampler = threading.Thread(target=sample_loop, daemon=True)
    sampler.start()
    time.sleep(12)

    check('unauthenticated_admin_endpoint_denied', not api('/user/list').get('status'))
    outsider = login('outsider')
    reader = login('reader')
    delegate = login('delegate')
    check('ordinary_user_admin_endpoint_denied', not api('/user/list', token=outsider).get('status'))
    check('svn_authorized_read', cli('ls', svnbase + '/basic', user='reader').returncode == 0)
    check('svn_unauthorized_read_denied', cli('ls', svnbase + '/basic', user='outsider').returncode != 0)
    check('svn_readonly_write_denied', cli('mkdir', svnbase + '/basic/reader-write', '-m', 'test', user='reader').returncode != 0)
    check('svn_writer_commit', cli('mkdir', svnbase + '/basic/trunk/private', '-m', 'test').returncode == 0)
    check('svn_child_read_deny', cli('ls', svnbase + '/basic/trunk/private', user='reader').returncode != 0)
    check('svn_group_write', cli('mkdir', svnbase + '/grouped/group-write', '-m', 'test').returncode == 0)
    check('svn_group_nonmember_denied', cli('ls', svnbase + '/grouped', user='reader').returncode != 0)

    # Simulate a modest Unity asset transfer, not a large-project load test.
    phase = 'active_small_project'
    wc = root / 'wc'
    if cli('checkout', svnbase + '/basic', wc).returncode != 0:
        raise RuntimeError('Fixture checkout failed')
    asset = wc / 'trunk' / '中文资源.bin'
    asset.write_bytes(os.urandom(16 * 1024 * 1024))
    assert cli('add', asset).returncode == 0
    check('svn_unicode_asset_commit', cli('commit', wc, '-m', 'Chinese path + 16 MiB asset').returncode == 0)
    assert cli('propset', 'svn:needs-lock', '*', asset).returncode == 0
    assert cli('commit', wc, '-m', 'needs-lock').returncode == 0
    check('svn_lock', cli('lock', asset, '-m', 'test lock').returncode == 0)
    check('svn_unlock', cli('unlock', asset).returncode == 0)
    deadline = time.monotonic() + 15
    def traffic(_):
        count = 0
        while time.monotonic() < deadline:
            must('/rep/list?page=1&pageSize=20', token=admin)
            must('/common/statistics', token=admin)
            count += 2
            time.sleep(0.1)
        return count
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        report['memory']['api_requests'] = sum(pool.map(traffic, range(4)))
    check('svn_asset_checkout', cli('checkout', svnbase + '/basic', root / 'wc2').returncode == 0)
    phase = 'idle_after_workload'
    time.sleep(12)

    # Backup download must obey repository and role restrictions, not only login.
    dump = home / 'backup' / 'secret_evaluation.dump'
    with dump.open('wb') as out:
        subprocess.run(['svnadmin', 'dump', str(home / 'rep/secret')], stdout=out,
                       stderr=subprocess.PIPE, check=True, timeout=30)
    status, body = api('/backup/download?name=' + dump.name, token=outsider, raw=True)
    check('backup_hidden_from_unauthorized_user', not body.startswith(b'SVN-fs-dump-format-version'),
          {'http_status': status, 'received_svn_dump': body.startswith(b'SVN-fs-dump-format-version')})

    # A writer has never received administrative delegation from an administrator.
    enabled = api('/secondpri/update', {'svnUserName': 'delegate', 'repName': 'delegation',
                                      'priPath': '/', 'enable': True}, delegate)
    allowed = api('/secondpri/objectCreate', {'svnUserName': 'delegate', 'repName': 'delegation',
                 'priPath': '/', 'objectType': 'user', 'objectName': 'receiver'}, delegate)
    changed = api('/pri/create', {'repName': 'delegation', 'priPath': '/', 'objectType': 'user',
                                 'objectName': 'receiver', 'perm': 'rw'}, delegate)
    receiver_access = cli('ls', svnbase + '/delegation', user='receiver').returncode == 0
    check('delegation_requires_admin_grant', not receiver_access,
          {'self_enable': enabled.get('status'), 'self_whitelist': allowed.get('status'),
           'grant_accepted': changed.get('status'), 'receiver_svn_access': receiver_access})

    # Disable must affect fresh SVN connections and existing web sessions.
    must('/user/updStatus', {'svnUserName': 'reader', 'svnUserStatus': 0}, admin)
    check('disabled_user_fresh_svn_denied', cli('ls', svnbase + '/basic', user='reader').returncode != 0)
    check('disabled_user_old_web_token_denied', not api('/common/userInfo', token=reader).get('status'))
    must('/subadmin/create', {'subadminName': 'limited', 'subadminPass': password,
                              'functions': ['rep/create']}, admin)
    limited = login('limited', 'subadmin')
    check('subadmin_ungranted_function_denied', not api('/user/list', token=limited).get('status'))
    check('subadmin_granted_function_allowed', api('/rep/create', {'repName': 'limited-before'}, limited).get('status'))
    sub = next(x for x in must('/subadmin/list', token=admin)['list'] if x['subadminName'] == 'limited')
    must(f'/subadmin/updStatus?subadminId={sub["subadminId"]}&status=0', {}, admin)
    after_disable = api('/rep/create', {'repName': 'limited-after-disabled'}, limited)
    check('disabled_subadmin_write_denied', not after_disable.get('status'),
          {'repository_created': (home / 'rep/limited-after-disabled').exists()})
    try:
        login('limited', 'subadmin')
        fresh_blocked = False
    except RuntimeError:
        fresh_blocked = True
    check('disabled_subadmin_fresh_login_denied', fresh_blocked)
    must('/user/updPass', {'svnUserName': 'outsider', 'svnUserPass': secrets.token_hex(16)}, admin)
    check('password_change_revokes_old_web_token', not api('/common/userInfo', token=outsider).get('status'))

    # Two case-distinct paths must remain distinct in the persisted ACL file.
    grant('basic', 'reader', 'r', '/Secret')
    grant('basic', 'reader', 'rw', '/secret')
    authz = (home / 'authz').read_text()
    check('case_distinct_acl_sections_preserved', '[basic:/Secret]' in authz and '[basic:/secret]' in authz)

    # Requests acknowledged as successful must not silently overwrite each other.
    def concurrent_grant(i):
        return api('/pri/create', {'repName': 'basic', 'priPath': '/', 'objectType': 'user',
                                  'objectName': f'parallel{i}', 'perm': 'r'}, admin).get('status')
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        accepted = list(pool.map(concurrent_grant, range(32)))
    persisted = (home / 'authz').read_text()
    retained = sum(f'parallel{i} = r' in persisted.splitlines() for i in range(32))
    check('concurrent_grants_not_lost', retained == sum(accepted),
          {'requests': 32, 'accepted': sum(accepted), 'persisted': retained})

    report['file_permissions'] = {name: oct((home / name).stat().st_mode & 0o777)
                                  for name in ('passwd', 'authz')}
    report['complete'] = True
except Exception as e:
    report['complete'] = False
    report['setup_or_runtime_error'] = f'{type(e).__name__}: {e}'
    print(report['setup_or_runtime_error'], flush=True)
finally:
    sampler_stop.set()
    if 'sampler' in globals():
        sampler.join(timeout=2)
    for label in ('idle_empty', 'active_small_project', 'idle_after_workload'):
        group = [s for s in samples if s['phase'] == label]
        if group:
            report['memory'][label] = {'samples': len(group),
                'rss_median_mib': statistics.median(s['rss_kib'] for s in group) / 1024,
                'rss_peak_mib': max(s['rss_kib'] for s in group) / 1024,
                'pss_median_mib': statistics.median(s['pss_kib'] for s in group) / 1024,
                'pss_peak_mib': max(s['pss_kib'] for s in group) / 1024,
                'representative': group[len(group)//2]['per_process']}
    report['memory']['method'] = '50ms /proc smaps_rollup samples; app + svnserve + descendants; excludes client, OS page cache, build tools; 4 repos and one 16 MiB random asset'
    report['summary'] = {'passed': sum(x['passed'] for x in report['cases']),
                         'failed': sum(not x['passed'] for x in report['cases'])}
    (results / 'runtime-report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    if server_pid:
        try:
            # The PID was read only from this newly-created private fixture.
            os.kill(server_pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    if process and process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
    temp.cleanup()
if not report.get('complete'):
    sys.exit(2)
