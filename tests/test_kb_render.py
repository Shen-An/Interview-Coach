import unittest

from backend.kb import normalize_rendered_text, render_body


class WikiRenderTests(unittest.TestCase):
    def test_normalize_repairs_numeric_ranges_without_touching_urls(self):
        text = "1.5×(1.1 1.35) ≈ 1.65 2.0 倍；见 https://example.com/a?id=1 2"
        normalized = normalize_rendered_text(text)
        self.assertIn("1.5×(1.1~1.35) ≈ 1.65~2.0 倍", normalized)
        self.assertIn("https://example.com/a?id=1 2", normalized)

    def test_render_omits_empty_optional_fields(self):
        artifact = {
            "topic": [],
            "scenarios": [{"title": "Fallback", "background": "", "scale": "", "focus": ""}],
            "events": [{"event": "Event", "ask": ""}],
            "coding": [{"title": "Code", "difficulty": "", "focus": ""}],
        }
        body = render_body(artifact)
        self.assertIn("- Fallback", body)
        self.assertNotIn("背景：）", body)
        self.assertIn("- Event", body)
        self.assertIn("- Code", body)


if __name__ == "__main__":
    unittest.main()
