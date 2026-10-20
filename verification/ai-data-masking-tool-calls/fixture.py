"""Public, synthetic OpenAI-compatible upstream. No model or credentials."""
import json
import pathlib
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = pathlib.Path('/evidence')


def response_parts(request, scenario):
    text = request['messages'][0]['content']
    calls = [
        {'index': 0, 'id': 'call_public_read', 'type': 'function',
         'function': {'name': 'read', 'arguments': '{"path":"README.md"}'}},
        {'index': 1, 'id': 'call_public_search', 'type': 'function',
         'function': {'name': 'search', 'arguments': '{"query":"demo"}'}},
    ]
    if scenario == 'long_tools':
        calls[0]['id'] = 'call_public_write'
        calls[0]['function'] = {'name': 'write', 'arguments': json.dumps({
            'path': 'demo-report.md', 'content': 'synthetic public report detail abc xyz\n' * 300})}
    if scenario == 'mixed_tools':
        calls[0]['function']['arguments'] = '{"path":"MASKED_TOKEN"}'
    if not request['stream']:

        return [json.dumps({'id': 'public-fixture', 'object': 'chat.completion',
                           'choices': [{'index': 0, 'message': {
                               'role': 'assistant', 'content': '',
                               'tool_calls': [{k: v for k, v in calls[0].items() if k != 'index'}]},
                               'finish_reason': 'tool_calls'}],
                           'usage': {'prompt_tokens': 12, 'completion_tokens': 8, 'total_tokens': 20}})]
    chunks = []

    def emit(delta, finish=None):
        chunks.append('data: ' + json.dumps({
            'id': 'public-fixture', 'object': 'chat.completion.chunk',
            'choices': [{'index': 0, 'delta': delta, 'finish_reason': finish}]}) + '\n\n')

    if scenario == 'error':
        return ['data: ' + json.dumps({'error': {'message': 'synthetic upstream failure', 'type': 'server_error'}}) + '\n\n']
    if scenario == 'unterminated_text':
        emit({'content': 'checking ' + text})
        return [chunks[0].rstrip('\n')]

    emit({'role': 'assistant', 'content': ''})
    if scenario == 'mixed_tools':
        content = 'checking ' + text
        split = content.index('MASKED_TOKEN') + 3 if 'MASKED_TOKEN' in content else len(content) // 2
        emit({'content': content[:split]})
        emit({'content': content[split:], 'tool_calls': [{**calls[0], 'function': {'name': 'read'}}]})
    if scenario in ['text_then_tools', 'plain_text']:
        content = 'checking ' + text
        for offset in range(0, len(content), 3):
            emit({'content': content[offset:offset + 3]})
    if scenario != 'plain_text':
        if scenario != 'mixed_tools':
            for call in calls[:2 if scenario == 'two_tools' else 1]:
                emit({'tool_calls': [{**call, 'function': {'name': call['function']['name']}}]})
        fragment_size = 512 if scenario == 'long_tools' else 7
        max_length = max(len(call['function']['arguments']) for call in calls)
        for position in range(0, max_length, fragment_size):
            for call in calls[:2 if scenario == 'two_tools' else 1]:
                fragment = call['function']['arguments'][position:position + fragment_size]
                if fragment:
                    emit({'tool_calls': [{'index': call['index'], 'function': {'arguments': fragment}}]})
    emit({}, 'stop' if scenario == 'plain_text' else 'tool_calls')
    if scenario == 'terminal_null':
        event = json.loads(chunks[-1][5:])
        event['choices'][0]['delta'] = None
        chunks[-1] = 'data: ' + json.dumps(event) + '\n\n'
    if scenario == 'terminal_missing':
        event = json.loads(chunks[-1][5:])
        del event['choices'][0]['delta']
        chunks[-1] = 'data: ' + json.dumps(event) + '\n\n'
    chunks.append('data: ' + json.dumps({'id': 'public-fixture', 'choices': [], 'usage': {
        'prompt_tokens': 12, 'completion_tokens': 8, 'total_tokens': 20}}) + '\n\n')
    chunks.append('data: [DONE]\n\n')
    return chunks


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, *args):
        pass

    def do_POST(self):
        if self.headers.get('Transfer-Encoding', '').lower() == 'chunked':
            body = b''
            while True:
                size = int(self.rfile.readline().split(b';')[0], 16)
                if not size:
                    self.rfile.readline()
                    break
                body += self.rfile.read(size)
                self.rfile.read(2)
        else:
            body = self.rfile.read(int(self.headers['Content-Length']))
        request = json.loads(body)
        case = self.headers['X-Test-Case']
        (ROOT / (case + '.upstream-request.json')).write_text(json.dumps(request, indent=2))
        parts = response_parts(request, self.headers['X-Test-Scenario'])
        raw = ''.join(parts).encode()
        (ROOT / (case + '.upstream-response')).write_bytes(raw)
        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream' if request['stream'] else 'application/json')
        if not request['stream']:
            self.send_header('Content-Length', str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
            return
        self.send_header('Transfer-Encoding', 'chunked')
        self.end_headers()
        if self.headers['X-Test-Delivery'] == 'single':
            writes = [raw]
        elif self.headers['X-Test-Delivery'] == 'frames':
            writes = [p.encode() for p in parts]
        elif self.headers['X-Test-Delivery'] == 'prefix1':
            writes = [raw[:1]] + [raw[i:i + 17] for i in range(1, len(raw), 17)]
        else:
            # First write has at least the full data: prefix, avoiding a separate SSE-detection bug.
            writes = [raw[i:i + 17] for i in range(0, len(raw), 17)]
        for fragment in writes:
            self.wfile.write(('%x\r\n' % len(fragment)).encode() + fragment + b'\r\n')
            self.wfile.flush()
            time.sleep(.003)
        self.wfile.write(b'0\r\n\r\n')
        self.wfile.flush()


if __name__ == '__main__':
    ThreadingHTTPServer(('0.0.0.0', 18080), Handler).serve_forever()
