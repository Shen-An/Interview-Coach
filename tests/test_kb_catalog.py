import unittest

from backend import retrieval


class WikiCatalogTests(unittest.TestCase):
    def setUp(self):
        self.items = [
            {
                "id": "intel#questions#0", "space": "intel", "kind": "questions",
                "layer": "", "day": "2026-09-09", "line": "Redis cluster failover",
                "company": "ByteDance", "platform": "Nowcoder", "topic": "Redis reliability",
                "freq": "high", "hot": False, "source": "daily research",
                "source_urls": [
                    {"url": "https://example.com/a", "title": "A"},
                    {"url": "javascript:alert(1)", "title": "unsafe"},
                    {"url": "file:///tmp/local", "title": "local"},
                ],
            },
            {
                "id": "intel#events#0", "space": "intel", "kind": "events",
                "layer": "", "day": "2026-09-02", "line": "Agent platform event",
                "company": "Tencent", "platform": "Zhihu", "topic": "Agent platform",
                "freq": "", "hot": False,
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
    def test_catalog_filters_unsafe_urls_and_marks_artifact_scope(self):
        result = retrieval.catalog(self.store, query="Redis reliability")
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["items"][0]["source_urls"], [
            {"url": "https://example.com/a", "title": "A"}
        ])
        self.assertEqual(result["items"][0]["source_scope"], "artifact")

    def test_platform_is_searchable_and_part_of_company_facets(self):
        by_query = retrieval.catalog(self.store, query="zhihu")
        by_company = retrieval.catalog(self.store, company="nowcoder")
        self.assertEqual([item["id"] for item in by_query["items"]], ["intel#events#0"])
        self.assertEqual([item["id"] for item in by_company["items"]], ["intel#questions#0"])
        self.assertIn("Nowcoder", by_query["facets"]["companies"])
        self.assertEqual(by_query["facets"]["platforms"], ["Nowcoder", "Zhihu"])
        self.assertEqual(by_query["facets"]["spaces"], ["bank", "intel"])

    def test_catalog_paginates_more_than_500_items(self):
        items = [{
            "id": f"bank#questions#{i:03d}", "space": "bank", "kind": "questions",
            "layer": "1", "day": "", "line": f"Question {i}", "company": "",
            "platform": "", "topic": "pagination", "freq": "", "hot": False,
            "source": "QUESTION-BANK.md", "source_urls": [],
        } for i in range(501)]
        result = retrieval.catalog({"items": items}, query="pagination", page=11, page_size=50)
        self.assertEqual(result["total"], 501)
        self.assertEqual(result["pages"], 11)
        self.assertEqual(len(result["items"]), 1)


if __name__ == "__main__":
    unittest.main()
