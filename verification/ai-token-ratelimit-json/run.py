from pathlib import Path
from datetime import datetime, timezone
import argparse
import hashlib
import http.client
import json
import os
import re
import shutil
import socket
import subprocess
import time

BASE = 'c74d7e2ddf69c38687f61dfbc2d560a9ae838b26'
FIXED = '8f7276835290c926428733637db1cb856c97f673'
PLUGIN = Path('plugins/wasm-go/extensions/ai-token-ratelimit')
GATEWAY = 'higress-registry.cn-hangzhou.cr.aliyuncs.com/higress/gateway@sha256:a82de493902012ce6b555ecb2244156f3c73824474d67549144a7efa334d0299'
REDIS = 'public.ecr.aws/docker/library/redis@sha256:bb186d083732f669da90be8b0f975a37812b15e913465bb14d845db72a4e3e08'
PREFIX = 'higress-token-ratelimit:{ai-token-json-repro}:'
SHARED = PREFIX + 'limit_by_header:3600:x-shared-group:shared'
ROOT = Path(__file__).resolve().parent
parser = argparse.ArgumentParser()
parser.add_argument('--repo', required=True, type=Path, help='Public Higress checkout containing the fixed revision')
parser.add_argument('--go', default='go', help='Go 1.24.4 executable')
parser.add_argument('--output', type=Path, help='New output directory; existing evidence is never overwritten')
args = parser.parse_args()
repo = args.repo.resolve()
work = (args.output or ROOT / 'runs' / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')).resolve()
if work.exists():
    raise SystemExit('Output exists; choose a new --output directory.')
work.mkdir(parents=True)
project = 'higress-json-public-repro'
image = 'higress-json-public-fixture:local'
env = os.environ.copy()
env.pop('GH_TOKEN', None)
env.pop('GITHUB_TOKEN', None)
go = shutil.which(args.go)
if not go:
    raise SystemExit('Go executable unavailable.')
env['PATH'] = str(Path(go).parent) + os.pathsep + env['PATH']
env['GOTOOLCHAIN'] = 'local'


def command(argv, *, cwd=None, extra_env=None):
    actual = env.copy()
    actual.update(extra_env or {})
    return subprocess.check_output(argv, cwd=cwd, env=actual, text=True, stderr=subprocess.STDOUT).strip()


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def compose(*argv):
    return command(['docker', 'compose', '-p', project, '-f', str(work / 'compose.json'), *argv])


def redis(*argv):
    return compose('exec', '-T', 'redis', 'redis-cli', '--raw', *argv)


def request(port, case, key, matched=True):
    connection = http.client.HTTPConnection('127.0.0.1', port, timeout=30)
    headers = {'content-type': 'application/json', 'x-fixture-case': case,
               'x-observation-id': key}
    if matched:
        headers.update({'x-fixture-user': 'u-' + key, 'x-shared-group': 'shared'})
    connection.request('POST', '/v1/chat/completions',
        b'{"model":"fixture","stream":false,"messages":[{"role":"user","content":"hello"}]}', headers)
    response = connection.getresponse()
    body = response.read()
    status = response.status
    connection.close()
    if status != 200:
        raise RuntimeError('Unexpected HTTP status: ' + str(status))
    return body


for port in (18511, 18512, 19511):
    probe = socket.socket()
    try:
        probe.bind(('127.0.0.1', port))
    finally:
        probe.close()
if command(['docker', 'ps', '-aq', '--filter', 'label=com.docker.compose.project=' + project]):
    raise SystemExit('Dedicated project already exists; preserve it and inspect before rerunning.')
if command(['git', 'diff', '--name-only', FIXED, '--', str(PLUGIN)], cwd=repo):
    raise SystemExit('Plugin source differs from the pinned fixed revision.')
version = command([go, 'version'])
if 'go1.24.4 ' not in version:
    raise SystemExit('Use Go 1.24.4 for this evidence run: ' + version)
print('Building pinned public-source Wasm and the local fixture.', flush=True)
reference = work / 'reference'
names = command(['git', 'ls-tree', '-r', '--name-only', BASE, '--', str(PLUGIN)], cwd=repo).splitlines()
for name in names:
    relative = Path(name)
    if '..' in relative.parts or not name.startswith(str(PLUGIN) + '/'):
        raise RuntimeError('Unexpected source path')
    target = reference / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(subprocess.check_output(['git', 'show', BASE + ':' + name], cwd=repo, env=env))
(work / 'wasm').mkdir()
for role, module in [('base', reference / PLUGIN), ('fixed', repo / PLUGIN)]:
    command([go, 'build', '-buildvcs=false', '-buildmode=c-shared', '-o', 'main.wasm', '.'],
            cwd=module, extra_env={'GOOS': 'wasip1', 'GOARCH': 'wasm'})
    shutil.copyfile(module / 'main.wasm', work / 'wasm' / (role + '.wasm'))
fixture = work / 'fixture'
fixture.mkdir()
shutil.copyfile(ROOT / 'fixture/Dockerfile', fixture / 'Dockerfile')
command([go, 'build', '-o', str(fixture / 'fixture'), str(ROOT / 'fixture/main.go')],
        extra_env={'GOOS': 'linux', 'GOARCH': 'amd64', 'CGO_ENABLED': '0'})
services = {
    'redis': {'image': REDIS, 'command': ['redis-server', '--save', '', '--appendonly', 'no']},
    'fixture': {'build': {'context': str(fixture)}, 'image': image, 'platform': 'linux/amd64',
                'ports': ['127.0.0.1:19511:9090']}
}
for role, port in [('base', 18511), ('fixed', 18512)]:
    services[role] = {'image': GATEWAY, 'platform': 'linux/amd64', 'depends_on': ['redis', 'fixture'],
                     'entrypoint': ['envoy'], 'command': ['-c', '/etc/envoy/envoy.yaml', '--concurrency', '1', '-l', 'trace'],
                     'volumes': [str(work / 'wasm' / (role + '.wasm')) + ':/etc/envoy/wasm/plugin.wasm:ro',
                                 str(ROOT / 'envoy.yaml') + ':/etc/envoy/envoy.yaml:ro'],
                     'ports': ['127.0.0.1:' + str(port) + ':18080']}
(work / 'compose.json').write_text(json.dumps({'services': services}, indent=2) + '\n')
records = []
try:
    print(compose('up', '--build', '--pull', 'never', '-d'), flush=True)
    for role, port in [('base', 18511), ('fixed', 18512)]:
        deadline = time.monotonic() + 120
        while True:
            try:
                request(port, '', 'ready', matched=False)
                break
            except (OSError, RuntimeError, http.client.HTTPException):
                if time.monotonic() > deadline:
                    raise RuntimeError('Envoy did not become ready: ' + role)
                time.sleep(.25)
        # Verify Redis accounting readiness separately before measuring cases.
        for attempt in range(20):
            key = role + '-warm-' + str(attempt)
            request(port, '', key)
            time.sleep(.25)
            if redis('GET', PREFIX + 'limit_by_per_header:3600:x-fixture-user:u-' + key) == '25':
                break
        else:
            raise RuntimeError('Redis accounting did not become ready: ' + role)
        for case in ('usage-key', 'pretty-json', 'sse', 'large-json'):
            for repetition in range(1, 4):
                key = role + '-' + case + '-' + str(repetition)
                expected_body = request(19511, case, 'direct-' + key)
                before_log = compose('logs', '--no-color', role)
                before_shared = int(redis('GET', SHARED) or 0)
                body = request(port, case, key)
                expected = 50 if case == 'pretty-json' else 25
                expected_observation = expected
                if role == 'base':
                    expected_observation = {'usage-key': 0, 'pretty-json': 20, 'sse': 25, 'large-json': None}[case]
                user_key = PREFIX + 'limit_by_per_header:3600:x-fixture-user:u-' + key
                deadline = time.monotonic() + 5
                while True:
                    user = int(redis('GET', user_key) or 0)
                    shared_delta = int(redis('GET', SHARED) or 0) - before_shared
                    if (expected_observation is not None and user == expected_observation
                            and shared_delta == expected_observation) or time.monotonic() > deadline:
                        break
                    time.sleep(.05)
                time.sleep(.25)
                after_log = compose('logs', '--no-color', role)
                delta = after_log[len(before_log):] if after_log.startswith(before_log) else after_log
                callbacks = [line for line in delta.splitlines() if 'proxy_on_response_body(' in line]
                callback_values = []
                for line in callbacks:
                    match = re.search(r'proxy_on_response_body\((\d+),\s*(\d+),\s*(\d+)\)', line)
                    if match:
                        callback_values.append({'context_id': int(match[1]), 'body_bytes': int(match[2]),
                                                'end_of_stream': bool(int(match[3]))})
                result = {'variant': role, 'case': case, 'repetition': repetition, 'observation': key,
                          'http_status': 200, 'body_bytes': len(body), 'body_sha256': hashlib.sha256(body).hexdigest(),
                          'body_unchanged': body == expected_body, 'expected_tokens': expected,
                          'expected_baseline_observation': expected_observation if role == 'base' else None,
                          'user_tokens': user, 'shared_increment': shared_delta,
                          'callback_arguments': callback_values, 'callback_trace': callbacks}
                records.append(result)
                print(json.dumps({k: v for k, v in result.items() if k != 'callback_trace'}), flush=True)
                allowed_count = (user == shared_delta and 0 <= user <= expected) if expected_observation is None else (user == expected_observation and shared_delta == expected_observation)
                if body != expected_body or not allowed_count:
                    raise RuntimeError('Response or accounting mismatch: ' + key)
                if role == 'base' and case == 'usage-key':
                    positive = [event for event in callback_values if event['body_bytes'] > 0]
                    if (len(positive) < 2 or len({event['context_id'] for event in callback_values}) != 1
                            or sum(event['body_bytes'] for event in positive) != len(body)):
                        raise RuntimeError('Missing direct evidence of multiple baseline body callbacks: ' + key)
    summary = {'baseline_revision': BASE, 'fixed_revision': FIXED, 'go': version,
               'gateway_image': GATEWAY, 'redis_image': REDIS, 'envoy_workers': 1,
               'envoy_version': compose('exec', '-T', 'fixed', 'envoy', '--version'),
               'redis_version': compose('exec', '-T', 'redis', 'redis-server', '--version'),
               'fixed_main_go_sha256': sha(repo / PLUGIN / 'main.go'),
               'wasm_sha256': {role: sha(work / 'wasm' / (role + '.wasm')) for role in ('base', 'fixed')},
               'bootstrap_sha256': sha(ROOT / 'envoy.yaml'), 'new_model_calls': 0,
               'controlled_fixture': True, 'results': records}
    (work / 'report.json').write_text(json.dumps(summary, indent=2) + '\n')
    print('All 24 controlled Envoy/Redis cases passed: ' + str(work / 'report.json'), flush=True)
finally:
    for role in ('base', 'fixed', 'fixture'):
        try:
            (work / (role + '.log')).write_text(compose('logs', '--no-color', role) + '\n')
        except subprocess.CalledProcessError:
            pass
    print(compose('down', '--remove-orphans'), flush=True)
    subprocess.run(['docker', 'image', 'rm', image], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
