"""Serve mode: routes, errors, token, HTML input, allow-list by document id."""
from __future__ import annotations

import json
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from housestyle.errors import ConfigError
from housestyle.serve import build_server, check_document, load

FIXTURES = Path(__file__).resolve().parent.parent / "housestyle" / "selftest" / "fixtures"


class ServeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.loaded = load(FIXTURES / "rules.yaml", FIXTURES / "genres.yaml",
                          FIXTURES / "allow.yaml", root=FIXTURES, token="s3cret")
        cls.server = build_server(cls.loaded, "127.0.0.1", 0)
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def call(self, method, path, body=None, token="s3cret", raw=None):
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        req = urllib.request.Request(self.base + path, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read())

    def test_token_required_on_every_request(self):
        self.assertEqual(self.call("GET", "/health", token=None)[0], 401)
        self.assertEqual(self.call("GET", "/health", token="wrong")[0], 401)
        status, body = self.call("POST", "/check", {"id": "x"}, token=None)
        self.assertEqual(status, 401)
        self.assertIn("error", body)
        self.assertEqual(self.call("GET", "/health")[0], 200)

    def test_routes_and_methods(self):
        self.assertEqual(self.call("GET", "/nope")[0], 404)
        self.assertEqual(self.call("POST", "/health", {})[0], 405)
        self.assertEqual(self.call("GET", "/check")[0], 405)
        self.assertEqual(self.call("PUT", "/check", {})[0], 405)

    def test_bad_bodies_are_400_with_a_message(self):
        status, body = self.call("POST", "/check", raw=b"{not json")
        self.assertEqual(status, 400)
        self.assertIn("not valid JSON", body["error"])
        self.assertEqual(self.call("POST", "/check", [])[0], 400)
        self.assertEqual(self.call("POST", "/check", {"id": "d", "genre": "client-facing", "format": "text"})[0], 400)
        status, body = self.call("POST", "/check", {"id": "d", "genre": "nowhere", "format": "text", "text": "x"})
        self.assertEqual(status, 400)
        self.assertIn("unknown genre", body["error"])
        status, body = self.call("POST", "/check", {"id": "d", "genre": "client-facing", "format": "pdf", "text": "x"})
        self.assertEqual(status, 400)
        status, body = self.call("POST", "/check", {"id": "d", "genre": "client-facing", "format": "text",
                                                    "text": "x", "overrides": [{"rule": "no-such", "match": "x"}]})
        self.assertEqual(status, 400)
        self.assertIn("unknown rule id", body["error"])
        status, body = self.call("POST", "/check", {"id": "d", "genre": "client-facing", "format": "text",
                                                    "text": "x", "extra": 1})
        self.assertEqual(status, 400)

    def test_html_is_read_as_text_nodes_with_source_positions(self):
        html = '<p class="key">We <em>leverage</em> it.</p>\n<style>.key{}</style>'
        status, body = self.call("POST", "/check", {"id": "d", "genre": "client-facing",
                                                    "format": "html", "text": html})
        self.assertEqual(status, 200)
        self.assertEqual([(f["rule"], f["match"], f["line"], f["col"]) for f in body["findings"]],
                         [("no-leverage", "leverage", 1, 23)])

    def test_verdicts_and_override_does_not_count(self):
        status, body = self.call("POST", "/check", {"id": "d", "genre": "client-facing", "format": "text",
                                                    "text": "Join the workshops."})
        self.assertEqual(body["verdict"], "warn")
        status, body = self.call("POST", "/check", {"id": "d", "genre": "client-facing", "format": "text",
                                                    "text": "Plain and clean."})
        self.assertEqual((body["verdict"], body["findings"]), ("pass", []))
        doc = {"id": "d", "genre": "client-facing", "format": "text", "text": "We leverage it. We leverage it."}
        status, body = self.call("POST", "/check", {**doc, "overrides": [{"rule": "no-leverage", "match": "leverage"}]})
        self.assertEqual(body["verdict"], "pass")
        self.assertEqual([f["severity"] for f in body["findings"]], ["overridden", "overridden"])
        # An override is exact on the matched text: "Leverage" is not "leverage".
        status, body = self.call("POST", "/check", {**doc, "text": "We Leverage it.",
                                                    "overrides": [{"rule": "no-leverage", "match": "leverage"}]})
        self.assertEqual(body["verdict"], "fail")

    def test_genre_and_allow_list_apply_by_document_id(self):
        # method genre: no-the-workshop does not apply.
        status, body = self.call("POST", "/check", {"id": "d", "genre": "method", "format": "text",
                                                    "text": "The workshop."})
        self.assertEqual(body["verdict"], "pass")
        # A document id equal to an allow-listed path is exempt from its rules.
        text = "Do not write leverage."
        status, plain = self.call("POST", "/check", {"id": "other.md", "genre": "internal", "format": "text", "text": text})
        status, allowed = self.call("POST", "/check", {"id": "docs/internal/banned-terms.md", "genre": "internal",
                                                       "format": "text", "text": text})
        self.assertEqual(plain["verdict"], "fail")
        self.assertEqual(allowed["verdict"], "pass")

    def test_malformed_rule_set_refuses_to_start(self):
        with self.assertRaises(ConfigError):
            load(FIXTURES / "rules.yaml", FIXTURES / "genres-missing.yaml", None, root=FIXTURES)

    def test_check_document_is_pure(self):
        payload = {"id": "d", "genre": "client-facing", "format": "text", "text": "keys"}
        self.assertEqual(check_document(self.loaded, payload), check_document(self.loaded, payload))


if __name__ == "__main__":
    unittest.main()
