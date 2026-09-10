import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend import app as app_module


class _FakeLlm:
    def ready(self):
        return True, "ready"


class ApiBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app_module.app, base_url="http://127.0.0.1:47821")
        self.header = {"X-Interview-Coach": "1"}

    def test_rejects_non_loopback_host(self):
        response = self.client.get("/api/config", headers={"host": "attacker.example"})
        self.assertEqual(response.status_code, 400)

    def test_rejects_cross_site_and_mismatched_origin(self):
        response = self.client.get("/api/config", headers={"sec-fetch-site": "cross-site"})
        self.assertEqual(response.status_code, 403)
        response = self.client.get("/api/config", headers={"origin": "http://127.0.0.1:9999"})
        self.assertEqual(response.status_code, 403)

    def test_settings_requires_marker_and_never_returns_secrets(self):
        self.assertEqual(self.client.get("/api/settings").status_code, 403)
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "top-secret"}, clear=False):
            response = self.client.get("/api/settings", headers=self.header)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["ANTHROPIC_API_KEY"], "")
        self.assertTrue(data["configured_secrets"]["ANTHROPIC_API_KEY"])
        self.assertNotIn("top-secret", response.text)

    def test_mutating_request_requires_marker(self):
        response = self.client.post("/api/settings", json={"values": {}})
        self.assertEqual(response.status_code, 403)

    def test_blank_preserves_secret_and_explicit_clear_removes_it(self):
        original_path = app_module.ENV_PATH
        original_llm = app_module.llm
        try:
            from tempfile import TemporaryDirectory
            from pathlib import Path
            with TemporaryDirectory() as tmp:
                app_module.ENV_PATH = Path(tmp) / ".env"
                app_module.llm = _FakeLlm()
                with patch.object(app_module, "LLMClient", _FakeLlm), patch.dict(
                    os.environ, {"ANTHROPIC_API_KEY": "keep-me"}, clear=False
                ):
                    response = self.client.post("/api/settings", headers=self.header, json={
                        "values": {"ANTHROPIC_API_KEY": ""}, "clear_secrets": []
                    })
                    self.assertTrue(response.json()["configured_secrets"]["ANTHROPIC_API_KEY"])
                    self.assertIn("ANTHROPIC_API_KEY=keep-me", app_module.ENV_PATH.read_text(encoding="utf-8"))
                    response = self.client.post("/api/settings", headers=self.header, json={
                        "values": {}, "clear_secrets": ["ANTHROPIC_API_KEY"]
                    })
                    self.assertFalse(response.json()["configured_secrets"]["ANTHROPIC_API_KEY"])
                    self.assertIn("ANTHROPIC_API_KEY=\n", app_module.ENV_PATH.read_text(encoding="utf-8"))
        finally:
            app_module.ENV_PATH = original_path
            app_module.llm = original_llm


if __name__ == "__main__":
    unittest.main()
