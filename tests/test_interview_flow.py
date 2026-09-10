import unittest
from unittest.mock import patch

from backend import prompts, retrieval


class InterviewFlowTests(unittest.TestCase):
    def test_first_round_starts_with_concepts_not_projects(self):
        self.assertIn("概念热身", prompts.stage_hint("一面", 2))
        self.assertIn("概念题", prompts.stage_hint("一面", 2))
        self.assertIn("禁止项目深挖", prompts.stage_hint("一面", 2))
        self.assertIn("概念题", prompts.stage_hint("一面", 3))

    def test_first_round_has_two_scenario_windows(self):
        self.assertIn("场景题一", prompts.stage_hint("一面", 4))
        self.assertIn("背景", prompts.stage_hint("一面", 4))
        self.assertIn("场景题追问", prompts.stage_hint("一面", 5))
        self.assertEqual(prompts.interview_material_kinds("一面", 4), ("scenarios",))
        self.assertEqual(prompts.interview_material_kinds("一面", 15), ("scenarios",))

    def test_project_is_delayed_and_then_rotates(self):
        resume = """项目经历\n平台A — Agent 检索 2025.01-2025.03\n平台B — 工具调用 2025.04-2025.06"""
        before = prompts.project_rotation_hint("一面", 2, resume)
        current = prompts.project_rotation_hint("一面", 7, resume)
        next_project = prompts.project_rotation_hint("一面", 10, resume)
        self.assertIn("项目延后", before)
        self.assertIn("平台A", current)
        self.assertIn("平台B", next_project)

    def test_coding_and_close_are_explicit(self):
        self.assertIn("手撕代码", prompts.stage_hint("一面", 17))
        self.assertEqual(prompts.interview_material_kinds("一面", 17), ("coding",))
        self.assertIn("反问收尾", prompts.stage_hint("一面", 19))
        self.assertEqual(prompts.interview_material_kinds("一面", 19), ())

    def test_stage_hint_is_safe_after_planned_close(self):
        hint = prompts.stage_hint("一面", 20)
        self.assertIn("反问收尾", hint)
        self.assertIn("不要再开启新题", hint)

    def test_turn_material_filter_respects_question_type(self):
        items = [
            {"id": "q", "kind": "questions", "terms": {"redis", "cluster"}, "head": {"redis"},
             "topic_terms": set(), "company": "", "freq": "", "diff": "中等",
             "layer": "", "day": "", "line": "concept", "related": []},
            {"id": "s", "kind": "scenarios", "terms": {"redis", "cluster"}, "head": {"cluster"},
             "topic_terms": set(), "company": "", "freq": "", "diff": "中等",
             "layer": "", "day": "", "line": "scenario", "related": []},
        ]
        store = {
            "items": items, "idf": {"redis": 2.0, "cluster": 2.0}, "df": {"redis": 1, "cluster": 1},
            "df_cut": 3, "newest": "", "by_id": {item["id"]: item for item in items},
        }
        self.assertEqual([item["kind"] for item in retrieval.select_turn(store, recent="Redis cluster", kinds=("scenarios",))], ["scenarios"])
        self.assertEqual(retrieval.select_turn(store, recent="Redis cluster", kinds=()), [])
        self.assertEqual(len(retrieval.select_turn(store, recent="Redis cluster", kinds=None)), 2)

    def test_selection_cache_uses_content_fingerprint(self):
        stores = [
            {"items": [{"id": "old"}], "version": ("old",), "newest": "2026-09-01", "total": 1},
            {"items": [{"id": "new"}], "version": ("new",), "newest": "2026-09-01", "total": 1},
        ]

        def select(store, **_kwargs):
            return {"questions": [{"id": store["items"][0]["id"]}]}

        prompts._sel_cache.clear()
        try:
            with patch.object(prompts.retrieval, "load", side_effect=stores), patch.object(
                prompts.retrieval, "select", side_effect=select
            ) as mocked_select:
                first = prompts.select_wiki("一面", "随机", "resume", "应届校招")[1]
                second = prompts.select_wiki("一面", "随机", "resume", "应届校招")[1]
            self.assertEqual(first["questions"][0]["id"], "old")
            self.assertEqual(second["questions"][0]["id"], "new")
            self.assertEqual(mocked_select.call_count, 2)
        finally:
            prompts._sel_cache.clear()

    def test_qa_and_interviewer_share_untrusted_wiki_rules(self):
        self.assertIn(prompts.UNTRUSTED_WIKI_RULES, prompts.build_qa_system("untrusted"))
        store = {"bank_total": 1, "intel_total": 1}
        with patch.object(prompts, "select_wiki", return_value=(store, {})), patch.object(
            prompts.retrieval, "render_bank", return_value="bank"
        ), patch.object(prompts.retrieval, "render_block", return_value="intel"), patch.object(
            prompts, "_read", return_value="persona"
        ):
            system = prompts.build_interviewer_system("一面", "随机")
        self.assertIn(prompts.UNTRUSTED_WIKI_RULES, system)


if __name__ == "__main__":
    unittest.main()
