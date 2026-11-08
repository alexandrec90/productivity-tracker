"""The collector's and the overlay's side of the HTTP API: stdlib only, JSON in and out."""

import json
import urllib.parse
import urllib.request
from typing import Any


class TrackerClient:
    def __init__(self, base_url: str, token: str = "", timeout: float = 5.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout

    def build_request(self, method: str, path: str, payload: Any = None) -> urllib.request.Request:
        if not self.base_url.startswith(("http://", "https://")):
            raise ValueError(f"TRACKER_URL must be an http(s) URL, got {self.base_url!r}")
        data = None if payload is None else json.dumps(payload).encode()
        headers = {"Accept": "application/json"}
        if data is not None:
            headers["Content-Type"] = "application/json"
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return urllib.request.Request(  # noqa: S310 - scheme checked above
            self.base_url + path, data=data, method=method, headers=headers
        )

    def request(
        self, method: str, path: str, payload: Any = None, timeout: float | None = None
    ) -> Any:
        req = self.build_request(method, path, payload)
        with urllib.request.urlopen(req, timeout=timeout or self.timeout) as response:  # noqa: S310 - scheme checked above
            body = response.read()
        return json.loads(body) if body else None

    def post_snapshot(self, snapshot: dict[str, Any]) -> None:
        self.request("POST", "/snapshots", snapshot)

    def state(self) -> dict[str, Any]:
        return self.request("GET", "/state")

    def add_task(self, name: str) -> dict[str, Any]:
        return self.request("POST", "/tasks", {"name": name})

    def remove_task(self, task_id: int) -> None:
        self.request("DELETE", f"/tasks/{task_id}")

    def set_active(self, task_id: int, active: bool) -> dict[str, Any]:
        return self.request("PUT", f"/tasks/{task_id}/active", {"active": active})

    def request_focus(self, host: str, pid: int) -> None:
        self.request("POST", "/focus", {"host": host, "pid": pid})

    def next_focus(self, host: str, wait: float = 20.0) -> int | None:
        """Wait for a click on one of `host`'s sessions: its pid, or None if `wait` passed."""
        path = f"/focus/{urllib.parse.quote(host, safe='')}?wait={wait:g}"
        return self.request("GET", path, timeout=wait + self.timeout)["pid"]
