"""Request rewrite boundaries and causal response budget release."""
import http.client
import json

from runtime_lab import Lab, arguments, sha
from verify_limits import argument_of_size, config, keymap
from verify_runtime import parse, request_for


def main():
    args = arguments(__doc__).parse_args()
    records = []
    with Lab(args, 'limit-followup') as lab:
        for size in (63, 64, 65):
            settings = config({'max_call_bytes': 64, 'max_buffer_bytes': 10000, 'max_calls': 10})
            settings['replace_roles'] = [{'regex': 'Z', 'type': 'replace', 'value': 'x' * (size - 8)}]
            gateway = lab.start(f'output-{size}', settings)
            try:
                for stream in (True, False):
                    case = f'request-output-{size}-{int(stream)}'
                    request = request_for('request-arguments', stream)
                    request['messages'][1]['tool_calls'][0]['function']['arguments'] = '{"x":"Z"}'
                    row, body = lab.request(gateway, case, request, scenario='request-arguments', delivery='events')
                    assert row['curl_exit'] == 0 and row['status'] == '200', row
                    if size <= 64:
                        assert row['upstream_received']
                        observed = json.loads((lab.cases / (case + '.upstream-request')).read_bytes())
                        argument = observed['messages'][1]['tool_calls'][0]['function']['arguments']
                        assert argument == argument_of_size(size), 'Expanded request argument differs'
                    else:
                        assert not row['upstream_received'] and '已被屏蔽' in body.decode()
                    records.append({**row, 'passed': True, 'target_bytes': size})
                    lab.save('results.json', records)
            finally:
                lab.stop(gateway)
        settings = config({'max_call_bytes': 64, 'max_buffer_bytes': 80, 'max_calls': 2})
        gateway = lab.start('release', settings)
        try:
            case = 'release-after-client-sees-first-finish'
            spec = {'calls': [{'name': 'lookup', 'id': f'call-{index}', 'index': 0, 'choice': index,
                               'arguments': argument_of_size(64)} for index in range(2)],
                    'finish_each': True, 'gate_calls': True}
            lab.save('cases/' + case + '.fixture.json', spec)
            request = json.dumps(request_for('normal', True)).encode()
            (lab.cases / (case + '.request')).write_bytes(request)
            connection = http.client.HTTPConnection('127.0.0.1', gateway.port, timeout=25)
            received = bytearray()
            gate = lab.cases / (case + '.ack0')
            try:
                connection.request('POST', '/v1/chat/completions', request,
                                   {'Content-Type': 'application/json', 'X-Test-Case': case})
                response = connection.getresponse()
                assert response.status == 200
                while part := response.read1(16384):
                    received.extend(part)
                    if not gate.exists() and parse(bytes(received), True)['finish'] == [(0, 'tool_calls')]:
                        first = parse(bytes(received), True)['arguments']
                        assert first == {('0', 'modern', '0'): argument_of_size(64)}
                        gate.write_text('First argument and first finish observed by client.\n')
            finally:
                connection.close()
                (lab.cases / (case + '.body')).write_bytes(received)
            actual = parse(bytes(received), True)
            assert gate.exists(), 'No first finish before upstream gate timeout'
            assert actual['arguments'] == keymap(spec)
            assert actual['finish'] == [(0, 'tool_calls'), (1, 'tool_calls')] and actual['done'] == 1
            records.append({'case': case, 'status': 200, 'passed': True, 'request_sha256': sha(request),
                            'body_sha256': sha(received), 'causal_gate_acknowledged': True})
            lab.save('results.json', records)
        finally:
            lab.stop(gateway)
        lab.save('summary.json', {'passed': len(records), 'failed': 0, 'model_requests': 0})


if __name__ == '__main__':
    main()
