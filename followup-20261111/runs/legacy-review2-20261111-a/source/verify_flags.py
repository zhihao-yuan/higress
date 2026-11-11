"""Test the three flags independently on the fixed gateway with old OpenAI handling off."""
from copy import deepcopy
import json

from runtime_lab import Lab, arguments
from verify_runtime import BASE_CONFIG, parse, request_for


def response_spec(value):
    return {'content': 'public response MASKED_TOKEN', 'calls': [
        {'name': 'lookup', 'arguments': json.dumps({'email': value, 'other': 'MASKED_TOKEN'}, ensure_ascii=False)}]}


def request(value='DEMO_SECRET', description='public description'):
    return {
        'messages': [
            {'role': 'user', 'content': 'DEMO_SECRET'},
            {'role': 'assistant', 'content': None, 'tool_calls': [
                {'id': 'call-0', 'type': 'function', 'function': {
                    'name': 'lookup', 'arguments': json.dumps({'email': value}, ensure_ascii=False)}}]},
        ],
        'tools': [{'type': 'function', 'function': {'name': 'lookup', 'description': description}}],
    }


def main():
    parser = arguments(__doc__)
    parser.add_argument('--system-word-file', required=True)
    args = parser.parse_args()
    with open(args.system_word_file, encoding='utf-8') as words:
        system_word = next(word.strip() for word in words if len(word.strip()) > 1 and not word.strip().isascii())
    records = []
    with Lab(args, 'flag-matrix') as lab:
        for deny_name, custom, system in [('none', False, False), ('custom', True, False),
                                          ('system', False, True), ('both', True, True)]:
            active_words = (['BLOCKED'] if custom else []) + ([system_word] if system else [])
            # Probe both sources, even if disabled. Keeping the requests fixed
            # isolates whether a dictionary source was actually enabled.
            words = [('custom', 'BLOCKED'), ('system', system_word)]
            for flag in range(8):
                check, restore, definitions = (bool(flag & bit) for bit in (1, 2, 4))
                settings = deepcopy(BASE_CONFIG)
                settings.update(deny_openai=False, deny_words=['BLOCKED'] if custom else [], system_deny=system,
                    tool_arguments={'check': check, 'restore': restore,
                                    'restore_allowlist': [{'tool': 'lookup', 'paths': ['/email']}]},
                    tool_definitions={'check': definitions})
                name = f'{deny_name}-{flag}'
                gateway = lab.start(name, settings)
                try:
                    for stream in (True, False):
                        cases = [('mask-restore', request(), response_spec('MASKED_TOKEN'), False, False)]
                        for source, word in words:
                            cases.extend([
                                (source + '-definition', request(description=word), response_spec('MASKED_TOKEN'),
                                 definitions and word in active_words, False),
                                (source + '-request', request(value=word), response_spec('MASKED_TOKEN'),
                                 check and word in active_words, False),
                                (source + '-response', request(), response_spec(word), False,
                                 check and word in active_words),
                            ])
                        for label, body_in, spec, request_denied, response_denied in cases:
                            body_in['stream'] = stream
                            case = f'{name}-{int(stream)}-{label}'
                            lab.save('cases/' + case + '.fixture.json', spec)
                            row, body = lab.request(gateway, case, body_in, delivery='events')
                            row.update(request_denied=request_denied, response_denied=response_denied)
                            try:
                                assert row['curl_exit'] == 0 and row['status'] == '200', row
                                assert row['upstream_received'] != request_denied, 'Unexpected upstream access'
                                if request_denied or response_denied and not stream:
                                    assert '已被屏蔽' in body.decode(), 'Missing refusal body'
                                elif response_denied:
                                    actual = parse(body, stream)
                                    assert not actual['arguments'] and actual['done'] == 0, 'Denied response leaked arguments'
                                else:
                                    upstream = json.loads((lab.cases / (case + '.upstream-request')).read_bytes())
                                    assert upstream['messages'][0]['content'] == 'DEMO_SECRET', 'Legacy OpenAI handling activated'
                                    assert upstream['tools'] == body_in['tools'], 'Definition modified'
                                    original = json.loads(body_in['messages'][1]['tool_calls'][0]['function']['arguments'])
                                    written = json.loads(upstream['messages'][1]['tool_calls'][0]['function']['arguments'])
                                    expected_input = 'MASKED_TOKEN' if check and original['email'] == 'DEMO_SECRET' else original['email']
                                    assert written == {'email': expected_input}, 'Request scope changed'
                                    actual = parse(body, stream)
                                    expected = json.loads(spec['calls'][0]['arguments'])
                                    if check and restore and expected_input == 'MASKED_TOKEN' and expected['email'] == 'MASKED_TOKEN':
                                        expected['email'] = 'DEMO_SECRET'
                                    assert [json.loads(value) for value in actual['arguments'].values()] == [expected], 'Response scope changed'
                                    assert actual['text'] == {('0', 'content'): 'public response MASKED_TOKEN'}, 'Tool map leaked into content'
                                    assert actual['done'] == int(stream) and actual['finish'] == [(0, 'tool_calls')], 'Termination changed'
                                    assert actual['usage'] == [{'total_tokens': 20}], 'Usage changed'
                                row['passed'] = True
                            except Exception as error:
                                row.update(passed=False, error=str(error))
                                raise
                            finally:
                                records.append(row)
                                lab.save('results.json', records)
                finally:
                    lab.stop(gateway)
                print(f'{name} passed ({len(records)} cumulative)', flush=True)
        lab.save('summary.json', {'passed': len(records), 'failed': 0, 'model_requests': 0})


if __name__ == '__main__':
    main()
