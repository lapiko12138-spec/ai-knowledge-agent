from __future__ import annotations

import json
import shutil
import subprocess
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional

from .core import KnowledgeStore
from .feeds import load_daily_intelligence


def _truncate(value: str, limit: int = 180) -> str:
    value = " ".join(value.split())
    return value if len(value) <= limit else value[: limit - 1].rstrip() + "…"


def _markdown(content: str, text_size: str = "body", align: str = "left") -> Dict[str, Any]:
    return {
        "tag": "markdown",
        "content": content,
        "text_size": text_size,
        "text_align": align,
    }


def _metric_column(value: str, label: str, primary: bool = False) -> Dict[str, Any]:
    value_markup = (
        "## <font color='blue'>" + value + "</font>"
        if primary
        else "**" + value + "**"
    )
    return {
        "tag": "column",
        "width": "weighted",
        "weight": 1,
        "background_style": "grey-50",
        "padding": "12px",
        "vertical_spacing": "2px",
        "elements": [
            _markdown(value_markup, align="center"),
            _markdown(
                "<font color='grey'>" + label + "</font>",
                text_size="caption",
                align="center",
            ),
        ],
    }


def _section(title: str, content: str, background: str = "grey-50") -> Dict[str, Any]:
    return {
        "tag": "column_set",
        "flex_mode": "none",
        "background_style": background,
        "columns": [
            {
                "tag": "column",
                "width": "weighted",
                "weight": 1,
                "padding": "12px",
                "vertical_spacing": "4px",
                "elements": [
                    _markdown("**" + title + "**", text_size="title"),
                    _markdown(content),
                ],
            }
        ],
    }


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _lark_cli_path() -> str:
    candidates = [
        Path.home()
        / ".trae-cn"
        / "plugins"
        / "trae-remote-official"
        / "lark"
        / "1.0.5"
        / "bin"
        / "lark-cli",
        Path("/opt/homebrew/bin/lark-cli"),
        Path("/usr/local/bin/lark-cli"),
    ]
    installed = next((path for path in candidates if path.is_file()), None)
    if installed:
        return str(installed)
    discovered = shutil.which("lark-cli")
    if discovered:
        return discovered
    raise RuntimeError("未找到 lark-cli，无法发送飞书提醒")


