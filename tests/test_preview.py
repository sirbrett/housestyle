"""Share-preview checker tests against a local HTTP server."""
from __future__ import annotations

import http.server
import json
import struct
import tempfile
import threading
import unittest
import zlib
from pathlib import Path

from housestyle.errors import ConfigError
from housestyle.imagesize import image_size
from housestyle.preview import load_standard, run_preview

FIXTURES = Path(__file__).resolve().parent.parent / "housestyle" / "selftest" / "fixtures"


def png(width: int, height: int) -> bytes:
    def chunk(kind: bytes, body: bytes) -> bytes:
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))
    raw = b"".join(b"\x00" + b"\x80" * (width * 3) for _ in range(height))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


PAGES = {
    "/good.html": """<!DOCTYPE html><html><head><meta charset="utf-8">
<title>Acme | Why we changed our pricing</title>
<meta property="og:site_name" content="Acme">
<meta property="og:title" content="Why we changed our pricing">
<meta property="og:description" content="The reasoning behind the new tiers, in plain words.">
<meta property="og:image" content="/big.png">
<meta name="author" content="Brett Raynes">
<meta property="article:published_time" content="2026-09-01">
</head><body><p>Body text is not a share field.</p></body></html>""",
    "/bad.html": """<!DOCTYPE html><html><head><meta charset="utf-8">
<title>Acme</title>
<meta property="og:site_name" content="Acme">
<meta property="og:image" content="/small.png">
<meta name="author" content="@acme">
<meta name="keywords" content="leverage">
</head><body></body></html>""",
    "/dup1.html": """<html><head><title>Insights</title>
<meta name="description" content="We leverage insight."><meta property="og:image" content="/missing.png">
<meta name="author" content="Jo Bloggs"><meta name="date" content="2026-01-01"></head></html>""",
    "/dup2.html": """<html><head><title>Insights</title>
<meta name="description" content="A second page with the same title."><meta property="og:image" content="/big.png">
<meta name="author" content="Jo Bloggs"><meta name="date" content="2026-01-02"></head></html>""",
}
IMAGES = {"/big.png": png(1200, 627), "/small.png": png(800, 418)}


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):  # quiet
        pass

    def do_GET(self):
        if self.path in PAGES:
            body = PAGES[self.path].encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
        elif self.path in IMAGES:
            body = IMAGES[self.path]
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
        else:
            body = b"not found"
            self.send_response(404)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


STANDARD = """
standard:
  genre: client-facing
  author_tag: name=author
  image:
    min_width: 1200
    min_height: 627
  site_defaults:
    description: ["Acme is a company."]
"""


class PreviewTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.tmp = tempfile.TemporaryDirectory()
        cls.dir = Path(cls.tmp.name)
        (cls.dir / "standard.yaml").write_text(STANDARD)
        (cls.dir / "targets.txt").write_text("\n".join([
            "# comment line", f"{cls.base}/good.html", f"{cls.base}/bad.html",
            f"{cls.base}/dup1.html", f"{cls.base}/dup2.html",
            str(FIXTURES / "docs" / "report.pdf"), "http://127.0.0.1:9/unreachable.html", "",
        ]))
        cls.out = cls.dir / "cards.html"
        cls.report = run_preview(cls.dir / "targets.txt", FIXTURES / "rules.yaml",
                                 cls.dir / "standard.yaml", cls.out, timeout=5)
        cls.by_name = {t.target.rsplit("/", 1)[-1]: t for t in cls.report.targets}

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.tmp.cleanup()

    def statuses(self, name):
        return {k: v.status for k, v in self.by_name[name].checks.items()}

    def test_good_page_passes_every_check(self):
        self.assertEqual(self.statuses("good.html"), {
            "title": "pass", "description": "pass", "image": "pass", "author": "pass",
            "date": "pass", "clean": "pass", "pdf": "n/a"})
        self.assertTrue(self.by_name["good.html"].passed)

    def test_bad_page_fails_the_right_checks(self):
        t = self.by_name["bad.html"]
        self.assertEqual(self.statuses("bad.html"), {
            "title": "fail", "description": "fail", "image": "fail", "author": "fail",
            "date": "fail", "clean": "pass", "pdf": "n/a"})
        self.assertIn("only the site name", t.checks["title"].detail)
        self.assertIn("800 by 418", t.checks["image"].detail)
        self.assertIn("starts with @", t.checks["author"].detail)

    def test_shared_title_is_a_site_wide_default(self):
        self.assertEqual(self.statuses("dup1.html")["title"], "fail")
        self.assertEqual(self.statuses("dup2.html")["title"], "fail")
        self.assertIn("shared with another target", self.by_name["dup1.html"].checks["title"].detail)
        self.assertEqual(self.statuses("dup2.html")["description"], "pass")

    def test_unreachable_image_and_unclean_field(self):
        t = self.by_name["dup1.html"]
        self.assertEqual(t.checks["image"].status, "fail")
        self.assertIn("not reachable", t.checks["image"].detail)
        self.assertEqual(t.checks["clean"].status, "fail")
        self.assertEqual([h["rule"] for h in t.hits], ["no-leverage"])
        self.assertEqual(t.hits[0]["field"], "description")

    def test_pdf_properties_and_no_image(self):
        t = self.by_name["report.pdf"]
        s = self.statuses("report.pdf")
        self.assertEqual(s["pdf"], "pass")
        self.assertEqual(s["image"], "n/a")
        self.assertEqual(s["author"], "pass")
        self.assertEqual(s["date"], "fail")
        self.assertEqual(s["clean"], "fail")
        self.assertEqual({h["field"] for h in t.hits}, {"title", "description"})

    def test_unreachable_target_fails_everything_with_a_message(self):
        t = self.by_name["unreachable.html"]
        self.assertIsNotNone(t.error)
        self.assertTrue(all(c.status == "fail" for c in t.checks.values()))

    def test_exit_code_and_outputs(self):
        self.assertEqual(self.report.exit_code, 1)
        self.assertEqual(self.report.failed, 5)
        data = json.loads(self.report.to_json())
        self.assertEqual(data["checked"], 6)
        self.assertIn("does not change a card", data["note"])
        human = self.report.to_human()
        self.assertIn("PASS", human)
        self.assertIn("re-scrapes", human)
        page = self.out.read_text()
        self.assertIn("Why we changed our pricing", page)
        self.assertEqual(page.count('<section class="card'), 6)
        self.assertNotIn("—", page)

    def test_standard_validation(self):
        bad = self.dir / "bad-standard.yaml"
        bad.write_text("standard:\n  genre: client-facing\n  author_tag: author\n")
        with self.assertRaises(ConfigError):
            load_standard(bad)
        bad.write_text("standard:\n  genre: nowhere\n  author_tag: name=author\n")
        with self.assertRaises(ConfigError):
            run_preview(self.dir / "targets.txt", FIXTURES / "rules.yaml", bad, self.dir / "x.html")


class ImageSizeTest(unittest.TestCase):
    def test_png_gif_jpeg_webp(self):
        self.assertEqual(image_size(png(1200, 627)), ("png", 1200, 627))
        self.assertEqual(image_size(b"GIF89a" + struct.pack("<HH", 300, 200) + b"\x00" * 10), ("gif", 300, 200))
        jpeg = b"\xff\xd8" + b"\xff\xe0" + struct.pack(">H", 16) + b"JFIF\x00" + b"\x00" * 9
        jpeg += b"\xff\xc0" + struct.pack(">HBHH", 17, 8, 627, 1200) + b"\x00" * 10
        self.assertEqual(image_size(jpeg), ("jpeg", 1200, 627))
        vp8x = b"RIFF" + b"\x00\x00\x00\x00" + b"WEBP" + b"VP8X" + b"\x0a\x00\x00\x00" + b"\x00" * 4
        vp8x += (1199).to_bytes(3, "little") + (626).to_bytes(3, "little")
        self.assertEqual(image_size(vp8x), ("webp", 1200, 627))
        self.assertIsNone(image_size(b"not an image"))


if __name__ == "__main__":
    unittest.main()
