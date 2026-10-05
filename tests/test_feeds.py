import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ai_knowledge_agent.core import KnowledgeStore
from ai_knowledge_agent.feeds import (
    _normalize_papers,
    build_teaching_view,
    ensure_paper_translations,
    fetch_x_radar,
    parse_huggingface_daily_html,
)


class DailyFeedsTest(unittest.TestCase):
    def test_parse_huggingface_embedded_data(self):
        items = [
            {
                "paper": {
                    "id": "1234.5678",
                    "title": "Agent Memory",
                    "summary": "Agents need memory. We introduce a new memory system.",
                    "upvotes": 42,
                    "submittedOnDailyAt": "2026-10-03T00:00:00.000Z",
                    "authors": [{"name": "A. Researcher"}],
                },
                "numComments": 3,
            }
        ]
        html = (
            "<html><script>window.__data__={"
            + '"dailyPapers":'
            + json.dumps(items)
            + "}</script></html>"
        )
        parsed = parse_huggingface_daily_html(html)
        self.assertEqual(parsed[0]["paper"]["id"], "1234.5678")

        papers = _normalize_papers(parsed)
        self.assertEqual(papers[0]["rank"], 1)
        self.assertEqual(papers[0]["editorial_tier"], "focus")
        self.assertIn("Memory", papers[0]["teaching"]["concepts"])

    def test_teaching_view_separates_method_and_evidence(self):
        summary = (
            "Long tasks are difficult for current agents. "
            "We introduce a belief-state memory architecture. "
            "The model outperforms baselines on eight benchmarks."
        )
        view = build_teaching_view("Belief-State Agent Memory", summary)
        self.assertIn("difficult", view["research_question"])
        self.assertIn("introduce", view["new_method"])
        self.assertIn("outperforms", view["evidence"])

    def test_x_radar_uses_official_api_when_token_is_available(self):
        def api_response(path, bearer_token, params=None, timeout=20):
            if path.startswith("users/by/username/"):
                handle = path.rsplit("/", 1)[-1]
                return {"data": {"id": "id-" + handle, "name": handle.title()}}
            handle = path.split("/", 2)[1].removeprefix("id-")
            return {
                "data": [
                    {
                        "id": "post-" + handle,
                        "text": "A current public viewpoint.",
                        "created_at": "2026-10-05T01:00:00Z",
                        "lang": "en",
                        "public_metrics": {"like_count": 2},
                    }
                ]
            }

        with patch(
            "ai_knowledge_agent.feeds._x_api_json",
            side_effect=api_response,
        ):
            radar = fetch_x_radar(bearer_token="test-token")

        self.assertEqual(radar["status"], "official_api")
        self.assertEqual(len(radar["topics"]), 6)
        self.assertIn("x.com/karpathy/status/", radar["topics"][0]["url"])

    def test_paper_translation_is_cached_with_title_and_summary(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = KnowledgeStore(Path(temporary))
            store.initialize()
            papers = [
                {
                    "id": "paper-1",
                    "title": "English title",
                    "summary": "English abstract.",
                    "localized": {"status": "pending"},
                }
            ]
            with patch(
                "ai_knowledge_agent.feeds._translate_to_zh",
                side_effect=["中文标题", "中文摘要。"],
            ):
                ensure_paper_translations(store, papers)

            self.assertEqual(papers[0]["localized"]["title_zh"], "中文标题")
            self.assertEqual(papers[0]["localized"]["summary_zh"], "中文摘要。")
            self.assertEqual(
                papers[0]["localized"]["status"], "machine_translated"
            )

            cached_papers = [
                {
                    "id": "paper-1",
                    "title": "English title",
                    "summary": "English abstract.",
                    "localized": {"status": "pending"},
                }
            ]
            with patch(
                "ai_knowledge_agent.feeds._translate_to_zh"
            ) as translate:
                ensure_paper_translations(store, cached_papers)
            translate.assert_not_called()
            self.assertEqual(
                cached_papers[0]["localized"]["summary_zh"], "中文摘要。"
            )


if __name__ == "__main__":
    unittest.main()
