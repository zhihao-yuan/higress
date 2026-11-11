"""Compare old raw/JSONPath/OpenAI rule behavior across all disabled configs."""
from copy import deepcopy
import json

from runtime_lab import Lab, arguments, sha
from verify_disabled_large import stable_headers
from verify_runtime import configurations, request_for


def snapshot(lab, case):
    files = {}
    for suffix in ('body', 'upstream-request', 'upstream-response'):
        path = lab.cases / (case + '.' + suffix)
        if path.exists():
            files[suffix] = sha(path.read_bytes())
    files['stable-headers'] = sha(b'\n'.join(stable_headers(lab.cases / (case + '.headers'))))
    return files


def main():
    args = arguments(__doc__).parse_args()
    records, baseline = [], {}
    paths = ['$.messages[*].tool_calls[*].function.arguments']
    profiles = {
        'hash-restore': {'deny_openai': True, 'kind': 'hash', 'restore': True},
        'static-no-restore': {'deny_openai': True, 'kind': 'replace', 'restore': False},
        'jsonpath': {'deny_openai': False, 'deny_jsonpath': paths, 'kind': 'replace', 'restore': True},
        'combined': {'deny_openai': False, 'deny_jsonpath': paths, 'deny_raw': True, 'kind': 'hash', 'restore': True},
    }
    with Lab(args, 'legacy-rules') as lab:
        for variant in ('baseline', 'candidate-off', 'candidate-false', 'candidate-false-limits'):
            for name, profile in profiles.items():
                settings = deepcopy(configurations()[variant])
                settings.update({key: value for key, value in profile.items() if key not in ('kind', 'restore')})
                settings['replace_roles'][0].update(type=profile['kind'], restore=profile['restore'])
                gateway = lab.start(variant + '-' + name, settings,
                                    'baseline.wasm' if variant == 'baseline' else 'candidate.wasm')
                try:
                    for stream in (False, True):
                        for label in ('normal', 'deny-argument', 'deny-content'):
                            case = f'{variant}-{name}-{int(stream)}-{label}'
                            request = request_for('request-arguments', stream)
                            # A string content field enters the existing typed request path.
                            request['messages'][1]['content'] = 'DEMO_SECRET'
                            if label == 'deny-content':
                                request['messages'][0]['content'] = 'BLOCKED'
                            elif label == 'deny-argument':
                                request['messages'][1]['tool_calls'][0]['function']['arguments'] = '{"email":"BLOCKED"}'
                            row, _ = lab.request(gateway, case, request, scenario='request-arguments', delivery='events')
                            try:
                                assert row['curl_exit'] == 0 and row['status'] == '200', row
                                captured = snapshot(lab, case)
                                fingerprint = (row['request_sha256'], row['upstream_received'], captured)
                                key = (name, stream, label)
                                if variant == 'baseline':
                                    baseline[key] = fingerprint
                                else:
                                    assert fingerprint == baseline[key], 'Legacy output differs'
                                row.update(passed=True, comparison_hashes=captured)
                            except Exception as error:
                                row.update(passed=False, error=str(error))
                                raise
                            finally:
                                records.append(row)
                                lab.save('results.json', records)
                finally:
                    lab.stop(gateway)
                print(f'{variant}/{name} passed ({len(records)} cumulative)', flush=True)
        lab.save('summary.json', {'passed': len(records), 'failed': 0, 'model_requests': 0})


if __name__ == '__main__':
    main()
