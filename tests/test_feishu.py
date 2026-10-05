import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from ai_knowledge_agent.core import KnowledgeStore
from ai_knowledge_agent.feishu import build_learning_reminder_card, send_card


class FeishuReminderTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.store = KnowledgeStore(Path(self.temporary.name))
        self.store.initialize()

    def tearDown(self):
        self.temporary.cleanup()

    def test_learning_card_uses_localized_papers_and_unread_radar(self):
        intelligence = {
            "version": 1,
            "huggingface": {
                "papers": [
                    {
                        "id": "paper-1",
                        "title": "Original title",
                        "url": "https://huggingface.co/papers/paper-1",
                        "upvotes": 42,
                        "editorial_tier": "focus",
                        "localized": {
                            "title_zh": "中文论文标题",
                            "editor_note": "连接记忆与推理。",
                        },
                    }
                ]
            },
            "x_radar": {
                "window_end": "2026-10-03",
                "topics": [
                    {
                        "id": "topic-1",
                        "person_name": "研究者",
                        "viewpoint": "未读核心观点",
                        "url": "https://x.com/researcher/status/1",
                    },
                    {
                        "id": "topic-2",
                        "person": "另一位研究者",
                        "viewpoint": "已读观点",
                    },
                ]
            },
        }
        (self.store.system_dir / "daily-intelligence.json").write_text(
            json.dumps(intelligence, ensure_ascii=False), encoding="utf-8"
        )
        (self.store.system_dir / "radar-progress.json").write_text(
            json.dumps({"version": 1, "read_items": {"topic-2": {}}}),
            encoding="utf-8",
        )

        card = build_learning_reminder_card(
            self.store, date.fromisoformat("2026-10-03")
        )
        rendered = json.dumps(card, ensure_ascii=False)

        self.assertEqual(card["schema"], "2.0")
        self.assertIn("中文论文标题", rendered)
        self.assertIn("未读核心观点", rendered)
        self.assertNotIn("已读观点", rendered)
        self.assertNotIn("下一张知识卡", rendered)
        self.assertIn("更新至 2026-10-03", rendered)
        self.assertIn("https://huggingface.co/papers/paper-1", rendered)
        self.assertIn("https://x.com/researcher/status/1", rendered)

    @patch("ai_knowledge_agent.feishu._lark_cli_path", return_value="/tmp/lark-cli")
    @patch("ai_knowledge_agent.feishu.subprocess.run")
    def test_send_card_uses_idempotency_key(self, run, cli_path):
        run.return_value.returncode = 0
        run.return_value.stdout = '{"ok":true,"data":{"message_id":"om_test"}}'
        run.return_value.stderr = ""

        result = send_card(
            {"schema": "2.0"},
            user_id="ou_test",
            confirm_send=True,
            idempotency_key="ai-learning-2026-10-03",
        )

        command = run.call_args.args[0]
        self.assertEqual(command[0], "/tmp/lark-cli")
        self.assertIn("ai-learning-2026-10-03", command)
        self.assertTrue(result["ok"])


if __name__ == "__main__":
    unittest.main()
