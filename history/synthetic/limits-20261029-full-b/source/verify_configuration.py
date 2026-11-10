"""Observe static failures and ECDS good -> bad -> good configuration updates."""
import json
import time
from copy import deepcopy

from runtime_lab import Lab, arguments
from verify_runtime import envoy_config, request_for

TYPE = 'type.googleapis.com/envoy.extensions.filters.http.wasm.v3.Wasm'
RESOURCE = 'type.googleapis.com/envoy.config.core.v3.TypedExtensionConfig'
NAME = 'masking-dynamic'
GOOD = {'deny_openai': False, 'deny_words': ['BLOCKED'], 'tool_arguments': {'check': True}}


def discovery(lab, version, settings):
    wasm = envoy_config(lab.network, 'candidate.wasm', settings)['static_resources']['listeners'][0]['filter_chains'][0]['filters'][0]['typed_config']['http_filters'][0]['typed_config']
    wasm['config'].pop('fail_open', None)
    wasm['config']['failure_policy'] = 'FAIL_CLOSED'
    wasm['config']['vm_config']['vm_id'] = 'configuration-probe'
    return {'version_info': version, 'type_url': RESOURCE, 'resources': [{'@type': RESOURCE, 'name': NAME, 'typed_config': wasm}]}


def write_update(lab, version, settings, gateway=None):
    value = discovery(lab, version, settings)
    lab.save('update-' + version + '.json', value)
    temporary = lab.output / 'extension.next'
    temporary.write_text(json.dumps(value, indent=2) + '\n')
    temporary.replace(lab.output / 'extension.json')
    if gateway:
        lab.command(['docker', 'exec', gateway.container, '/bin/sh', '-c',
            'cp "$1" /tmp/extension.next && mv /tmp/extension.next /tmp/extension.json',
            'update', '/lab/update-' + version + '.json'])


def admin(lab, gateway, endpoint):
    return lab.command(['docker', 'exec', gateway.container, 'curl', '-sf', 'http://127.0.0.1:15000/' + endpoint]).stdout


def versions(dump):
    value = json.loads(dump)
    return [entry['version_info'] for configuration in value.get('configs', []) for entry in configuration.get('ecds_filters', [])]


def blocked_request(word):
    return {'model': 'public-fixture', 'stream': False, 'messages': [{'role': 'assistant', 'content': None, 'tool_calls': [{'id': 'request-call', 'type': 'function', 'function': {'name': 'lookup', 'arguments': json.dumps({'email': word})}}]}]}


def assert_blocked(lab, gateway, case, word):
    row, body = lab.request(gateway, case, blocked_request(word))
    assert row['curl_exit'] == 0 and row['status'] == '200', row
    assert not row['upstream_received'], row
    assert '已被屏蔽' in body.decode(), body
    return row


def main():
    args = arguments(__doc__).parse_args()
    results = []
    with Lab(args, 'configuration') as lab:
        bad = {**GOOD, 'tool_arguments': {'check': True, 'restore': True}}
        write_update(lab, 'good-1', GOOD)

        def dynamic(config):
            config['node'] = {'id': 'public-fixture', 'cluster': 'public-fixture'}
            manager = config['static_resources']['listeners'][0]['filter_chains'][0]['filters'][0]['typed_config']
            manager['http_filters'][0] = {'name': NAME, 'config_discovery': {'config_source': {'path_config_source': {'path': '/tmp/extension.json'}, 'resource_api_version': 'V3'}, 'type_urls': [TYPE]}}

        gateway = lab.start('dynamic', GOOD, modify=dynamic, initial_discovery=True)
        dump = admin(lab, gateway, 'config_dump')
        (lab.output / 'before.config-dump.json').write_text(dump)
        assert versions(dump) == ['good-1'], versions(dump)
        results.append(assert_blocked(lab, gateway, 'before-bad', 'BLOCKED'))
        write_update(lab, 'bad-2', bad, gateway)
        rejected = False
        for _ in range(100):
            stats = admin(lab, gateway, 'stats?filter=extension_config_discovery')
            if any((name in line and line.rsplit(': ', 1)[-1] not in ('0', '')) for line in stats.splitlines() for name in ('update_rejected', 'config_fail')):
                rejected = True
                break
            time.sleep(.1)
        (lab.output / 'after-bad.ecds-stats').write_text(stats)
        dump = admin(lab, gateway, 'config_dump')
        (lab.output / 'after-bad.config-dump.json').write_text(dump)
        assert rejected, 'bad update was not observed as rejected'
        assert versions(dump) == ['good-1'], versions(dump)
        results.append(assert_blocked(lab, gateway, 'after-bad', 'BLOCKED'))
        next_good = {**GOOD, 'deny_words': ['FORBIDDEN']}
        write_update(lab, 'good-3', next_good, gateway)
        for _ in range(100):
            dump = admin(lab, gateway, 'config_dump')
            if versions(dump) == ['good-3']:
                break
            time.sleep(.1)
        (lab.output / 'after-good.config-dump.json').write_text(dump)
        assert versions(dump) == ['good-3']
        row, body = lab.request(gateway, 'new-good-allows-previous-word', blocked_request('BLOCKED'))
        assert row['curl_exit'] == 0 and row['status'] == '200' and row['upstream_received'], row
        results.append(row)
        results.append(assert_blocked(lab, gateway, 'new-good-blocks-new-word', 'FORBIDDEN'))
        lab.stop(gateway)
        invalid = {
            'missing-allowlist': bad,
            'bad-pointer': {**GOOD, 'tool_arguments': {'check': True, 'restore': True, 'restore_allowlist': [{'tool': 'lookup', 'paths': ['/bad~2path']}]}},
            'bad-limit': {**GOOD, 'tool_arguments': {'check': True, 'limits': {'max_call_bytes': 0}}},
            'bad-global-valid-rule': {**bad, '_rules_': [{'_match_route_': ['fixture'], 'tool_arguments': {'check': True}}]},
            'bad-rule': {**GOOD, '_rules_': [{'_match_route_': ['fixture'], 'tool_arguments': {'restore': True}}]},
        }
        for name, settings in invalid.items():
            gateway = lab.start('static-' + name, settings, ready=False)
            for _ in range(100):
                state = json.loads(lab.command(['docker', 'inspect', '--format', '{{json .State}}', gateway.container]).stdout)
                if not state['Running']:
                    break
                time.sleep(.1)
            logs = lab.command(['docker', 'logs', gateway.container], check=False)
            text = logs.stdout + logs.stderr
            assert 'invalid global tool configuration' in text or 'invalid per-rule tool configuration' in text, text
            if state['Running']:
                port = int(lab.command(['docker', 'port', gateway.container, '10000/tcp']).stdout.strip().rsplit(':', 1)[1])
                gateway.port = port
                lab.ports.append(port)
                row, _ = lab.request(gateway, name + '-closed', request_for('normal', False))
                assert row['status'] == '503' and not row['upstream_received'], row
                results.append({**row, 'host_behavior': 'running but FAIL_CLOSED'})
            else:
                assert state['ExitCode'] != 0, state
                results.append({'case': name, 'host_behavior': 'startup rejected', 'exit_code': state['ExitCode']})
            lab.stop(gateway)
        lab.save('results.json', results)
        lab.save('summary.json', {'dynamic_bad_update_rejected': rejected, 'last_good_retained': True, 'new_good_applied': True, 'static_bad_cases': len(invalid), 'models': 0, 'full_t5_complete': False})


if __name__ == '__main__':
    main()
