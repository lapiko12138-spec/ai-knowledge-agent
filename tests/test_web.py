import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ai_knowledge_agent.core import KnowledgeStore
from ai_knowledge_agent.web import (
    build_state,
    load_progress,
    load_radar_progress,
    save_progress,
    save_radar_read,
    sync_user_state,
)


class KnowledgeWebTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.store = KnowledgeStore(Path(self.temporary.name))
        self.store.initialize()

    def tearDown(self):
        self.temporary.cleanup()

    def test_empty_state_has_expected_shape(self):
        state = build_state(self.store, include_intelligence=False)
        self.assertEqual(state["chunks"], [])
        self.assertEqual(state["stats"]["chunks"], 0)
        self.assertIn("daily_reports", state)
        self.assertIn("weekly_reports", state)

    def test_learning_progress_is_persisted(self):
        index = self.store.load_index()
        index["chunks"]["kc-test"] = {
            "id": "kc-test",
            "title": "Test knowledge",
            "canonical_key": "testknowledge",
            "aliases": [],
            "category": "LLM",
            "concept": "Concept",
            "problem": "Problem",
            "mechanism": "Mechanism",
            "why_it_matters": "Reason",
            "example": "Example",
            "connections": [],
            "parents": [],
            "level": "L1",
            "keywords": ["test"],
            "classification": "A",
            "priority": {
                "relevance": 1,
                "novelty": 1,
                "connection": 1,
                "impact": 1,
            },
            "priority_score": 1,
            "sources": [],
            "relationship_refs": [],
            "created_at": "2026-10-03T00:00:00+08:00",
            "updated_at": "2026-10-03T00:00:00+08:00",
        }
        index["canonical"]["testknowledge"] = "kc-test"
        self.store.index_path.write_text(
            __import__("json").dumps(index, ensure_ascii=False),
            encoding="utf-8",
        )

        saved = save_progress(self.store, "kc-test", "learning", 4, "My note")
        self.assertEqual(saved["status"], "learning")
        self.assertEqual(saved["confidence"], 4)
        self.assertEqual(load_progress(self.store)["chunks"]["kc-test"]["notes"], "My note")
        self.assertEqual(
            build_state(self.store, include_intelligence=False)["chunks"][0]["progress"]["confidence"],
            4,
        )

    def test_radar_item_can_be_marked_read(self):
        cache = {
            "version": 1,
            "huggingface": {"papers": [], "daily_date": ""},
            "x_radar": {},
            "editorial_model": {},
        }
        (self.store.system_dir / "daily-intelligence.json").write_text(
            __import__("json").dumps(cache),
            encoding="utf-8",
        )
        result = save_radar_read(
            self.store, "x-2105909609487872075", True
        )
        self.assertTrue(result["is_read"])
        self.assertIn(
            "x-2105909609487872075",
            load_radar_progress(self.store)["read_items"],
        )

    def test_user_state_sync_reports_github_result(self):
        with patch(
            "ai_knowledge_agent.web.sync_github",
            return_value={"status": "pushed", "commit": "abc123"},
        ):
            result = sync_user_state(self.store)
        self.assertEqual(result["status"], "pushed")

    def test_user_state_sync_keeps_local_save_on_push_failure(self):
        with patch(
            "ai_knowledge_agent.web.sync_github",
            side_effect=RuntimeError("push failed"),
        ):
            result = sync_user_state(self.store)
        self.assertEqual(result["status"], "failed")
        self.assertIn("push failed", result["message"])


if __name__ == "__main__":
    unittest.main()
