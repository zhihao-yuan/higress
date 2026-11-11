# Copyright (c) 2026 Alibaba Group Holding Ltd.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Gateway limits and scope checks. All data and upstream responses are synthetic."""
import gzip
import json
from copy import deepcopy

from runtime_lab import Lab, arguments, sha
from verify_runtime import BASE_CONFIG, parse, request_for


def argument_of_size(size, key='x', value='x'):
    prefix, suffix = '{"' + key + '":"', '"}'
    assert size >= len(prefix + suffix)
    argument = prefix + value * (size - len(prefix + suffix)) + suffix
    assert len(argument.encode()) == size
    return argument


def config(limits, restore=False):
    value = deepcopy(BASE_CONFIG)
    limits = {'max_unparsed_bytes': 65536, **limits}
    value['tool_arguments'] = {'check': not restore, 'restore': restore, 'limits': limits}
    if restore:
        value['tool_arguments']['restore_allowlist'] = [{'tool': 'lookup', 'paths': ['/email']}]
    return value


def spec_for(arguments, **options):
    return {'calls': [{'name': 'lookup', 'id': 'call-0', 'index': 0, 'arguments': arguments}], **options}


def keymap(spec, replacements=None):
    values = {}
    for ordinal, call in enumerate(spec.get('calls', [])):
        if not isinstance(call.get('arguments'), str):
            continue
        key = (str(call.get('choice', 0)), 'legacy' if call.get('legacy') else 'modern', '0' if call.get('legacy') else str(call.get('index', ordinal)))
        values[key] = replacements.get(ordinal, call['arguments']) if replacements else call['arguments']
    return values


def compress_case(lab, case):
    for suffix in ('request', 'fixture.json', 'body', 'upstream-request', 'upstream-response'):
        path = lab.cases / (case + '.' + suffix)
        if path.exists() and path.stat().st_size > 262144:
            with path.open('rb') as source, gzip.open(str(path) + '.gz', 'wb') as destination:
                while chunk := source.read(1048576):
                    destination.write(chunk)
            path.unlink()


