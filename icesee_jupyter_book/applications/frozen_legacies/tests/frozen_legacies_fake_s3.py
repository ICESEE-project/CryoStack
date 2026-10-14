"""A small local S3-compatible HTTP server for tests (no AWS access).

Implements just what the read-only Frozen Legacies S3 provider uses:
``ListObjectsV2`` (paginated), ``HeadObject`` and ``GetObject`` with
``Range``. Faults can be injected per key or prefix: access denied (403),
transient server errors (503, retried by the SDK), interrupted transfers
(the connection closes after half the body) and per-request delay.

Requests are not authenticated; the tests give the SDK dummy credentials
through the standard environment variables.
"""
from __future__ import annotations

import threading
import time
from email.utils import formatdate
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlsplit
from xml.sax.saxutils import escape


class FakeS3:
    def __init__(self, bucket: str = "radar-archive"):
        self.bucket = bucket
        self.objects: dict[str, tuple[bytes, str, float]] = {}
        self.denied: set[str] = set()          # key prefixes answered with 403
        self.transient: dict[str, int] = {}    # key -> number of 503s before success
        self.truncate: set[str] = set()        # keys whose GET body is cut short
        self.down = False                      # every request fails with 503
        self.page_size = 1000
        self.delay_s = 0.0
        self.requests: list[tuple[str, str, bool]] = []   # (method, key, ranged)
        self._lock = threading.Lock()
        self._server: ThreadingHTTPServer | None = None

    # ── content ──────────────────────────────────────────────────────
    def put(self, key: str, data: bytes, *, etag: str | None = None) -> None:
        version = len(self.objects) + 1
        self.objects[key] = (data, etag or f"etag-{version}-{len(data)}", time.time())

    def delete(self, key: str) -> None:
        self.objects.pop(key, None)

    def count(self, method: str) -> int:
        with self._lock:
            return sum(1 for m, _k, _r in self.requests if m == method)

    # ── server ───────────────────────────────────────────────────────
    @property
    def url(self) -> str:
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}"

    def start(self) -> "FakeS3":
        fake = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args):
                pass

            def do_HEAD(self):
                fake._handle(self, head=True)

            def do_GET(self):
                fake._handle(self, head=False)

        class Server(ThreadingHTTPServer):
            def handle_error(self, request, client_address):
                pass                            # clients hanging up on cut transfers

        self._server = Server(("127.0.0.1", 0), Handler)
        self._server.daemon_threads = True
        threading.Thread(target=self._server.serve_forever, daemon=True).start()
        return self

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()

    # ── protocol ─────────────────────────────────────────────────────
    def _send(self, h, status, body=b"", headers=None, *, head=False, length=None):
        h.send_response(status)
        for name, value in (headers or {}).items():
            h.send_header(name, value)
        h.send_header("Content-Length", str(len(body) if length is None else length))
        h.end_headers()
        if not head and body:
            h.wfile.write(body)

    def _error(self, h, status, code, *, head=False):
        body = (f'<?xml version="1.0" encoding="UTF-8"?><Error><Code>{code}</Code>'
                f"<Message>{code}</Message></Error>").encode()
        self._send(h, status, b"" if head else body,
                   {"Content-Type": "application/xml"}, head=head, length=0 if head else None)

    def _denied(self, key: str) -> bool:
        return any(key.startswith(p) for p in self.denied)

    def _handle(self, h, *, head: bool):
        if self.delay_s:
            time.sleep(self.delay_s)
        parts = urlsplit(h.path)
        path = unquote(parts.path).lstrip("/")
        bucket, _, key = path.partition("/")
        with self._lock:
            self.requests.append(("HEAD" if head else "GET", key, "Range" in h.headers))
        if self.down:
            return self._error(h, 503, "ServiceUnavailable", head=head)
        if bucket != self.bucket:
            return self._error(h, 404, "NoSuchBucket", head=head)
        if not key:
            return self._list(h, parse_qs(parts.query))
        if self._denied(key):
            return self._error(h, 403, "AccessDenied", head=head)
        with self._lock:
            if self.transient.get(key, 0) > 0:
                self.transient[key] -= 1
                return self._error(h, 503, "SlowDown", head=head)
        if key not in self.objects:
            return self._error(h, 404, "NoSuchKey" if not head else "NotFound", head=head)
        data, etag, mtime = self.objects[key]
        headers = {"ETag": f'"{etag}"', "Last-Modified": formatdate(mtime, usegmt=True),
                   "Accept-Ranges": "bytes", "Content-Type": "application/octet-stream"}
        if head:
            return self._send(h, 200, b"", headers, head=True, length=len(data))
        status, body = 200, data
        wanted = h.headers.get("Range")
        if wanted and wanted.startswith("bytes="):
            first, _, last = wanted[6:].partition("-")
            first = int(first)
            last = min(int(last) if last else len(data) - 1, len(data) - 1)
            if first >= len(data):
                return self._error(h, 416, "InvalidRange")
            body = data[first:last + 1]
            status = 206
            headers["Content-Range"] = f"bytes {first}-{last}/{len(data)}"
        if key in self.truncate:
            h.send_response(status)
            for name, value in headers.items():
                h.send_header(name, value)
            h.send_header("Content-Length", str(len(body)))
            h.send_header("Connection", "close")
            h.end_headers()
            h.wfile.write(body[:len(body) // 2])
            h.wfile.flush()
            h.close_connection = True
            return
        self._send(h, status, body, headers)

    def _list(self, h, query):
        prefix = (query.get("prefix") or [""])[0]
        if self._denied(prefix):
            return self._error(h, 403, "AccessDenied")
        try:
            max_keys = int((query.get("max-keys") or ["1000"])[0])
        except ValueError:
            max_keys = 1000
        start = int((query.get("continuation-token") or ["0"])[0])
        keys = sorted(k for k in self.objects if k.startswith(prefix))
        size = max(1, min(max_keys, self.page_size))
        page = keys[start:start + size]
        truncated = start + size < len(keys)
        items = []
        for key in page:
            data, etag, mtime = self.objects[key]
            stamp = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(mtime))
            items.append(f"<Contents><Key>{escape(key)}</Key><LastModified>{stamp}</LastModified>"
                         f"<ETag>&quot;{etag}&quot;</ETag><Size>{len(data)}</Size>"
                         "<StorageClass>STANDARD</StorageClass></Contents>")
        body = ('<?xml version="1.0" encoding="UTF-8"?>'
                '<ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">'
                f"<Name>{self.bucket}</Name><Prefix>{escape(prefix)}</Prefix>"
                f"<KeyCount>{len(page)}</KeyCount><MaxKeys>{max_keys}</MaxKeys>"
                f"<IsTruncated>{'true' if truncated else 'false'}</IsTruncated>"
                + (f"<NextContinuationToken>{start + size}</NextContinuationToken>"
                   if truncated else "")
                + "".join(items) + "</ListBucketResult>").encode()
        self._send(h, 200, body, {"Content-Type": "application/xml"})
