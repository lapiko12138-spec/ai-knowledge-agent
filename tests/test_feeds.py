import json
import unittest

from ai_knowledge_agent.feeds import (
    _normalize_papers,
    build_teaching_view,
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


if __name__ == "__main__":
    unittest.main()
