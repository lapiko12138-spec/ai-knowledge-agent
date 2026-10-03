import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from ai_knowledge_agent.core import KnowledgeStore
from ai_knowledge_agent.feishu import build_daily_card


def payload(title="KV Cache avoids repeated attention computation"):
    return {
        "source": {
            "title": "Test source",
            "type": "paper",
            "url": "https://example.test/source",
            "captured_at": "2026-10-03T09:00:00+08:00",
        },
        "assessment": {
            "classification": "A",
            "rationale": "Reusable mechanism.",
            "evidence_boundary": "Test fixture.",
        },
        "chunks": [
            {
                "title": title,
                "category": "AI Infra",
                "concept": "The cache reuses previously computed key/value states.",
                "problem": "Repeated prefix computation wastes work.",
                "mechanism": "Append only the new token states.",
                "why_it_matters": "Inference gets cheaper.",
                "example": "Token 101 reuses tokens 1 through 100.",
                "parents": ["Transformer Inference"],
                "connections": [{"target": "Attention", "type": "depends_on"}],
                "level": "L2",
                "keywords": ["KV Cache", "Inference"],
                "priority": {
                    "relevance": 5,
                    "novelty": 4,
                    "connection": 5,
                    "impact": 5,
                },
            }
        ],
        "open_questions": ["How does paged attention alter cache allocation?"],
    }


class KnowledgeStoreTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.vault = Path(self.temporary.name)
        self.store = KnowledgeStore(self.vault)

    def tearDown(self):
        self.temporary.cleanup()

    def test_init_and_ingest_create_linked_markdown(self):
        result = self.store.ingest(payload())
        self.assertEqual(len(result.created), 1)
        self.assertEqual(result.relationships_added, 2)

        index = json.loads(self.store.index_path.read_text(encoding="utf-8"))
        record = next(iter(index["chunks"].values()))
        chunk_path = self.store.chunks_dir / (record["title"] + ".md")
        content = chunk_path.read_text(encoding="utf-8")
        self.assertIn("[[Transformer Inference]]", content)
        self.assertIn("[[Attention]]", content)
        self.assertIn("[[2026-10-03 - Test source]]", content)

    def test_exact_duplicate_updates_existing_chunk(self):
        first = self.store.ingest(payload())
        changed = payload()
        changed["source"]["url"] = "https://example.test/second"
        changed["source"]["title"] = "Second source"
        changed["chunks"][0]["concept"] = (
            "A longer explanation that should replace the prior short explanation "
            "while preserving one stable knowledge chunk."
        )
        second = self.store.ingest(changed)

        self.assertEqual(len(first.created), 1)
        self.assertEqual(second.created, [])
        self.assertEqual(len(second.updated), 1)
        index = self.store.load_index()
        self.assertEqual(len(index["chunks"]), 1)
        record = next(iter(index["chunks"].values()))
        self.assertEqual(len(record["sources"]), 2)
        self.assertTrue(record["concept"].startswith("A longer explanation"))

    def test_similar_title_requires_review(self):
        self.store.ingest(payload())
        similar = payload("KV Cache avoids repeated attention computations")
        similar["source"]["url"] = "https://example.test/similar"
        result = self.store.ingest(similar)
        self.assertEqual(result.created, [])
        self.assertEqual(len(result.review_required), 1)

    def test_daily_weekly_and_card_generation(self):
        self.store.ingest(payload())
        daily = self.store.daily_digest(date(2026, 10, 3))
        weekly = self.store.weekly_review(date(2026, 10, 3))
        card = build_daily_card(self.store, date(2026, 10, 3))

        self.assertTrue(daily.exists())
        self.assertTrue(weekly.exists())
        self.assertEqual(card["schema"], "2.0")
        self.assertEqual(card["header"]["template"], "blue")
        self.assertEqual(len(card["body"]["elements"]), 4)


if __name__ == "__main__":
    unittest.main()
