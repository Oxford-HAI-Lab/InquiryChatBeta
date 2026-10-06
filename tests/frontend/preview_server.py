#!/usr/bin/env python3
"""Serve the real frontend with in-memory browser fixtures. Never imports app.py.

Run: python3 tests/frontend/preview_server.py --port 8766
Open /runner.html for regressions or /fixture?scene=chat for manual inspection.
Only explicitly allowed frontend files are served; env and sessions are inaccessible.
"""
from argparse import ArgumentParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit, parse_qs
import mimetypes

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        url = urlsplit(self.path)
        if url.path in ("/", "/fixture"):
            page = (ROOT / "static/index.html").read_text()
            page = page.replace("<head>", '<head><script src="/fixture.js"></script>', 1)
            if "baseline" in parse_qs(url.query):
                page = page.replace('/static/app.js?', '/baseline/app.js?')
            page = page.replace("</body>", '<script src="/fixture_bootstrap.js"></script></body>')
            self.respond(page.encode(), "text/html; charset=utf-8")
            return
        permitted = {
            "/runner.html": HERE / "runner.html",
            "/runner.js": HERE / "runner.js",
            "/fixture.js": HERE / "fixture.js",
            "/fixture_bootstrap.js": HERE / "fixture_bootstrap.js",
            "/static/app.js": ROOT / "static/app.js",
            "/static/style.css": ROOT / "static/style.css",
        }
        if url.path == "/baseline/app.js" and self.server.baseline:
            permitted[url.path] = self.server.baseline
        target = permitted.get(url.path)
        if not target or not target.is_file():
            self.respond(b"Not found: this fixture server exposes no backend or user files.", "text/plain", 404)
            return
        self.respond(target.read_bytes(), mimetypes.guess_type(target.name)[0] or "text/plain")

    def do_POST(self):
        self.respond(b"All fixture mutations must remain in browser memory.", "text/plain", 405)

    do_DELETE = do_POST

    def respond(self, body, kind, status=200):
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_):
        pass


if __name__ == "__main__":
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--baseline", type=Path, help="Optional pre-edit app.js snapshot")
    args = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    server.baseline = args.baseline.resolve() if args.baseline else None
    print(f"Frontend fixtures: http://127.0.0.1:{args.port}/fixture?scene=chat", flush=True)
    print(f"Regression runner: http://127.0.0.1:{args.port}/runner.html", flush=True)
    server.serve_forever()
