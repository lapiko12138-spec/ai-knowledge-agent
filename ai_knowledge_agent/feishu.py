from __future__ import annotations

import json
import subprocess
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional

from .core import KnowledgeStore


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
        "lark-cli",
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
