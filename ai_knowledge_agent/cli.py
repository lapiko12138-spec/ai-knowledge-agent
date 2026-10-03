from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date
from pathlib import Path
from typing import Any, Dict, Optional

from .core import KnowledgeStore
from .feishu import build_daily_card, send_card
from .updater import install_schedule, schedule_info, update_daily
from .web import serve


DEFAULT_VAULT = Path.home() / "Downloads" / "obsidian"


def _date(value: str) -> date:
    return date.fromisoformat(value)


def _load_json(path: str) -> Dict[str, Any]:
    if path == "-":
        return json.load(sys.stdin)
    return json.loads(Path(path).expanduser().read_text(encoding="utf-8"))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ai-knowledge",
        description="Obsidian-first AI knowledge graph workflow.",
    )
    parser.add_argument(
        "--vault",
        type=Path,
        default=Path(os.getenv("AI_KNOWLEDGE_VAULT", str(DEFAULT_VAULT))),
        help="Obsidian vault path (default: ~/Downloads/obsidian).",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("init", help="Initialize the AI Knowledge vault structure.")

    ingest = subparsers.add_parser("ingest", help="Ingest a structured source analysis.")
    ingest.add_argument("input", help="JSON file path, or - for stdin.")
    ingest.add_argument(
        "--allow-similar",
        action="store_true",
        help="Create a chunk even when a similar existing title is found.",
    )

    search = subparsers.add_parser("search", help="Search existing knowledge chunks.")
    search.add_argument("query")
    search.add_argument("--limit", type=int, default=10)

    daily = subparsers.add_parser("daily", help="Generate an AI Daily Digest.")
    daily.add_argument("--date", type=_date, default=date.today())

    weekly = subparsers.add_parser("weekly", help="Generate a weekly knowledge review.")
    weekly.add_argument(
        "--week-end",
        type=_date,
        default=date.today(),
        help="Inclusive review end date.",
    )

    card = subparsers.add_parser("card", help="Build a Feishu daily digest card JSON.")
    card.add_argument("--date", type=_date, default=date.today())
    card.add_argument("--output", type=Path)

    send = subparsers.add_parser("send-daily", help="Send or preview a Feishu digest card.")
    send.add_argument("--date", type=_date, default=date.today())
    destination = send.add_mutually_exclusive_group(required=True)
    destination.add_argument("--chat-id")
    destination.add_argument("--user-id")
    send.add_argument("--as", dest="identity", choices=("user", "bot"), default="bot")
    send.add_argument("--dry-run", action="store_true")
    send.add_argument(
        "--confirm-send",
        action="store_true",
        help="Required for a live send after recipient/content/identity review.",
    )

    web = subparsers.add_parser("serve", help="启动中文交互学习网页。")
    web.add_argument("--host", default="127.0.0.1")
    web.add_argument("--port", type=int, default=8765)

    subparsers.add_parser("update-daily", help="执行一次每日信息更新。")

    schedule = subparsers.add_parser("schedule", help="管理每日更新计划。")
    schedule.add_argument("action", choices=("install", "status"))
    schedule.add_argument("--hour", type=int, default=8)
    schedule.add_argument("--minute", type=int, default=0)
    return parser


def main(argv: Optional[list] = None) -> int:
    args = build_parser().parse_args(argv)
    store = KnowledgeStore(args.vault)

    try:
        if args.command == "init":
            store.initialize()
            result: Any = {"ok": True, "root": str(store.root)}
        elif args.command == "ingest":
            payload = _load_json(args.input)
            result = {
                "ok": True,
                **store.ingest(payload, allow_similar=args.allow_similar).as_dict(),
            }
        elif args.command == "search":
            result = {"ok": True, "results": store.search(args.query, args.limit)}
        elif args.command == "daily":
            result = {"ok": True, "path": str(store.daily_digest(args.date))}
        elif args.command == "weekly":
            result = {"ok": True, "path": str(store.weekly_review(args.week_end))}
        elif args.command == "card":
            card = build_daily_card(store, args.date)
            rendered = json.dumps(card, ensure_ascii=False, indent=2) + "\n"
            if args.output:
                args.output.expanduser().write_text(rendered, encoding="utf-8")
                result = {"ok": True, "path": str(args.output.expanduser().resolve())}
            else:
                sys.stdout.write(rendered)
                return 0
        elif args.command == "send-daily":
            card = build_daily_card(store, args.date)
            result = send_card(
                card,
                chat_id=args.chat_id,
                user_id=args.user_id,
                identity=args.identity,
                dry_run=args.dry_run,
                confirm_send=args.confirm_send,
                cwd=Path.cwd(),
                idempotency_key="ai-digest-" + args.date.isoformat(),
            )
        elif args.command == "serve":
            serve(store, host=args.host, port=args.port)
            return 0
        elif args.command == "update-daily":
            result = update_daily(store)
        elif args.command == "schedule":
            if args.action == "install":
                result = install_schedule(
                    args.vault, hour=args.hour, minute=args.minute
                )
            else:
                result = {"ok": True, **schedule_info(store)}
        else:
            raise ValueError("Unsupported command: " + args.command)
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as error:
        print(
            json.dumps(
                {"ok": False, "error": str(error)},
                ensure_ascii=False,
                indent=2,
            ),
            file=sys.stderr,
        )
        return 1

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0
