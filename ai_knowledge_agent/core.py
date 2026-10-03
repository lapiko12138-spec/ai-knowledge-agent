from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


CATEGORIES = [
    "Foundation",
    "Machine Learning",
    "Deep Learning",
    "Transformer",
    "LLM",
    "Agent",
    "AI Infra",
    "Multimodal",
    "AI Product",
    "AI Application",
    "AI Business",
    "AI Safety",
    "Robotics",
    "Frontier",
]

LEVELS = {"L1", "L2", "L3", "L4"}
SKIP_CLASSIFICATIONS = {"G"}


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def canonicalize(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).strip().casefold()
    return re.sub(r"[\W_]+", "", value, flags=re.UNICODE)


def safe_name(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).strip()
    value = re.sub(r'[\\/:*?"<>|#^[\]]+', "-", value)
    value = re.sub(r"\s+", " ", value).strip(" .")
    return value[:100] or "Untitled"


def json_yaml(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def wikilink(title: str) -> str:
    return "[[" + safe_name(title) + "]]"


def score_priority(priority: Dict[str, Any]) -> float:
    values = []
    for key in ("relevance", "novelty", "connection", "impact"):
        raw = priority.get(key, 0)
        try:
            value = float(raw)
        except (TypeError, ValueError):
            value = 0.0
        values.append(max(0.0, min(5.0, value)))
    product = 1.0
    for value in values:
        product *= value
    return round(product, 2)


def _atomic_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content.rstrip() + "\n", encoding="utf-8")
    temporary.replace(path)


@dataclass
class IngestResult:
    created: List[str]
    updated: List[str]
    skipped: List[str]
    review_required: List[Dict[str, Any]]
    relationships_added: int
    source_note: str

    def as_dict(self) -> Dict[str, Any]:
        return {
            "created": self.created,
            "updated": self.updated,
            "skipped": self.skipped,
            "review_required": self.review_required,
            "relationships_added": self.relationships_added,
            "source_note": self.source_note,
        }