def main():
    parser = arguments(__doc__)
    parser.add_argument('--smoke', action='store_true')
    args = parser.parse_args()
    records = []
    with Lab(args, 'limits') as lab:
        def group(name, settings, cases, module='candidate.wasm'):
            gateway = lab.start(name, settings, module)
            try:
                for case_number, case_data in enumerate(cases):
                    request = case_data.get('request', request_for('normal', True))
                    specification = case_data.get('spec', spec_for('{}'))
                    expected = case_data.get('expected', 'pass')
                    for stream in case_data.get('streams', (True, False)):
                        request = {**request, 'stream': stream}
                        for delivery in (('single',) if args.smoke else ('single', 'events', 'fragment17', 'prefix1')):
                            for repeat in range(1 if args.smoke else 2):
                                case = f'{name}-{case_number}-{int(stream)}-{delivery}-{repeat}'
                                (lab.cases / (case + '.fixture.json')).write_text(json.dumps(specification, ensure_ascii=False) + '\n')
                                row, body = lab.request(gateway, case, request, delivery=delivery)
                                row.update(expected=expected, stream=stream, repeat=repeat)
                                try:
                                    assert row['curl_exit'] == 0 and row['status'] == '200', row
                                    if expected == 'request-denied':
                                        assert not row['upstream_received'], 'invalid request reached upstream'
                                        assert '已被屏蔽' in body.decode(), 'missing refusal body'
                                    elif expected == 'response-denied':
                                        assert row['upstream_received']
                                        if stream:
                                            actual = parse(body, True)
                                            assert not actual['arguments'] and actual['done'] == 0, 'denied stream leaked parameters/termination'
                                        else:
                                            assert '已被屏蔽' in body.decode()
                                    else:
                                        assert row['upstream_received']
                                        actual = parse(body, stream)
                                        upstream_wire = (lab.cases / (case + '.upstream-response')).read_bytes()
                                        original = parse(upstream_wire, stream)
                                        expected_args = case_data.get('expected_arguments', keymap(specification))
                                        assert actual['arguments'] == expected_args, 'arguments changed or missing'
                                        assert actual['names'] == original['names'], 'tool metadata changed'
                                        assert actual['usage'] == original['usage']
                                        assert actual['finish'] == original['finish'] and actual['done'] == original['done']
                                        assert actual['text'] == {('0', 'content'): case_data.get('expected_text', 'checking DEMO_SECRET')}, 'content scope changed'
                                        upstream = json.loads((lab.cases / (case + '.upstream-request')).read_bytes())
                                        if case_data.get('legacy_content_masked'):
                                            assert upstream['messages'][0]['content'] == 'MASKED_TOKEN', 'legacy text was not masked'
                                        if 'request_argument' in case_data:
                                            value = upstream['messages'][1]['tool_calls'][0]['function']['arguments']
                                            assert value == case_data['request_argument'], 'request argument result differs'
                                        if case_data.get('history'):
                                            assert len(request['messages'][1]['tool_calls']) > 128
                                            assert len(json.dumps(request).encode()) > 4194304
                                            for call in upstream['messages'][1]['tool_calls']:
                                                assert json.loads(call['function']['arguments'])['email'] == 'MASKED_TOKEN'
                                        row['arguments_sha256'] = {':'.join(key): sha(value.encode()) for key, value in actual['arguments'].items()}
                                    row['passed'] = True
                                except Exception as error:
                                    row.update(passed=False, error=str(error))
                                    records.append(row)
                                    lab.save('results.json', records)
                                    raise AssertionError(case + ': ' + str(error)) from error
                                records.append(row)
                                lab.save('results.json', records)
                                compress_case(lab, case)
            finally:
                lab.stop(gateway)
            print(json.dumps({'group': name, 'passed': len(records)}), flush=True)


        boundary = 1048576
        settings = config({})
        settings['tool_arguments']['limits'] = {}
        cases = [{'spec': spec_for(argument_of_size(size)),
                  'expected': 'pass' if size <= boundary else 'response-denied'}
                 for size in (boundary - 1, boundary, boundary + 1)]
        group('default-input', settings, cases)
        cases = []
        for size in (boundary - 1, boundary, boundary + 1):
            request = request_for('request-arguments', True)
            request['messages'][1]['tool_calls'][0]['function']['arguments'] = argument_of_size(size)
            cases.append({'request': request, 'spec': {'calls': []},
                          'expected': 'pass' if size <= boundary else 'request-denied',
                          'expected_text': 'checking DEMO_SECRET', 'legacy_content_masked': True})
        group('default-request-input', settings, cases)
        for size in (boundary - 1, boundary, boundary + 1):
            settings = config({}, restore=True)
            settings['tool_arguments']['limits'] = {}
            settings['replace_roles'] = [{'regex': 'O+', 'type': 'replace', 'value': 'MASK', 'restore': True}]
            request = request_for('normal', True)
            request['messages'][0]['content'] = 'O' * (size - 12)
            changed = '{"email":"' + 'O' * (size - 12) + '"}'
            assert len(changed.encode()) == size
            group('default-restored-output-' + str(size), settings,
                  [{'request': request, 'spec': spec_for('{"email":"MASK"}', content='public status'),
                    'expected': 'pass' if size <= boundary else 'response-denied',
                    'expected_arguments': {('0', 'modern', '0'): changed}, 'expected_text': 'public status'}])
        settings = config({})
        settings['tool_arguments']['limits'] = {}
        for delta in (-1, 0, 1):
            sizes = [boundary] * 3 + [boundary - 48 + delta]
            calls = [{'name': 'lookup', 'id': 'call-' + str(i), 'index': i,
                      'arguments': argument_of_size(size)} for i, size in enumerate(sizes)]
            assert sum(len(c['name']) + len(c['id']) + len(c['arguments']) for c in calls) == 4194304 + delta
            group('default-total-' + str(4194304 + delta), settings,
                  [{'spec': {'calls': calls}, 'expected': 'pass' if delta <= 0 else 'response-denied'}])
        lab.save('summary.json', {'passed': len(records), 'failed': 0, 'models': 0,
                 'defaults': {'max_call_bytes': 1048576, 'max_buffer_bytes': 4194304, 'max_calls': 128},
                 'sizes_are_decoded_utf8_bytes': True, 'restore_does_not_shorten_the_equal_boundary': True})


if __name__ == '__main__':
    main()