def build_learning_reminder_card(
    store: KnowledgeStore, target: date
) -> Dict[str, Any]:
    intelligence = _read_json(store.system_dir / "daily-intelligence.json")
    if not intelligence:
        intelligence = load_daily_intelligence(store, cache_minutes=10**9)
    papers = intelligence.get("huggingface", {}).get("papers", [])
    radar_topics = intelligence.get("x_radar", {}).get("topics", [])
    read_items = _read_json(
        store.system_dir / "radar-progress.json"
    ).get("read_items", {})
    unread_topics = [
        item for item in radar_topics if str(item.get("id", "")) not in read_items
    ]

    index = store.load_index()
    learning = _read_json(
        store.system_dir / "learning-progress.json"
    ).get("chunks", {})
    pending_chunks = [
        item
        for item in index.get("chunks", {}).values()
        if learning.get(item.get("id"), {}).get("status", "unread") != "mastered"
    ]
    pending_chunks.sort(
        key=lambda item: float(item.get("priority_score", 0)), reverse=True
    )

    focus = next(
        (item for item in papers if item.get("editorial_tier") == "focus"),
        papers[0] if papers else None,
    )
    if focus:
        localized = focus.get("localized", {})
        focus_title = localized.get("title_zh") or focus.get("title") or "今日论文"
        focus_note = (
            localized.get("editor_note")
            or localized.get("research_question_zh")
            or focus.get("summary")
            or "值得今天优先阅读。"
        )
        focus_url = str(focus.get("url") or "")
        focus_heading = (
            "[" + _truncate(str(focus_title), 90) + "](" + focus_url + ")"
            if focus_url
            else _truncate(str(focus_title), 90)
        )
        focus_content = (
            "**今日 Deep Dive：" + focus_heading + "**\n"
            + _truncate(str(focus_note), 220)
        )
    else:
        focus_content = "**今日 Deep Dive**\n今日暂无新论文，先复习已有知识卡。"

    paper_lines = []
    for item in papers[:5]:
        localized = item.get("localized", {})
        title = localized.get("title_zh") or item.get("title") or "未命名论文"
        url = str(item.get("url") or "")
        title_markup = (
            "[" + _truncate(str(title), 72) + "](" + url + ")"
            if url
            else _truncate(str(title), 72)
        )
        paper_lines.append(
            "- " + title_markup + " · " + str(item.get("upvotes", 0)) + " 赞"
        )
    if not paper_lines:
        paper_lines.append("- 今日暂无可用论文")

    radar_lines = []
    for item in unread_topics[:4]:
        person = (
            item.get("person_name")
            or item.get("person")
            or item.get("author")
            or item.get("name")
            or "人物雷达"
        )
        url = str(item.get("url") or "")
        person_markup = (
            "[" + _truncate(str(person), 24) + "](" + url + ")"
            if url
            else _truncate(str(person), 24)
        )
        viewpoint = (
            item.get("viewpoint")
            or item.get("summary")
            or item.get("title")
            or "待阅读观点"
        )
        radar_lines.append(
            "- **" + person_markup + "**：" + _truncate(str(viewpoint), 100)
        )
    if not radar_lines:
        radar_lines.append("- 暂无未读人物观点")

    next_chunk = pending_chunks[0] if pending_chunks else None
    if next_chunk:
        next_content = (
            "**"
            + _truncate(str(next_chunk.get("title", "下一张知识卡")), 90)
            + "**\n"
            + _truncate(
                str(next_chunk.get("why_it_matters") or next_chunk.get("concept") or ""),
                220,
            )
        )
    else:
        next_content = "现有知识卡已全部掌握，今天可选择一篇论文继续深挖。"

    return {
        "schema": "2.0",
        "config": {
            "update_multi": True,
            "width_mode": "default",
            "summary": {"content": "AI 学习提醒 · " + target.isoformat()},
            "style": {
                "text_size": {
                    "title": {
                        "default": "heading-2",
                        "pc": "heading-2",
                        "mobile": "heading-3",
                    },
                    "body": {
                        "default": "normal",
                        "pc": "normal",
                        "mobile": "normal",
                    },
                    "caption": {
                        "default": "notation",
                        "pc": "notation",
                        "mobile": "notation",
                    },
                }
            },
        },
        "header": {
            "title": {"tag": "plain_text", "content": "今日 AI 学习提醒"},
            "subtitle": {
                "tag": "plain_text",
                "content": target.isoformat() + " · 每天推进一点",
            },
            "template": "blue",
            "icon": {"tag": "standard_icon", "token": "ai-common_colorful"},
        },
        "body": {
            "direction": "vertical",
            "padding": "12px 12px 20px 12px",
            "vertical_spacing": "large",
            "elements": [
                _section("今日重点", focus_content, background="blue-50"),
                {
                    "tag": "column_set",
                    "flex_mode": "none",
                    "horizontal_spacing": "large",
                    "columns": [
                        _metric_column(str(len(papers)), "今日论文", primary=True),
                        _metric_column(str(len(unread_topics)), "未读观点"),
                        _metric_column(str(len(pending_chunks)), "待学知识卡"),
                    ],
                },
                _section("今日论文", "\n".join(paper_lines)),
                _section("人物雷达 · 未读观点", "\n".join(radar_lines)),
                _section("下一张知识卡", next_content, background="blue-50"),
            ],
        },
    }


