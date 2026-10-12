"""Real CLI printing while an HTTP stylesheet is still pending."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import re
from socketserver import TCPServer
import threading

import pytest

from .browser_lifecycle_support import LifecycleCLI


def verify_pdf_readiness(tmp_path: Path, mode: str):
    cli = LifecycleCLI(tmp_path)
    requested = threading.Event()
    release = threading.Event()
    sent = threading.Event()
    css_width = "90mm 54mm" if mode == "document" else "140mm 80mm"
    css = (
        f"@page {{size:{css_width};margin:0}}html,body{{margin:0}}"
        ".card{background:#10314f;color:white;font:14pt serif}"
    ).encode()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *unused):
            pass

        def do_GET(self):
            is_css = self.path == "/slow.css"
            body = (
                css
                if is_css
                else (
                    b"<!doctype html><head><link rel=stylesheet href=/slow.css></head>"
                    b"<body><div class=card>Vector Card 90x54</div></body>"
                )
            )
            self.send_response(200)
            self.send_header("Content-Type", "text/css" if is_css else "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            if is_css:
                requested.set()
                if not release.wait(timeout=30):
                    return
            self.wfile.write(body)
            self.wfile.flush()
            if is_css:
                sent.set()

    class Server(ThreadingHTTPServer):
        def server_bind(self):
            # A fixed loopback test has no dependency on hostname lookup.
            TCPServer.server_bind(self)
            self.server_name = "127.0.0.1"
            self.server_port = self.socket.getsockname()[1]

    server = Server(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    timer = None
    sid = None
    try:
        started = cli(
            "browser_start", "--headless", "true", "--temp", "--reuse", "none"
        )
        assert started["connected"], started
        sid = started["session_id"]
        url = f"http://127.0.0.1:{server.server_port}/"
        cli("page_goto", "--session-id", sid, "--url", url, "--no-wait")
        assert requested.wait(timeout=5), "Chrome did not request the real stylesheet"
        before = cli(
            "js_evaluate",
            "--session-id",
            sid,
            "--expression",
            "({url:location.href,ready:document.readyState})",
        )["result"]
        assert before["url"] == url and before["ready"] != "complete", before
        assert not sent.is_set()

        timer = threading.Timer(4, release.set)
        timer.start()
        out = tmp_path / "card.pdf"
        flags = {
            "document": ("--prefer-css-page-size",),
            "preset": ("--paper", "card-cn"),
            "units": ("--paper-width", "90mm", "--paper-height", "54mm"),
        }[mode]
        printed = cli("page_pdf", "--session-id", sid, "--path", str(out), *flags)
        assert sent.is_set(), "PDF returned before the real stylesheet was delivered"
        assert printed["pages"] == 1, printed
        assert printed["page_size_mm"] == pytest.approx([90, 54], abs=0.2), printed
        data = out.read_bytes()
        match = re.search(rb"/MediaBox\s*\[\s*0\s+0\s+([\d.]+)\s+([\d.]+)\s*\]", data)
        assert match and data.startswith(b"%PDF-") and b"/Font" in data, data[:100]
        assert [float(match[1]), float(match[2])] == pytest.approx(
            [255.12, 153.07], abs=0.5
        )
        after = cli(
            "js_evaluate",
            "--session-id",
            sid,
            "--expression",
            "({url:location.href,ready:document.readyState,temporaryStyle:!!document.getElementById('__adb_page_size__')})",
        )["result"]
        assert after == {"url": url, "ready": "complete", "temporaryStyle": False}, (
            after
        )
        cli.evidence(
            "pdf-readiness",
            mode=mode,
            before=before,
            after=after,
            pdf=printed,
            stylesheet_delivered=True,
            actual_pdf_mediabox=[float(match[1]), float(match[2])],
        )
    finally:
        release.set()
        if timer:
            timer.cancel()
        if sid:
            stopped = cli("browser_stop", "--session-id", sid)
            assert stopped["stopped"], stopped
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