class KnowledgeStore:
    def __init__(self, vault: Path) -> None:
        self.vault = vault.expanduser().resolve()
        self.root = self.vault / "AI Knowledge"
        self.chunks_dir = self.root / "20 Knowledge Chunks"
        self.sources_dir = self.root / "10 Sources"
        self.maps_dir = self.root / "30 Knowledge Maps"
        self.daily_dir = self.root / "40 Daily Digests"
        self.weekly_dir = self.root / "50 Weekly Reviews"
        self.inbox_dir = self.root / "00 Inbox"
        self.system_dir = self.root / "99 System"
        self.index_path = self.system_dir / "index.json"

    def initialize(self) -> None:
        for path in (
            self.inbox_dir,
            self.sources_dir,
            self.chunks_dir,
            self.maps_dir,
            self.daily_dir,
            self.weekly_dir,
            self.system_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)
        if not self.index_path.exists():
            _atomic_json(
                self.index_path,
                {
                    "version": 1,
                    "chunks": {},
                    "canonical": {},
                    "sources": {},
                    "relationships": [],
                    "open_questions": [],
                },
            )
        self._write_home()
        self._write_data_dictionary()
        self.rebuild_maps()

    def load_index(self) -> Dict[str, Any]:
        self.initialize()
        return json.loads(self.index_path.read_text(encoding="utf-8"))

    def ingest(
        self, payload: Dict[str, Any], allow_similar: bool = False
    ) -> IngestResult:
        index = self.load_index()
        source = self._normalize_source(payload.get("source", {}))
        source_id = self._source_id(source)
        source_path = self.sources_dir / (
            source["captured_at"][:10] + " - " + safe_name(source["title"]) + ".md"
        )

        created: List[str] = []
        updated: List[str] = []
        skipped: List[str] = []
        reviews: List[Dict[str, Any]] = []
        relationships_added = 0
        accepted_ids: List[str] = []

        index["sources"][source_id] = {
            **source,
            "path": str(source_path.relative_to(self.vault)),
            "chunks": [],
            "assessment": payload.get("assessment", {}),
        }

        for raw_chunk in payload.get("chunks", []):
            chunk = self._normalize_chunk(raw_chunk)
            if chunk["classification"] in SKIP_CLASSIFICATIONS:
                skipped.append(chunk["title"])
                continue

            canonical_key = chunk["canonical_key"]
            existing_id = index["canonical"].get(canonical_key)
            if not existing_id:
                existing_id = self._alias_match(index, chunk["title"])

            if not existing_id and not allow_similar:
                candidates = self._similar_candidates(index, chunk["title"])
                if candidates:
                    review = {
                        "incoming": chunk["title"],
                        "canonical_key": canonical_key,
                        "candidates": candidates,
                        "source_id": source_id,
                        "date": source["captured_at"][:10],
                    }
                    reviews.append(review)
                    continue

            if existing_id:
                record = index["chunks"][existing_id]
                self._merge_record(record, chunk, source_id)
                updated.append(record["title"])
                accepted_ids.append(existing_id)
                self._write_chunk(record, index)
            else:
                chunk_id = self._chunk_id(canonical_key)
                record = self._new_record(chunk_id, chunk, source_id)
                index["chunks"][chunk_id] = record
                index["canonical"][canonical_key] = chunk_id
                created.append(record["title"])
                accepted_ids.append(chunk_id)

            record = index["chunks"][accepted_ids[-1]]
            relationships_added += self._merge_relationships(
                index, record, chunk, source["captured_at"][:10]
            )
            self._write_chunk(record, index)

        questions = payload.get("open_questions", [])
        for question in questions:
            entry = {
                "question": str(question).strip(),
                "source_id": source_id,
                "date": source["captured_at"][:10],
                "status": "open",
            }
            if entry["question"] and entry not in index["open_questions"]:
                index["open_questions"].append(entry)

        index["sources"][source_id]["chunks"] = accepted_ids
        self._resolve_relationship_targets(index)
        for chunk_id in accepted_ids:
            self._write_chunk(index["chunks"][chunk_id], index)
        _atomic_json(self.index_path, index)
        self._write_source(source_path, source_id, source, payload, accepted_ids, index)
        self.rebuild_maps(index)

        return IngestResult(
            created=created,
            updated=updated,
            skipped=skipped,
            review_required=reviews,
            relationships_added=relationships_added,
            source_note=str(source_path),
        )

    def search(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        index = self.load_index()
        normalized = canonicalize(query)
        scored: List[Tuple[float, Dict[str, Any]]] = []
        for record in index["chunks"].values():
            haystack = " ".join(
                [
                    record["title"],
                    record.get("concept", ""),
                    " ".join(record.get("keywords", [])),
                    " ".join(record.get("aliases", [])),
                ]
            )
            compact = canonicalize(haystack)
            ratio = SequenceMatcher(None, normalized, canonicalize(record["title"])).ratio()
            score = ratio + (1.0 if normalized and normalized in compact else 0.0)
            if score >= 0.35:
                scored.append(
                    (
                        score,
                        {
                            "id": record["id"],
                            "title": record["title"],
                            "category": record["category"],
                            "level": record["level"],
                            "priority": record["priority_score"],
                            "path": str(self._chunk_path(record)),
                        },
                    )
                )
        return [item for _, item in sorted(scored, reverse=True)[:limit]]

    def daily_digest(self, target: date) -> Path:
        index = self.load_index()
        target_s = target.isoformat()
        new_records = [
            item
            for item in index["chunks"].values()
            if item["created_at"][:10] == target_s
        ]
        updated_records = [
            item
            for item in index["chunks"].values()
            if item["updated_at"][:10] == target_s
            and item["created_at"][:10] != target_s
        ]
        sources = [
            (source_id, item)
            for source_id, item in index["sources"].items()
            if item["captured_at"][:10] == target_s
        ]
        relationships = [
            rel for rel in index["relationships"] if rel["date"] == target_s
        ]
        questions = [
            item
            for item in index["open_questions"]
            if item["date"] == target_s and item["status"] == "open"
        ]
        ranked = sorted(
            new_records + updated_records,
            key=lambda item: item.get("priority_score", 0),
            reverse=True,
        )

        lines = [
            "---",
            "type: ai-daily-digest",
            "date: " + target_s,
            "new_chunks: " + str(len(new_records)),
            "updated_chunks: " + str(len(updated_records)),
            "relationships_added: " + str(len(relationships)),
            "---",
            "",
            "# AI Daily Digest - " + target_s,
            "",
            "## 1. Today",
            "",
        ]
        if sources:
            for _, source in sources[:5]:
                classification = source.get("assessment", {}).get("classification", "未标注")
                lines.append(
                    "- **"
                    + source["title"]
                    + "** · "
                    + source["type"]
                    + " · "
                    + classification
                )
        else:
            lines.append("- 今天尚未录入新来源。")

        lines.extend(["", "## 2. New Knowledge", ""])
        lines.extend(self._record_lines(new_records, "今天没有新增知识卡。"))
        lines.extend(["", "## 3. Existing Knowledge Updated", ""])
        lines.extend(self._record_lines(updated_records, "今天没有更新旧知识。"))
        lines.extend(["", "## 4. Connections", ""])
        if relationships:
            for rel in relationships:
                source_title = index["chunks"].get(rel["source"], {}).get(
                    "title", rel["source_title"]
                )
                lines.append(
                    "- "
                    + wikilink(source_title)
                    + " → `"
                    + rel["type"]
                    + "` → "
                    + wikilink(rel["target_title"])
                )
        else:
            lines.append("- 今天没有新增知识连接。")

        lines.extend(["", "## 5. Deep Dive", ""])
        if ranked:
            focus = ranked[0]
            lines.append(
                "- "
                + wikilink(focus["title"])
                + "，优先级 "
                + str(focus["priority_score"])
                + "。"
            )
            lines.append("- 理由：" + focus["why_it_matters"])
        else:
            lines.append("- 今日暂无推荐。")

        lines.extend(["", "## 6. Open Questions", ""])
        if questions:
            lines.extend("- [ ] " + item["question"] for item in questions)
        else:
            lines.append("- 今日没有新增开放问题。")

        path = self.daily_dir / (target_s + " AI Daily Digest.md")
        _write_text(path, "\n".join(lines))
        return path

    def weekly_review(self, week_end: date) -> Path:
        index = self.load_index()
        week_start = week_end - timedelta(days=6)

        def in_week(value: str) -> bool:
            current = date.fromisoformat(value[:10])
            return week_start <= current <= week_end

        touched = [
            item for item in index["chunks"].values() if in_week(item["updated_at"])
        ]
        created = [item for item in touched if in_week(item["created_at"])]
        keyword_counts = Counter(
            keyword for item in touched for keyword in item.get("keywords", [])
        )
        category_counts = Counter(item["category"] for item in touched)
        relationships = [
            rel for rel in index["relationships"] if in_week(rel["date"])
        ]
        gaps = self._knowledge_gaps(index, touched)

        path = self.weekly_dir / (
            week_end.strftime("%G-W%V") + " Weekly AI Knowledge Review.md"
        )
        lines = [
            "---",
            "type: ai-weekly-review",
            "week_start: " + week_start.isoformat(),
            "week_end: " + week_end.isoformat(),
            "new_chunks: " + str(len(created)),
            "---",
            "",
            "# Weekly AI Knowledge Review",
            "",
            "## 1. 这周真正学到了什么",
            "",
        ]
        lines.extend(self._record_lines(created[:12], "本周没有新增知识卡。"))
        lines.extend(["", "## 2. 重复出现的主题", ""])
        trends = category_counts.most_common(5) + keyword_counts.most_common(5)
        if trends:
            seen = set()
            for topic, count in trends:
                if topic not in seen and count >= 2:
                    lines.append("- **" + topic + "**：出现 " + str(count) + " 次")
                    seen.add(topic)
            if not seen:
                lines.append("- 暂无重复频次足够高的主题。")
        else:
            lines.append("- 暂无数据。")

        lines.extend(["", "## 3. 正在形成的知识链", ""])
        if relationships:
            for rel in relationships[:12]:
                lines.append(
                    "- "
                    + wikilink(rel["source_title"])
                    + " → "
                    + wikilink(rel["target_title"])
                    + " (`"
                    + rel["type"]
                    + "`)"
                )
        else:
            lines.append("- 本周尚未形成新的知识链。")

        lines.extend(["", "## 4. Knowledge Gaps", ""])
        lines.extend("- [ ] " + gap for gap in gaps[:10])
        if not gaps:
            lines.append("- 暂未识别出明显缺口。")

        lines.extend(["", "## 5. 下周深入主题", ""])
        recommendations = [
            topic for topic, count in keyword_counts.most_common() if count >= 2
        ][:3]
        if not recommendations:
            recommendations = [topic for topic, _ in category_counts.most_common(3)]
        lines.extend("- " + topic for topic in recommendations)
        if not recommendations:
            lines.append("- 数据不足，暂不推荐。")

        _write_text(path, "\n".join(lines))
        return path

    def rebuild_maps(self, index: Optional[Dict[str, Any]] = None) -> None:
        if index is None:
            if not self.index_path.exists():
                return
            index = json.loads(self.index_path.read_text(encoding="utf-8"))
        by_category: Dict[str, List[Dict[str, Any]]] = {}
        for record in index["chunks"].values():
            by_category.setdefault(record["category"], []).append(record)

        overview = [
            "---",
            "type: ai-knowledge-map",
            "updated: " + now_iso(),
            "---",
            "",
            "# AI Knowledge Map",
            "",
            "> 图谱入口。关系来自知识卡中的 Wikilink，可直接使用 Obsidian Graph 浏览。",
            "",
        ]
        for category in CATEGORIES:
            records = sorted(
                by_category.get(category, []),
                key=lambda item: (-item.get("priority_score", 0), item["title"]),
            )
            overview.append("## " + category)
            overview.append("")
            if records:
                overview.extend(
                    "- "
                    + wikilink(item["title"])
                    + " · "
                    + item["level"]
                    + " · P="
                    + str(item["priority_score"])
                    for item in records
                )
            else:
                overview.append("- _暂无知识卡_")
            overview.append("")
        _write_text(self.maps_dir / "AI Knowledge Map.md", "\n".join(overview))

    def _normalize_source(self, source: Dict[str, Any]) -> Dict[str, Any]:
        captured_at = str(source.get("captured_at") or now_iso())
        return {
            "title": str(source.get("title") or "Untitled source").strip(),
            "type": str(source.get("type") or "article").strip(),
            "url": str(source.get("url") or "").strip(),
            "author": str(source.get("author") or "").strip(),
            "published_at": str(source.get("published_at") or "").strip(),
            "captured_at": captured_at,
            "credibility": str(source.get("credibility") or "unverified").strip(),
        }

    def _normalize_chunk(self, chunk: Dict[str, Any]) -> Dict[str, Any]:
        title = str(chunk.get("title") or "").strip()
        if not title:
            raise ValueError("Each chunk requires a title")
        category = str(chunk.get("category") or "Frontier").strip()
        level = str(chunk.get("level") or "L1").strip().upper()
        if level not in LEVELS:
            raise ValueError("Invalid level for " + title + ": " + level)
        priority = chunk.get("priority") or {}
        return {
            "title": title,
            "canonical_key": str(chunk.get("canonical_key") or canonicalize(title)),
            "aliases": sorted(
                {str(item).strip() for item in chunk.get("aliases", []) if str(item).strip()}
            ),
            "category": category,
            "concept": str(chunk.get("concept") or "").strip(),
            "problem": str(chunk.get("problem") or "").strip(),
            "mechanism": str(chunk.get("mechanism") or "").strip(),
            "why_it_matters": str(chunk.get("why_it_matters") or "").strip(),
            "example": str(chunk.get("example") or "").strip(),
            "connections": chunk.get("connections") or [],
            "parents": chunk.get("parents") or [],
            "level": level,
            "keywords": sorted(
                {str(item).strip() for item in chunk.get("keywords", []) if str(item).strip()}
            )[:8],
            "classification": str(chunk.get("classification") or "A").strip().upper(),
            "priority": {
                key: priority.get(key, 0)
                for key in ("relevance", "novelty", "connection", "impact")
            },
        }

    def _new_record(
        self, chunk_id: str, chunk: Dict[str, Any], source_id: str
    ) -> Dict[str, Any]:
        timestamp = now_iso()
        return {
            "id": chunk_id,
            **chunk,
            "priority_score": score_priority(chunk["priority"]),
            "sources": [source_id],
            "relationship_refs": [],
            "created_at": timestamp,
            "updated_at": timestamp,
        }

    def _merge_record(
        self, record: Dict[str, Any], chunk: Dict[str, Any], source_id: str
    ) -> None:
        for field in (
            "concept",
            "problem",
            "mechanism",
            "why_it_matters",
            "example",
        ):
            incoming = chunk.get(field, "")
            if len(incoming) > len(record.get(field, "")):
                record[field] = incoming
        record["aliases"] = sorted(
            set(record.get("aliases", [])) | set(chunk.get("aliases", []))
        )
        record["keywords"] = sorted(
            set(record.get("keywords", [])) | set(chunk.get("keywords", []))
        )[:8]
        if source_id not in record["sources"]:
            record["sources"].append(source_id)
        incoming_score = score_priority(chunk["priority"])
        if incoming_score >= record.get("priority_score", 0):
            record["priority"] = chunk["priority"]
            record["priority_score"] = incoming_score
        record["updated_at"] = now_iso()

    def _merge_relationships(
        self,
        index: Dict[str, Any],
        record: Dict[str, Any],
        chunk: Dict[str, Any],
        relationship_date: str,
    ) -> int:
        additions = 0
        raw_relationships = list(chunk.get("connections", []))
        raw_relationships.extend(
            {"target": parent, "type": "child_of"} for parent in chunk.get("parents", [])
        )
        for raw in raw_relationships:
            if isinstance(raw, str):
                raw = {"target": raw, "type": "related_to"}
            target_title = str(raw.get("target") or "").strip()
            if not target_title or canonicalize(target_title) == record["canonical_key"]:
                continue
            target_id = index["canonical"].get(canonicalize(target_title))
            relation = {
                "source": record["id"],
                "source_title": record["title"],
                "target": target_id,
                "target_title": target_title,
                "type": str(raw.get("type") or "related_to").strip(),
                "note": str(raw.get("note") or "").strip(),
                "date": relationship_date,
            }
            relation_key = (
                relation["source"],
                canonicalize(relation["target_title"]),
                relation["type"],
            )
            existing_keys = {
                (
                    item["source"],
                    canonicalize(item["target_title"]),
                    item["type"],
                )
                for item in index["relationships"]
            }
            if relation_key not in existing_keys:
                index["relationships"].append(relation)
                record["relationship_refs"].append(relation)
                additions += 1
        return additions

    def _resolve_relationship_targets(self, index: Dict[str, Any]) -> None:
        for relation in index["relationships"]:
            relation["target"] = index["canonical"].get(
                canonicalize(relation["target_title"])
            )

    def _write_chunk(self, record: Dict[str, Any], index: Dict[str, Any]) -> None:
        relationships = [
            rel for rel in index["relationships"] if rel["source"] == record["id"]
        ]
        source_links = []
        for source_id in record["sources"]:
            source = index["sources"].get(source_id)
            if source:
                source_links.append(wikilink(Path(source["path"]).stem))
            else:
                source_links.append(source_id)
        relation_lines = []
        for rel in relationships:
            note = " - " + rel["note"] if rel["note"] else ""
            relation_lines.append(
                "- `"
                + rel["type"]
                + "` → "
                + wikilink(rel["target_title"])
                + note
            )
        if not relation_lines:
            relation_lines.append("- 暂无")

        content = [
            "---",
            "type: knowledge-chunk",
            "id: " + json_yaml(record["id"]),
            "title: " + json_yaml(record["title"]),
            "canonical_key: " + json_yaml(record["canonical_key"]),
            "aliases: " + json_yaml(record.get("aliases", [])),
            "category: " + json_yaml(record["category"]),
            "level: " + json_yaml(record["level"]),
            "classification: " + json_yaml(record["classification"]),
            "keywords: " + json_yaml(record["keywords"]),
            "priority: " + json_yaml(record["priority_score"]),
            "created: " + json_yaml(record["created_at"]),
            "updated: " + json_yaml(record["updated_at"]),
            "---",
            "",
            "# " + record["title"],
            "",
            "## Concept",
            "",
            record["concept"] or "待补充。",
            "",
            "## Problem",
            "",
            record["problem"] or "待补充。",
            "",
            "## Mechanism",
            "",
            record["mechanism"] or "待补充。",
            "",
            "## Why it matters",
            "",
            record["why_it_matters"] or "待补充。",
            "",
            "## Example",
            "",
            record["example"] or "待补充。",
            "",
            "## Connections",
            "",
            *relation_lines,
            "",
            "## Sources",
            "",
            *("- " + source for source in source_links),
        ]
        _write_text(self._chunk_path(record), "\n".join(content))

    def _write_source(
        self,
        path: Path,
        source_id: str,
        source: Dict[str, Any],
        payload: Dict[str, Any],
        chunk_ids: List[str],
        index: Dict[str, Any],
    ) -> None:
        assessment = payload.get("assessment", {})
        chunk_lines = [
            "- " + wikilink(index["chunks"][chunk_id]["title"])
            for chunk_id in chunk_ids
            if chunk_id in index["chunks"]
        ]
        content = [
            "---",
            "type: ai-source",
            "id: " + json_yaml(source_id),
            "source_type: " + json_yaml(source["type"]),
            "author: " + json_yaml(source["author"]),
            "url: " + json_yaml(source["url"]),
            "published_at: " + json_yaml(source["published_at"]),
            "captured_at: " + json_yaml(source["captured_at"]),
            "credibility: " + json_yaml(source["credibility"]),
            "classification: "
            + json_yaml(assessment.get("classification", "unclassified")),
            "---",
            "",
            "# " + source["title"],
            "",
            "## Value Assessment",
            "",
            "- Classification: "
            + str(assessment.get("classification", "unclassified")),
            "- Rationale: " + str(assessment.get("rationale", "待补充")),
            "- Fact / interpretation / opinion boundary: "
            + str(assessment.get("evidence_boundary", "待补充")),
            "",
            "## Knowledge Chunks",
            "",
            *(chunk_lines or ["- 未生成知识卡。"]),
            "",
            "## Source Notes",
            "",
            str(payload.get("source_notes") or "待补充。"),
        ]
        _write_text(path, "\n".join(content))

    def _write_home(self) -> None:
        content = """---
type: ai-knowledge-home
---

# AI Knowledge

## Navigate

- [[AI Knowledge Map]]
- `00 Inbox`：待处理来源与结构化输入
- `10 Sources`：原始来源、可信度和事实边界
- `20 Knowledge Chunks`：可独立复用的原子知识
- `40 Daily Digests`：每日增量
- `50 Weekly Reviews`：每周知识重组与缺口

## Operating Principle

> Chunk before summarize.

先判断价值，再拆分知识；先搜索去重，再创建卡片；新闻保留为来源，不强行知识化。
"""
        _write_text(self.root / "AI Knowledge Home.md", content)

    def _write_data_dictionary(self) -> None:
        content = """# AI Knowledge Data Dictionary

## Classification

- `A`：新知识
- `B`：已知知识的新解释
- `C`：已有知识的延伸
- `D`：新闻 / 事件
- `E`：观点 / 判断
- `F`：案例
- `G`：暂时没有长期价值

## Level

- `L1`：入门概念
- `L2`：技术原理
- `L3`：工程实现
- `L4`：Research Frontier

## Relationship Types

- `child_of`：下位概念
- `depends_on`：依赖或前置知识
- `enables`：带来能力
- `improves`：优化对象
- `contrasts_with`：方法对比
- `used_in`：应用于
- `related_to`：一般相关

## Priority

`Priority = Relevance × Novelty × Connection × Impact`

四项分别取 0–5。乘积用于排序，不代表事实可信度。
"""
        _write_text(self.system_dir / "Data Dictionary.md", content)

    def _alias_match(self, index: Dict[str, Any], title: str) -> Optional[str]:
        key = canonicalize(title)
        for chunk_id, record in index["chunks"].items():
            aliases = [canonicalize(item) for item in record.get("aliases", [])]
            if key in aliases:
                return chunk_id
        return None

    def _similar_candidates(
        self, index: Dict[str, Any], title: str
    ) -> List[Dict[str, Any]]:
        key = canonicalize(title)
        candidates = []
        for record in index["chunks"].values():
            ratio = SequenceMatcher(None, key, record["canonical_key"]).ratio()
            if ratio >= 0.82:
                candidates.append(
                    {
                        "id": record["id"],
                        "title": record["title"],
                        "similarity": round(ratio, 3),
                    }
                )
        return sorted(candidates, key=lambda item: item["similarity"], reverse=True)[:5]

    def _knowledge_gaps(
        self, index: Dict[str, Any], touched: Iterable[Dict[str, Any]]
    ) -> List[str]:
        gaps = [
            item["question"]
            for item in index["open_questions"]
            if item["status"] == "open"
        ]
        for record in touched:
            if not record.get("relationship_refs"):
                gaps.append(record["title"] + " 尚未连接到其他知识节点")
            missing = [
                field
                for field in ("problem", "mechanism", "example")
                if not record.get(field)
            ]
            if missing:
                gaps.append(record["title"] + " 缺少：" + "、".join(missing))
        return list(dict.fromkeys(gaps))

    def _record_lines(
        self, records: Iterable[Dict[str, Any]], empty: str
    ) -> List[str]:
        records = sorted(
            records,
            key=lambda item: item.get("priority_score", 0),
            reverse=True,
        )
        if not records:
            return ["- " + empty]
        return [
            "- "
            + wikilink(item["title"])
            + " · "
            + item["category"]
            + " · "
            + item["level"]
            + " · P="
            + str(item["priority_score"])
            for item in records
        ]

    def _source_id(self, source: Dict[str, Any]) -> str:
        raw = source["url"] or source["title"] + source["captured_at"][:10]
        return "src-" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]

    def _chunk_id(self, canonical_key: str) -> str:
        return "kc-" + hashlib.sha1(canonical_key.encode("utf-8")).hexdigest()[:12]

    def _chunk_path(self, record: Dict[str, Any]) -> Path:
        return self.chunks_dir / (safe_name(record["title"]) + ".md")
