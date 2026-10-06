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
from .updater import (
    configure_notification,
    ensure_daily_update,
    install_schedule,
    load_notification_config,
    schedule_info,
    send_learning_reminder,
    update_daily,
)
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
    subparsers.add_parser(
        "ensure-daily", help="当天更新未成功时执行补漏更新。"
    )

    schedule = subparsers.add_parser("schedule", help="管理每日更新计划。")
    schedule.add_argument("action", choices=("install", "status"))
    schedule.add_argument("--hour", type=int, default=8)
    schedule.add_argument("--minute", type=int, default=0)

    notification = subparsers.add_parser(
        "notification", help="管理每日飞书学习提醒。"
    )
    notification.add_argument(
        "action", choices=("configure", "status", "test", "disable")
    )
    notification.add_argument("--user-id")
    notification.add_argument(
        "--as", dest="identity", choices=("user", "bot"), default="bot"
    )
    notification.add_argument("--dry-run", action="store_true")
    notification.add_argument(
        "--confirm-send",
        action="store_true",
        help="真实发送测试提醒时必须显式确认。",
    )
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
        elif args.command == "ensure-daily":
            result = ensure_daily_update(store)
        elif args.command == "schedule":
            if args.action == "install":
                result = install_schedule(
                    args.vault, hour=args.hour, minute=args.minute
                )
            else:
                result = {"ok": True, **schedule_info(store)}
        elif args.command == "notification":
            if args.action == "configure":
                if not args.user_id:
                    raise ValueError("notification configure 需要 --user-id")
                result = {
                    "ok": True,
                    **configure_notification(
                        store, args.user_id, identity=args.identity
                    ),
                }
            elif args.action == "disable":
                current = load_notification_config(store)
                result = {
                    "ok": True,
                    **configure_notification(
                        store,
                        current["user_id"],
                        identity=current["identity"],
                        enabled=False,
                    ),
                }
            elif args.action == "test":
                if not args.dry_run and not args.confirm_send:
                    raise ValueError("真实发送测试提醒需要 --confirm-send")
                result = {
                    "ok": True,
                    **send_learning_reminder(
                        store, date.today(), dry_run=args.dry_run
                    ),
                }
            else:
                result = {"ok": True, **load_notification_config(store)}
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
