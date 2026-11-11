"""Compare large requests and tool responses with the three new flags off."""
from copy import deepcopy
import json

from runtime_lab import Lab, arguments, sha
from verify_limits import argument_of_size, compress_case, keymap
from verify_runtime import configurations, parse, request_for


def stable_headers(path):
    ignored = {b'date', b'x-envoy-upstream-service-time', b'x-request-id',
               b'req-cost-time', b'req-arrive-time', b'resp-start-time'}
    return sorted(line for line in path.read_bytes().splitlines()
                  if line and line.split(b':', 1)[0].lower() not in ignored)


def main():
    args = arguments(__doc__).parse_args()
    payloads = {
        'single-oversize': [argument_of_size(1048577)],
        'total-and-count-oversize': [argument_of_size(35000)] * 129,
        'malformed-legacy': ['{"email":"MASKED_TOKEN"'],
    }
    records = []
    expected = {}
    with Lab(args, 'disabled-large') as lab:
        for variant in ('baseline', 'candidate-off', 'candidate-false', 'candidate-false-limits'):
            for rule_set in ('openai', 'deny-openai-off', 'raw'):
                settings = deepcopy(configurations()[variant])
                if rule_set == 'deny-openai-off':
                    settings['deny_openai'] = False
                if rule_set == 'raw':
                    settings.update(deny_openai=False, deny_raw=True, system_deny=True)
                gateway = lab.start(variant + '-' + rule_set, settings,
                                    'baseline.wasm' if variant == 'baseline' else 'candidate.wasm')
                try:
                    for label, payload in payloads.items():
                        legacy = label == 'malformed-legacy'
                        if rule_set != 'openai' and not legacy:
                            continue
                        calls = [{'name': 'lookup', 'id': f'call-{index}', 'index': index,
                                  'legacy': legacy, 'arguments': item}
                                 for index, item in enumerate(payload)]
                        spec = {'calls': calls, 'fragment_size': 32768, 'content': 'ordinary response'}
                        for stream, delivery in ((False, 'single'), (True, 'events')):
                            for repeat in range(2):
                                name = f'{label}-{int(stream)}-{delivery}-{repeat}'
                                case = f'{variant}-{rule_set}-{name}'
                                request = request_for('normal', stream)
                                function_calls = [{'id': call['id'], 'type': 'function',
                                                   'function': {'name': call['name'], 'arguments': call['arguments']}}
                                                  for call in calls]
                                history = {'role': 'assistant', 'content': None}
                                if legacy:
                                    history['function_call'] = function_calls[0]['function']
                                else:
                                    history['tool_calls'] = function_calls
                                request['messages'].append(history)
                                lab.save('cases/' + case + '.fixture.json', spec)
                                row, body = lab.request(gateway, case, request, delivery=delivery)
                                try:
                                    assert row['curl_exit'] == 0 and row['status'] == '200', row
                                    assert row['upstream_received'], 'Request did not reach fixture'
                                    upstream = lab.cases / (case + '.upstream-request')
                                    sent = lab.cases / (case + '.upstream-response')
                                    headers = lab.cases / (case + '.headers')
                                    row.update(upstream_request_sha256=sha(upstream.read_bytes()),
                                               upstream_response_sha256=sha(sent.read_bytes()),
                                               stable_headers_sha256=sha(b'\n'.join(stable_headers(headers))))
                                    actual = parse(body, stream)
                                    assert len(actual['arguments']) == len(payload), 'Arguments missing'
                                    if rule_set != 'raw':
                                        assert list(actual['arguments'].values()) == list(keymap(spec).values()), 'Arguments changed'
                                    # Raw replacement is a legacy rule. Its actual baseline
                                    # output, including any replacement, is the reference.
                                    assert actual['finish'] == [(0, 'tool_calls')], 'Finish changed'
                                    assert actual['done'] == int(stream), 'DONE changed'
                                    assert actual['usage'] == [{'total_tokens': 20}], 'Usage changed'
                                    fingerprint = tuple(row[field] for field in (
                                        'request_sha256', 'upstream_request_sha256', 'upstream_response_sha256',
                                        'body_sha256', 'stable_headers_sha256'))
                                    key = (rule_set, name)
                                    if variant == 'baseline':
                                        expected[key] = fingerprint
                                    else:
                                        assert fingerprint == expected[key], 'Candidate differs from baseline'
                                    row['passed'] = True
                                except Exception as error:
                                    row.update(passed=False, error=str(error))
                                    raise
                                finally:
                                    records.append(row)
                                    lab.save('results.json', records)
                                    compress_case(lab, case)
                    print(f'{variant}/{rule_set} passed ({len(records)} cumulative)', flush=True)
                finally:
                    lab.stop(gateway)
        lab.save('summary.json', {'passed': len(records), 'failed': 0, 'model_requests': 0})


if __name__ == '__main__':
    main()