def build_daily_card(store: KnowledgeStore, target: date) -> Dict[str, Any]:
    index = store.load_index()
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
    relationships = [
        item for item in index["relationships"] if item["date"] == target_s
    ]
    questions = [
        item
        for item in index["open_questions"]
        if item["date"] == target_s and item["status"] == "open"
    ]
    sources = [
        item
        for item in index["sources"].values()
        if item["captured_at"][:10] == target_s
    ]
    ranked = sorted(
        new_records + updated_records,
        key=lambda item: item.get("priority_score", 0),
        reverse=True,
    )
    focus = ranked[0] if ranked else None

    source_lines = []
    for item in sources[:5]:
        classification = item.get("assessment", {}).get("classification", "未标注")
        source_lines.append(
            "- **" + _truncate(item["title"], 70) + "** · " + str(classification)
        )
    if not source_lines:
        source_lines.append("- 今天尚未录入新来源")

    change_lines = []
    for item in new_records[:4]:
        change_lines.append(
            "- <text_tag color='blue'>新增</text_tag> " + _truncate(item["title"], 64)
        )
    for item in updated_records[:3]:
        change_lines.append(
            "- <text_tag color='violet'>更新</text_tag> " + _truncate(item["title"], 64)
        )
    if not change_lines:
        change_lines.append("- 今天没有知识卡变化")

    connection_lines = [
        "- "
        + _truncate(item["source_title"], 36)
        + " → "
        + _truncate(item["target_title"], 36)
        for item in relationships[:4]
    ]
    if not connection_lines:
        connection_lines.append("- 今天没有新增知识连接")

    question_lines = ["- " + _truncate(item["question"], 100) for item in questions[:3]]
    if not question_lines:
        question_lines.append("- 今天没有新增开放问题")

    focus_content = (
        "**今日 Deep Dive："
        + _truncate(focus["title"], 90)
        + "**\n"
        + _truncate(focus.get("why_it_matters", "值得继续深入。"), 220)
        if focus
        else "**今日 Deep Dive**\n暂无推荐，先补充高价值信息源。"
    )

    return {
        "schema": "2.0",
        "config": {
            "update_multi": True,
            "width_mode": "default",
            "summary": {"content": "AI Daily Digest · " + target_s},
            "style": {
                "text_size": {
                    "title": {
                        "default": "heading-2",
                        "pc": "heading-2",
                        "mobile": "heading-3",
                    },
                    "body": {
                        "default": "normal",
                        "pc": "normal",
                        "mobile": "normal",
                    },
                    "caption": {
                        "default": "notation",
                        "pc": "notation",
                        "mobile": "notation",
                    },
                }
            },
        },
        "header": {
            "title": {"tag": "plain_text", "content": "AI Daily Digest"},
            "subtitle": {"tag": "plain_text", "content": target_s + " · Knowledge Graph"},
            "template": "blue",
            "icon": {"tag": "standard_icon", "token": "ai-common_colorful"},
            "text_tag_list": [
                {
                    "tag": "text_tag",
                    "text": {"tag": "plain_text", "content": "Daily"},
                    "color": "blue",
                }
            ],
        },
        "body": {
            "direction": "vertical",
            "padding": "12px 12px 20px 12px",
            "vertical_spacing": "large",
            "elements": [
                {
                    "tag": "column_set",
                    "flex_mode": "none",
                    "background_style": "blue-50",
                    "columns": [
                        {
                            "tag": "column",
                            "width": "weighted",
                            "weight": 1,
                            "padding": "12px",
                            "elements": [_markdown(focus_content)],
                        }
                    ],
                },
                {
                    "tag": "column_set",
                    "flex_mode": "none",
                    "horizontal_spacing": "large",
                    "columns": [
                        _metric_column(
                            str(len(new_records) + len(updated_records)),
                            "知识变化",
                            primary=True,
                        ),
                        _metric_column(str(len(relationships)), "新增连接"),
                        _metric_column(str(len(questions)), "开放问题"),
                    ],
                },
                {
                    "tag": "column_set",
                    "flex_mode": "none",
                    "background_style": "blue-50",
                    "columns": [
                        {
                            "tag": "column",
                            "width": "weighted",
                            "weight": 1,
                            "padding": "12px",
                            "vertical_spacing": "4px",
                            "elements": [
                                _markdown("**Today**", text_size="title"),
                                _markdown("\n".join(source_lines)),
                            ],
                        }
                    ],
                },
                {
                    "tag": "column_set",
                    "flex_mode": "bisect",
                    "horizontal_spacing": "large",
                    "columns": [
                        {
                            "tag": "column",
                            "background_style": "grey-50",
                            "padding": "12px",
                            "vertical_spacing": "4px",
                            "elements": [
                                _markdown("**Knowledge**", text_size="title"),
                                _markdown("\n".join(change_lines)),
                            ],
                        },
                        {
                            "tag": "column",
                            "background_style": "grey-50",
                            "padding": "12px",
                            "vertical_spacing": "4px",
                            "elements": [
                                _markdown("**Connections & Gaps**", text_size="title"),
                                _markdown(
                                    "\n".join(connection_lines + question_lines)
                                ),
                            ],
                        },
                    ],
                },
            ],
        },
    }


def send_card(
    card: Dict[str, Any],
    chat_id: Optional[str] = None,
    user_id: Optional[str] = None,
    identity: str = "bot",
    dry_run: bool = False,
    confirm_send: bool = False,
    cwd: Optional[Path] = None,
    idempotency_key: Optional[str] = None,
) -> Dict[str, Any]:
    if bool(chat_id) == bool(user_id):
        raise ValueError("Provide exactly one of chat_id or user_id")
    if not dry_run and not confirm_send:
        raise ValueError("Live sending requires --confirm-send")
    command: List[str] = [
        _lark_cli_path(),
        "im",
        "+messages-send",
        "--as",
        identity,
        "--msg-type",
        "interactive",
        "--content",
        json.dumps(card, ensure_ascii=False, separators=(",", ":")),
        "--idempotency-key",
        idempotency_key or "ai-digest-" + date.today().isoformat(),
    ]
    if chat_id:
        command.extend(["--chat-id", chat_id])
    else:
        command.extend(["--user-id", str(user_id)])
    if dry_run:
        command.append("--dry-run")

    completed = subprocess.run(
        command,
        cwd=str(cwd) if cwd else None,
        check=False,
        text=True,
        capture_output=True,
    )
    output = completed.stdout.strip() or completed.stderr.strip()
    try:
        result = json.loads(output)
    except json.JSONDecodeError:
        result = {
            "ok": False,
            "error": {
                "type": "invalid_cli_output",
                "message": output,
            },
        }
    if completed.returncode != 0 or result.get("ok") is False:
        raise RuntimeError(json.dumps(result, ensure_ascii=False))
    return result
