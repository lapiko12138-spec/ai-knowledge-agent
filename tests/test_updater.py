import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from ai_knowledge_agent.core import KnowledgeStore
from ai_knowledge_agent.updater import (
    load_update_status,
    next_scheduled_run,
    should_catch_up,
    update_daily,
)


class DailyUpdaterTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.store = KnowledgeStore(Path(self.temporary.name))
        self.store.initialize()

    def tearDown(self):
        self.temporary.cleanup()

    def test_next_run_rolls_to_tomorrow_after_schedule(self):
        current = datetime.fromisoformat("2026-10-03T09:30:00+08:00")
        next_run = next_scheduled_run(current, hour=8, minute=0)
        self.assertEqual(next_run.isoformat(), "2026-10-04T08:00:00+08:00")

    def test_successful_update_writes_status_and_cache(self):
        payload = {
            "source": "https://huggingface.co/papers",
            "daily_date": "2026-10-03",
            "fetched_at": "2026-10-03T08:00:00+00:00",
            "papers": [
                {
                    "id": "test-paper",
                    "localized": {"title_zh": "测试论文"},
                }
            ],
        }
        with patch(
            "ai_knowledge_agent.updater.fetch_huggingface_daily",
            return_value=payload,
        ), patch(
            "ai_knowledge_agent.updater.sync_github",
            return_value={"status": "unchanged"},
        ):
            result = update_daily(self.store)

        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "success")
        self.assertEqual(
            load_update_status(self.store)["sources"]["huggingface"][
                "paper_count"
            ],
            1,
        )
        self.assertFalse(should_catch_up(self.store))


if __name__ == "__main__":
    unittest.main()
