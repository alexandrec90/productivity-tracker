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
        if self.command == "POST":
            self.send_response(204)
            self.end_headers()
            return
        payload = json.dumps({"ok": True}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    do_GET = do_POST = do_PUT = _handle

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


def test_no_token_sends_no_authorization_header(server):
    TrackerClient(server).state()
    assert Recorder.calls[0][2] is None


def test_a_non_http_url_is_refused():
    with pytest.raises(ValueError, match="http"):
        TrackerClient("file:///etc/passwd").build_request("GET", "/state")
