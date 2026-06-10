from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
SMOKE_SCRIPT = REPO_ROOT / "deploy" / "scripts" / "post_deploy_smoke.sh"


def test_post_deploy_smoke_allows_degraded_ops_metrics_by_default(tmp_path: Path) -> None:
    result = _run_smoke(
        tmp_path,
        {
            "kind": "ops_metrics",
            "ready": True,
            "alerts": [
                {
                    "code": "langfuse.capture_input_output_disabled",
                    "severity": "degraded",
                    "message": "Langfuse input/output capture is disabled.",
                }
            ],
        },
    )

    assert result.returncode == 0, result.stderr
    assert "ops metrics degraded alert: langfuse.capture_input_output_disabled" in result.stderr


def test_post_deploy_smoke_fails_on_ops_metrics_error_alert(tmp_path: Path) -> None:
    result = _run_smoke(
        tmp_path,
        {
            "kind": "ops_metrics",
            "ready": True,
            "alerts": [
                {
                    "code": "gate_blocked.game_launch",
                    "severity": "error",
                    "message": "game_launch gate is blocked.",
                }
            ],
        },
    )

    assert result.returncode != 0
    assert "ops metrics error alert: gate_blocked.game_launch" in result.stderr
    assert "post-deploy smoke failed: ops metrics reports blocking alerts" in result.stderr


def _run_smoke(tmp_path: Path, ops_metrics: dict[str, Any]) -> subprocess.CompletedProcess[str]:
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("bash is required for post-deploy smoke script tests")
    bash_path = Path(bash)
    if os.name == "nt" and any(part.lower() in {"system32", "windowsapps"} for part in bash_path.parts):
        pytest.skip("Windows WSL bash shim cannot execute Windows workspace paths")

    server = _SmokeServer(ops_metrics)
    server.start()
    try:
        base_url = f"http://127.0.0.1:{server.port}"
        env = {
            **os.environ,
            "APP_BASE_URL": base_url,
            "API_HEALTH_URL": f"{base_url}/api/health",
            "APP_DIR": str(tmp_path),
            "CHECK_TASK_QUEUE": "false",
            "CHECK_TASK_WORKER": "false",
            "CHECK_TASK_ARTIFACTS": "false",
            "CHECK_NGINX": "false",
            "CHECK_SYSTEMD": "false",
            "CHECK_PORTS": "false",
            "CURL_TIMEOUT_SECONDS": "3",
        }
        return subprocess.run(
            [bash, str(SMOKE_SCRIPT)],
            cwd=REPO_ROOT,
            env=env,
            text=True,
            capture_output=True,
            timeout=20,
            check=False,
        )
    finally:
        server.stop()


class _SmokeServer:
    def __init__(self, ops_metrics: dict[str, Any]) -> None:
        self._ops_metrics = ops_metrics
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def port(self) -> int:
        return int(self._server.server_address[1])

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._server.shutdown()
        self._thread.join(timeout=5)
        self._server.server_close()

    def _handler(self) -> type[BaseHTTPRequestHandler]:
        ops_metrics = self._ops_metrics

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                path = urlsplit(self.path).path
                if path == "/api/health":
                    self._send_json(
                        {
                            "status": "ok",
                            "ready": True,
                            "external": {
                                "task_control": {
                                    "artifact_root": {"writable": True},
                                    "worker_fresh": True,
                                }
                            },
                        }
                    )
                elif path == "/api/ops/metrics":
                    self._send_json(ops_metrics)
                elif path == "/":
                    self._send_text(
                        '<!doctype html><html><head><script src="/assets/app.js"></script></head><body></body></html>',
                        "text/html; charset=utf-8",
                    )
                elif path == "/assets/app.js":
                    self._send_text("window.__smoke = true;\n", "application/javascript")
                else:
                    self.send_error(404)

            def log_message(self, format: str, *args: Any) -> None:
                return

            def _send_json(self, payload: dict[str, Any]) -> None:
                body = json.dumps(payload).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _send_text(self, body: str, content_type: str) -> None:
                encoded = body.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)

        return Handler
