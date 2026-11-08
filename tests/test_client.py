import json
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import ClassVar

import pytest

from productivity_tracker.client import TrackerClient

TOKEN = "t0k"


class Recorder(BaseHTTPRequestHandler):
    calls: ClassVar[list[tuple[str, str, str | None, object]]] = []

    def _handle(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length)) if length else None
        Recorder.calls.append((self.command, self.path, self.headers.get("Authorization"), body))
        if self.command == "DELETE" or (self.command == "POST" and self.path != "/tasks"):
            self.send_response(204)
            self.end_headers()
            return
        answer = {"pid": 42} if self.path.startswith("/focus") else {"ok": True}
        payload = json.dumps(answer).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    do_GET = do_POST = do_PUT = do_DELETE = _handle

    def log_message(self, *args: object) -> None:
        pass


@pytest.fixture
def server() -> Iterator[str]:
    Recorder.calls = []
    httpd = HTTPServer(("127.0.0.1", 0), Recorder)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}/"
    httpd.shutdown()
    httpd.server_close()


def test_the_client_speaks_the_api_with_its_token(server):
    client = TrackerClient(server, token=TOKEN)

    client.post_snapshot({"host": "desk", "sessions": []})
    assert client.state() == {"ok": True}
    assert client.set_active(7, False) == {"ok": True}

    assert Recorder.calls == [
        ("POST", "/snapshots", "Bearer t0k", {"host": "desk", "sessions": []}),
        ("GET", "/state", "Bearer t0k", None),
        ("PUT", "/tasks/7/active", "Bearer t0k", {"active": False}),
    ]


def test_the_list_is_edited_over_the_api(server):
    client = TrackerClient(server)

    assert client.add_task("itopia") == {"ok": True}
    client.remove_task(7)

    assert Recorder.calls == [
        ("POST", "/tasks", None, {"name": "itopia"}),
        ("DELETE", "/tasks/7", None, None),
    ]


def test_a_click_goes_up_and_comes_down_to_the_collector(server):
    client = TrackerClient(server)

    client.request_focus("DESKTOP-B9FC8VP", 42)
    assert client.next_focus("DESKTOP-B9FC8VP", wait=20) == 42

    assert Recorder.calls == [
        ("POST", "/focus", None, {"host": "DESKTOP-B9FC8VP", "pid": 42}),
        ("GET", "/focus/DESKTOP-B9FC8VP?wait=20", None, None),
    ]


def test_waiting_for_a_click_outlasts_the_client_s_usual_timeout(monkeypatch):
    client = TrackerClient("http://server", timeout=5.0)
    seen: list[float | None] = []

    def request(method, path, payload=None, timeout=None):
        seen.append(timeout)
        return {"pid": None}

    monkeypatch.setattr(client, "request", request)

    assert client.next_focus("a host", wait=20) is None
    assert seen == [25.0]


def test_no_token_sends_no_authorization_header(server):
    TrackerClient(server).state()
    assert Recorder.calls[0][2] is None


def test_a_non_http_url_is_refused():
    with pytest.raises(ValueError, match="http"):
        TrackerClient("file:///etc/passwd").build_request("GET", "/state")
