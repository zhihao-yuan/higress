"""Pinned Envoy/Wasm comparison using an SSE fixture, not a live model."""
import concurrent.futures
import hashlib
import http.client
import json
from pathlib import Path
import shutil
import socket
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = Path(__file__).resolve().parent
IMAGE = "higress-registry.cn-hangzhou.cr.aliyuncs.com/higress/gateway@sha256:a82de493902012ce6b555ecb2244156f3c73824474d67549144a7efa334d0299"
CASES = {}
CONTAINERS = []
PORTS = []


def docker(*args):
    return subprocess.run(["docker", *args], check=True, capture_output=True,
                          text=True, timeout=60).stdout.strip()


def save(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n")


def record(case, side, role, **fields):
    with case["lock"]:
        case["timeline"].append(dict(sequence=len(case["timeline"]), time_ns=time.monotonic_ns(),
                                     side=side, role=role, **fields))


def event(kind, **fields):
    return ("data: " + json.dumps(dict(type=kind, **fields), separators=(",", ":")) + "\n\n").encode()


def events(role):
    a = role == "a"
    start = event("message_start", message=dict(
        id="msg_" + role, role="assistant", content=[], model="claude-fixture",
        usage=dict(input_tokens=955 if a else 45, output_tokens=0,
                   service_tier="standard" if a else "priority")))
    if a:
        middle = [event("content_block_delta", index=0, delta=dict(type="text_delta", text="answer a"))]
    else:
        middle = [
            event("content_block_start", index=0, content_block=dict(type="tool_use", id="call_b", name="weather", input={})),
            event("content_block_delta", index=0, delta=dict(type="input_json_delta", partial_json='{"city":"Beijing"}'))]
    return [start, *middle,
            event("message_delta", delta=dict(stop_reason="end_turn" if a else "tool_use"),
                  usage=dict(output_tokens=256 if a else 510)),
            event("message_stop")]


class Fixture(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def do_POST(self):
        label = self.headers["x-observation-id"]
        name, role = label.rsplit("-", 1)
        case = CASES[name]
        folder = ROOT / "gateway" / name
        if self.headers.get("Transfer-Encoding", "").lower() == "chunked":
            parts = []
            while True:
                size = int(self.rfile.readline().split(b";", 1)[0], 16)
                if size == 0:
                    while self.rfile.readline() not in (b"\r\n", b"\n", b""):
                        pass
                    break
                parts.append(self.rfile.read(size))
                assert self.rfile.read(2) == b"\r\n"
            body = b"".join(parts)
        else:
            body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        (folder / (role + ".upstream.request.json")).write_bytes(body)
        save(folder / (role + ".upstream.headers.json"), dict(path=self.path, headers=list(self.headers.items())))
        frames = events(role)
        (folder / (role + ".upstream.sse")).write_bytes(b"".join(frames))
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()

        def send(index, frame):
            record(case, "upstream.send", role, index=index, event=json.loads(frame[5:])["type"])
            self.wfile.write(("%x\r\n" % len(frame)).encode() + frame + b"\r\n")
            self.wfile.flush()

        try:
            send(0, frames[0])
            if case["parallel"]:
                wait = case["b_started"] if role == "a" else case["a_done"]
                if not wait.wait(30):
                    raise TimeoutError("handshake timed out: " + label)
            for index, frame in enumerate(frames[1:], 1):
                send(index, frame)
            self.wfile.write(b"0\r\n\r\n")
            self.wfile.flush()
        except Exception as exc:
            case["errors"].append(repr(exc))
            self.close_connection = True


def request(port, name, role):
    case = CASES[name]
    folder = ROOT / "gateway" / name
    if role == "b" and not case["a_started"].wait(30):
        raise TimeoutError("A did not emit its first chunk")
    body = dict(model="claude-fixture", messages=[dict(role="user", content="fixture " + role)], stream=True)
    save(folder / (role + ".client.request.json"), body)
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=35)
    conn.request("POST", "/v1/chat/completions", json.dumps(body),
                 {"Content-Type": "application/json", "x-observation-id": name + "-" + role})
    response = conn.getresponse()
    raw, line, chunks = bytearray(), bytearray(), []
    try:
        while True:
            char = response.read(1)
            if not char:
                record(case, "client.complete", role)
                case[role + "_done"].set()
                break
            raw.extend(char)
            line.extend(char)
            if char != b"\n":
                continue
            data = bytes(line).strip()
            line.clear()
            if data.startswith(b"data:") and data != b"data: [DONE]":
                chunk = json.loads(data[5:].strip())
                record(case, "downstream.receive", role, index=len(chunks),
                       id=chunk.get("id"), service_tier=chunk.get("service_tier"))
                chunks.append(chunk)
                case[role + "_started"].set()
    finally:
        conn.close()
        (folder / (role + ".client.sse")).write_bytes(raw)
        save(folder / (role + ".client.headers.json"), dict(status=response.status, headers=response.getheaders()))
    assert response.status == 200 and len(chunks) == (4 if role == "a" else 5), (name, role, response.status, chunks)
    tier = "standard" if role == "a" else "priority"
    expected = dict(prompt_tokens=955 if role == "a" else 45,
                    completion_tokens=256 if role == "a" else 510,
                    total_tokens=1211 if role == "a" else 555)
    checks = [dict(index=i, id=c.get("id"), id_ok=c.get("id") == "msg_" + role,
                   service_tier=c.get("service_tier"), tier_ok=c.get("service_tier") == tier)
              for i, c in enumerate(chunks)]
    usage = chunks[-1].get("usage")
    usage_checks = {key: usage is not None and usage.get(key) == value for key, value in expected.items()}
    choices = [choice for chunk in chunks for choice in chunk.get("choices", [])]
    text = "".join(str(choice.get("delta", {}).get("content") or "") for choice in choices)
    calls = [call for choice in choices for call in choice.get("delta", {}).get("tool_calls", [])]
    arguments = "".join(call.get("function", {}).get("arguments", "") for call in calls)
    payload_ok = (text == "answer a" if role == "a" else arguments == '{"city":"Beijing"}'
                  and any(c.get("id") == "call_b" and c.get("function", {}).get("name") == "weather" for c in calls))
    finish = [c.get("finish_reason") for c in choices if c.get("finish_reason")]
    finish_ok = finish == ["stop" if role == "a" else "tool_calls"]
    request_info = json.loads((folder / (role + ".upstream.headers.json")).read_text())
    request_body = json.loads((folder / (role + ".upstream.request.json")).read_text())
    if case["provider"] == "vertex":
        assert "/publishers/anthropic/models/claude-fixture:streamRawPredict" in request_info["path"]
        assert request_body["anthropic_version"] == "vertex-2023-10-16"
        assert "model" not in request_body
    else:
        assert request_info["path"].split("?")[0] == "/v1/messages"
        assert request_body["model"] == "claude-fixture"
    return dict(case=name, provider=case["provider"], role=role, status=response.status,
                response_sha256=hashlib.sha256(raw).hexdigest(), chunks=checks,
                usage=usage, expected_usage=expected, usage_checks=usage_checks,
                payload_preserved=payload_ok, finish_reason_preserved=finish_ok,
                correct=all(c["id_ok"] and c["tier_ok"] for c in checks)
                and all(usage_checks.values()) and payload_ok and finish_ok)


def create_gateway(label, provider, upstream_port):
    folder = ROOT / "gateway" / (label + "-" + provider)
    folder.mkdir(parents=True, exist_ok=True)
    cfg = json.loads((ROOT / "envoy-template.json").read_text())
    hcm = cfg["static_resources"]["listeners"][0]["filter_chains"][0]["filters"][0]["typed_config"]
    wasm = hcm["http_filters"][0]["typed_config"]["config"]
    wasm["configuration"]["value"] = json.dumps(dict(provider=dict(
        type=provider, apiTokens=["fixture-placeholder"], modelMapping={"*": "claude-fixture"})))
    cfg["static_resources"]["clusters"][0]["load_assignment"]["endpoints"][0]["lb_endpoints"][0]["endpoint"]["address"]["socket_address"]["port_value"] = upstream_port
    cfg["admin"]["address"]["socket_address"]["address"] = "0.0.0.0"
    save(folder / "envoy.json", cfg)
    shutil.copyfile(ROOT / (label + ".wasm"), folder / "plugin.wasm")
    name = "claude-matrix-" + label + "-" + provider + "-" + str(time.time_ns())
    docker("run", "-d", "--name", name, "-p", "127.0.0.1::10000", "-p", "127.0.0.1::15000",
           "-v", str(folder) + ":/lab:ro", "--entrypoint", "/usr/local/bin/envoy", IMAGE,
           "-c", "/lab/envoy.json", "--concurrency", "1", "--log-level", "warning")
    CONTAINERS.append(name)
    port = int(docker("port", name, "10000/tcp").rsplit(":", 1)[1])
    admin = int(docker("port", name, "15000/tcp").rsplit(":", 1)[1])
    PORTS.extend([port, admin])
    for _ in range(100):
        try:
            c = http.client.HTTPConnection("127.0.0.1", admin, timeout=1)
            c.request("GET", "/ready")
            response = c.getresponse()
            response.read()
            c.close()
            if response.status == 200:
                return name, port, admin, folder
        except OSError:
            pass
        time.sleep(.1)  # Readiness only; interleaving uses events.
    raise RuntimeError("gateway not ready: " + name)


def check_timeline(case):
    trace = case["timeline"]
    def seq(side, role, index=None):
        return next(e["sequence"] for e in trace
                    if e["side"] == side and e["role"] == role
                    and (index is None or e.get("index") == index))
    sequence = [seq("upstream.send", "a", 0), seq("downstream.receive", "a", 0),
                seq("upstream.send", "b", 0), seq("downstream.receive", "b", 0),
                seq("upstream.send", "a", 1), seq("client.complete", "a"),
                seq("upstream.send", "b", 1), seq("client.complete", "b")]
    assert sequence == sorted(set(sequence)), sequence
    return dict(ordered_sequences=sequence, correct=True)


def main():
    (ROOT / "gateway").mkdir(exist_ok=True)
    server = ThreadingHTTPServer(("0.0.0.0", 0), Fixture)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    results, timing = [], {}
    cleanup = {}
    try:
        save(ROOT / "image.json", json.loads(docker("image", "inspect", IMAGE)))
        for label in ("baseline", "fixed"):
            for provider in ("claude", "vertex"):
                name, port, admin, folder = create_gateway(label, provider, server.server_port)
                for mode in ("control", "pair1", "pair2", "pair3"):
                    key = label + "-" + provider + "-" + mode
                    (ROOT / "gateway" / key).mkdir(exist_ok=True)
                    case = dict(provider=provider, parallel=mode != "control", lock=threading.Lock(),
                                timeline=[], errors=[], **{r + "_" + event: threading.Event()
                                for r in ("a", "b") for event in ("started", "done")})
                    CASES[key] = case
                    if mode == "control":
                        pair = [request(port, key, "a")]
                    else:
                        with concurrent.futures.ThreadPoolExecutor(2) as pool:
                            futures = [pool.submit(request, port, key, role) for role in ("a", "b")]
                            pair = [f.result() for f in futures]
                        timing[key] = check_timeline(case)
                    results.extend(pair)
                    save(ROOT / "gateway" / key / "timeline.json", case["timeline"])
                    save(ROOT / "gateway-results.json", results)
                    assert not case["errors"], case["errors"]
                    assert all(r["payload_preserved"] and r["finish_reason_preserved"] for r in pair)
                    if label == "fixed" or mode == "control":
                        for r in pair:
                            assert r["correct"], r
                    else:
                        a, b = pair
                        # Assert both named failure modes, rather than any failed stream.
                        assert a["chunks"][0]["id"] == "msg_a"
                        assert all(c["id"] == "msg_b" and c["service_tier"] == "priority" for c in a["chunks"][1:])
                        assert a["usage"] == dict(prompt_tokens=45, completion_tokens=256, total_tokens=301)
                        assert all(c["id_ok"] and c["tier_ok"] for c in b["chunks"])
                        assert b["usage"] == dict(prompt_tokens=45, completion_tokens=766, total_tokens=811)
                c = http.client.HTTPConnection("127.0.0.1", admin, timeout=5)
                c.request("GET", "/stats?filter=wasm")
                stats = c.getresponse().read().decode()
                c.close()
                (folder / "wasm-stats.txt").write_text(stats)
                (folder / "envoy.log").write_text(docker("logs", name))
                for suffix in ("crash_total", "worker_fail_open_skip_total", "worker_uninitialized", "rebuild_memory_total"):
                    values = [line.rsplit(":", 1)[1].strip() for line in stats.splitlines() if line.split(":")[0].endswith("." + suffix)]
                    assert values and all(v == "0" for v in values), (suffix, values)
                docker("rm", "-f", name)
        assert len(results) == 28, len(results)
        save(ROOT / "timing-results.json", timing)
        save(ROOT / "summary.json", dict(http_calls=len(results), pair_groups=len(timing),
              fixed_streams_correct=all(r["correct"] for r in results if r["case"].startswith("fixed")),
              baseline_target_failures=12, controls_correct=4))
        print("PASS: 28 HTTP calls; both target failures reproduced in each of 6 baseline pairs; fixed streams correct.")
    finally:
        for name in CONTAINERS:
            remaining = docker("ps", "-a", "--filter", "name=^/" + name + "$", "--format", "{{.Names}}")
            if remaining:
                p = subprocess.run(["docker", "logs", name], capture_output=True, text=True)
                (ROOT / "gateway" / (name + ".log")).write_text(p.stdout + p.stderr)
                docker("rm", "-f", name)
            cleanup[name] = not bool(docker("ps", "-a", "--filter", "name=^/" + name + "$", "--format", "{{.Names}}"))
        fixture_port = server.server_port
        server.shutdown()
        server.server_close()
        thread.join(5)
        ports_closed = {}
        for port in PORTS + [fixture_port]:
            with socket.socket() as probe:
                probe.settimeout(1)
                ports_closed[str(port)] = probe.connect_ex(("127.0.0.1", port)) != 0
        save(ROOT / "gateway-cleanup.json", dict(containers_absent=cleanup,
             fixture_port=fixture_port, fixture_closed=server.fileno() == -1,
             ports_closed=ports_closed, server_thread_stopped=not thread.is_alive()))
        assert all(cleanup.values()) and all(ports_closed.values()) and server.fileno() == -1 and not thread.is_alive()


if __name__ == "__main__":
    main()
