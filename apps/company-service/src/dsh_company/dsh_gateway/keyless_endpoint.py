from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


@dataclass(frozen=True, slots=True)
class ModelRequest:
    body: dict[str, Any]
    marker: str

    def contains(self, text: str) -> bool:
        return text in json.dumps(self.body)


class _ModelServer(ThreadingHTTPServer):
    requests: list[ModelRequest]


class _ModelHandler(BaseHTTPRequestHandler):
    server: _ModelServer

    def do_POST(self) -> None:
        length = int(self.headers.get("content-length", "0"))
        body = json.loads(self.rfile.read(length).decode("utf-8"))
        session_marker = next(
            content
            for message in body["messages"]
            if isinstance((content := message.get("content")), str)
            if content.startswith("remember ")
        )
        self.server.requests.append(ModelRequest(body=body, marker=session_marker))
        self.send_response(200)
        self.send_header("content-type", "text/event-stream")
        self.end_headers()
        chunks = (
            'data: {"choices":[{"delta":{"role":"assistant","content":""}}]}\n\n',
            f'data: {{"choices":[{{"delta":{{"content":"stored {session_marker}"}}}}]}}\n\n',
            'data: {"choices":[{"delta":{"content":""},"finish_reason":"stop"}],'
            '"usage":{"prompt_tokens":5,"completion_tokens":3}}\n\n',
            "data: [DONE]\n\n",
        )
        for chunk in chunks:
            self.wfile.write(chunk.encode("utf-8"))

    def log_message(self, _format: str, *_args: object) -> None:
        return


class KeylessModelEndpoint:
    def __init__(self) -> None:
        self._server = _ModelServer(("127.0.0.1", 0), _ModelHandler)
        self._server.requests = []
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="dsh-company-keyless-endpoint",
            daemon=True,
        )

    def __enter__(self) -> KeylessModelEndpoint:
        self._thread.start()
        return self

    def __exit__(self, _exc_type: object, _exc: object, _tb: object) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join()

    @property
    def base_url(self) -> str:
        host = self._server.server_address[0]
        port = self._server.server_address[1]
        return f"http://{host}:{port}"

    @property
    def requests(self) -> list[ModelRequest]:
        return self._server.requests

    def request_for(self, marker: str) -> ModelRequest:
        return next(request for request in self._server.requests if request.marker == marker)
