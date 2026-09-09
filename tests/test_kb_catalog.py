import unittest

from backend import retrieval


class WikiCatalogTests(unittest.TestCase):
    def setUp(self):
        self.items = [
            {
                "id": "intel#questions#0", "space": "intel", "kind": "questions",
                "layer": "", "day": "2026-09-09", "line": "Redis cluster failover",
                "company": "ByteDance", "freq": "high", "hot": False,
                "source": "daily research", "source_urls": [{"url": "https://example.com/a", "title": "A"}],
            },
            {
                "id": "intel#events#0", "space": "intel", "kind": "events",
                "layer": "", "day": "2026-09-02", "line": "Agent platform event",
                "company": "Tencent", "freq": "", "hot": False,
                "source": "daily research", "source_urls": [],
            },
            {
                "id": "bank#questions#0", "space": "bank", "kind": "questions",
                "layer": "1", "day": "", "line": "Redis basics",
                "company": "ByteDance", "freq": "high", "hot": True,
                "source": "QUESTION-BANK.md", "source_urls": [],
            },
        ]
        self.store = {"items": self.items}

    def test_catalog_filters_and_keeps_provenance(self):
        result = retrieval.catalog(self.store, query="redis", company="byte",
                                   ref_day="2026-09-09", page_size=10)
        self.assertEqual(result["total"], 2)
        self.assertEqual(result["items"][0]["frequency"], "high")
        self.assertEqual(result["items"][0]["source_urls"][0]["url"], "https://example.com/a")
        self.assertEqual(result["items"][1]["page"], "")

    def test_recent_filter_excludes_undated_bank_entries(self):
        result = retrieval.catalog(self.store, days=7, ref_day="2026-09-09")
        self.assertEqual([item["id"] for item in result["items"]], ["intel#questions#0", "intel#events#0"])

    def test_kind_and_pagination_are_stable(self):
        result = retrieval.catalog(self.store, kind="questions", page=2, page_size=1,
                                   ref_day="2026-09-09")
        self.assertEqual(result["total"], 2)
        self.assertEqual(result["pages"], 2)
        self.assertEqual(result["items"][0]["id"], "bank#questions#0")
        self.assertEqual(result["stats"]["kinds"]["events"], 1)


if __name__ == "__main__":
    unittest.main()
