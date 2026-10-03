from __future__ import annotations

import json
import mimetypes
import sys
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from .core import KnowledgeStore, _atomic_json
from .feeds import load_daily_intelligence
from .updater import (
    ensure_daily_update,
    load_update_status,
    sync_github,
    update_daily,
)


PROJECT_ROOT = Path(__file__).resolve().parent.parent
WEB_ROOT = PROJECT_ROOT / "web"
PROGRESS_STATUSES = {"unread", "learning", "mastered"}


def sync_user_state(store: KnowledgeStore) -> Dict[str, Any]:
    try:
        return sync_github(store)
    except (OSError, RuntimeError, ValueError) as error:
        return {"status": "failed", "message": str(error)}


def _read_reports(directory: Path, limit: int = 12) -> List[Dict[str, Any]]:
    if not directory.exists():
        return []
    reports = []
    for path in sorted(directory.glob("*.md"), reverse=True)[:limit]:
        reports.append(
            {
                "name": path.stem,
                "content": path.read_text(encoding="utf-8"),
                "modified_at": datetime.fromtimestamp(
                    path.stat().st_mtime
                ).astimezone().isoformat(timespec="seconds"),
            }
        )
    return reports


def load_progress(store: KnowledgeStore) -> Dict[str, Any]:
    path = store.system_dir / "learning-progress.json"
    if not path.exists():
        return {"version": 1, "chunks": {}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"version": 1, "chunks": {}}
    if not isinstance(payload.get("chunks"), dict):
        return {"version": 1, "chunks": {}}
    return payload


def load_radar_progress(store: KnowledgeStore) -> Dict[str, Any]:
    path = store.system_dir / "radar-progress.json"
    if not path.exists():
        return {"version": 1, "read_items": {}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"version": 1, "read_items": {}}
    if not isinstance(payload.get("read_items"), dict):
        return {"version": 1, "read_items": {}}
    return payload


def save_radar_read(
    store: KnowledgeStore, item_id: str, is_read: bool
) -> Dict[str, Any]:
    intelligence = load_daily_intelligence(store)
    valid_ids = {
        str(item.get("id"))
        for item in intelligence.get("x_radar", {}).get("topics", [])
    }
    if item_id not in valid_ids:
        raise ValueError("人物观点不存在")
    progress = load_radar_progress(store)
    if is_read:
        progress["read_items"][item_id] = {
            "read_at": datetime.now().astimezone().isoformat(timespec="seconds")
        }
    else:
        progress["read_items"].pop(item_id, None)
    _atomic_json(store.system_dir / "radar-progress.json", progress)
    return {"item_id": item_id, "is_read": is_read}


def save_progress(
    store: KnowledgeStore,
    chunk_id: str,
    status: str,
    confidence: int,
    notes: str,
) -> Dict[str, Any]:
    index = store.load_index()
    if chunk_id not in index["chunks"]:
        raise ValueError("知识卡不存在")
    if status not in PROGRESS_STATUSES:
        raise ValueError("学习状态无效")
    confidence = max(0, min(5, int(confidence)))
    notes = str(notes).strip()[:5000]
    progress = load_progress(store)
    progress["chunks"][chunk_id] = {
        "status": status,
        "confidence": confidence,
        "notes": notes,
        "reviewed_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    _atomic_json(store.system_dir / "learning-progress.json", progress)
    return progress["chunks"][chunk_id]


def build_state(
    store: KnowledgeStore, include_intelligence: bool = True
) -> Dict[str, Any]:
    index = store.load_index()
    progress = load_progress(store)["chunks"]
    sources = index.get("sources", {})

    chunks = []
    for record in index.get("chunks", {}).values():
        source_items = []
        for source_id in record.get("sources", []):
            source = sources.get(source_id)
            if source:
                source_items.append(
                    {
                        "id": source_id,
                        "title": source.get("title", "未命名来源"),
                        "type": source.get("type", "unknown"),
                        "url": source.get("url", ""),
                        "author": source.get("author", ""),
                        "credibility": source.get("credibility", "unverified"),
                    }
                )
        chunks.append(
            {
                **record,
                "sources_detail": source_items,
                "progress": progress.get(
                    record["id"],
                    {
                        "status": "unread",
                        "confidence": 0,
                        "notes": "",
                        "reviewed_at": "",
                    },
                ),
            }
        )

    chunks.sort(
        key=lambda item: (
            item["progress"]["status"] == "mastered",
            -float(item.get("priority_score", 0)),
            item["title"],
        )
    )
    status_counts = {"unread": 0, "learning": 0, "mastered": 0}
    for chunk in chunks:
        status_counts[chunk["progress"]["status"]] += 1

    open_questions = [
        item
        for item in index.get("open_questions", [])
        if item.get("status") == "open"
    ]
    intelligence = (
        load_daily_intelligence(store) if include_intelligence else {}
    )
    read_items = load_radar_progress(store)["read_items"]
    for topic in intelligence.get("x_radar", {}).get("topics", []):
        topic["is_read"] = topic.get("id") in read_items
    for person in intelligence.get("x_radar", {}).get("sources", []):
        for viewpoint in person.get("viewpoints", []):
            viewpoint["is_read"] = viewpoint.get("id") in read_items
    return {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "vault_root": str(store.root),
        "chunks": chunks,
        "relationships": index.get("relationships", []),
        "sources": list(sources.values()),
        "open_questions": open_questions,
        "daily_reports": _read_reports(store.daily_dir),
        "weekly_reports": _read_reports(store.weekly_dir),
        "daily_intelligence": intelligence,
        "update_status": load_update_status(store),
        "stats": {
            "chunks": len(chunks),
            "sources": len(sources),
            "relationships": len(index.get("relationships", [])),
            "open_questions": len(open_questions),
            **status_counts,
        },
    }


def make_handler(store: KnowledgeStore):
    class KnowledgeHandler(BaseHTTPRequestHandler):
        server_version = "AIKnowledge/0.1"

        def log_message(self, format: str, *args: Any) -> None:
            print("[web] " + (format % args))

        def _json(
            self, payload: Dict[str, Any], status: int = 200
        ) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            route = urlparse(self.path).path
            if route == "/api/state":
                try:
                    self._json({"ok": True, "data": build_state(store)})
                except (OSError, ValueError, json.JSONDecodeError) as error:
                    self._json({"ok": False, "error": str(error)}, 500)
                return
            self._serve_static(route)

        def do_POST(self) -> None:
            route = urlparse(self.path).path
            if route == "/api/refresh":
                try:
                    result = update_daily(store)
                    self._json({"ok": result.get("ok", False), "data": result})
                except (OSError, ValueError, json.JSONDecodeError) as error:
                    self._json({"ok": False, "error": str(error)}, 500)
                return
            if route == "/api/radar-read":
                try:
                    content_length = int(self.headers.get("Content-Length", "0"))
                    if content_length <= 0 or content_length > 20000:
                        raise ValueError("请求内容大小无效")
                    payload = json.loads(
                        self.rfile.read(content_length).decode("utf-8")
                    )
                    result = save_radar_read(
                        store,
                        str(payload.get("item_id", "")),
                        bool(payload.get("is_read", True)),
                    )
                    self._json(
                        {
                            "ok": True,
                            "data": result,
                            "github": sync_user_state(store),
                        }
                    )
                except (OSError, ValueError, TypeError, json.JSONDecodeError) as error:
                    self._json({"ok": False, "error": str(error)}, 400)
                return
            if route != "/api/progress":
                self._json({"ok": False, "error": "接口不存在"}, 404)
                return
            try:
                content_length = int(self.headers.get("Content-Length", "0"))
                if content_length <= 0 or content_length > 20000:
                    raise ValueError("请求内容大小无效")
                payload = json.loads(self.rfile.read(content_length).decode("utf-8"))
                result = save_progress(
                    store,
                    str(payload.get("chunk_id", "")),
                    str(payload.get("status", "")),
                    int(payload.get("confidence", 0)),
                    str(payload.get("notes", "")),
                )
                self._json(
                    {
                        "ok": True,
                        "data": result,
                        "github": sync_user_state(store),
                    }
                )
            except (OSError, ValueError, TypeError, json.JSONDecodeError) as error:
                self._json({"ok": False, "error": str(error)}, 400)

        def _serve_static(self, route: str) -> None:
            relative = "index.html" if route in {"", "/"} else route.lstrip("/")
            candidate = (WEB_ROOT / relative).resolve()
            if WEB_ROOT.resolve() not in candidate.parents and candidate != WEB_ROOT.resolve():
                self.send_error(403)
                return
            if not candidate.is_file():
                candidate = WEB_ROOT / "index.html"
            body = candidate.read_bytes()
            content_type = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
            if content_type.startswith("text/") or content_type in {
                "application/javascript",
                "application/json",
            }:
                content_type += "; charset=utf-8"
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-cache")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.end_headers()
            self.wfile.write(body)

    return KnowledgeHandler


def serve(
    store: KnowledgeStore,
    host: str = "127.0.0.1",
    port: int = 8765,
    max_port_attempts: int = 20,
) -> None:
    store.initialize()
    try:
        ensure_daily_update(store)
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as error:
        print("启动补漏更新失败：" + str(error), file=sys.stderr)
    if not (WEB_ROOT / "index.html").exists():
        raise FileNotFoundError("缺少 web/index.html")

    server: Optional[ThreadingHTTPServer] = None
    selected_port = port
    for candidate_port in range(port, port + max_port_attempts):
        try:
            server = ThreadingHTTPServer(
                (host, candidate_port), make_handler(store)
            )
            selected_port = candidate_port
            break
        except OSError:
            continue
    if server is None:
        raise OSError("没有可用端口")

    print("AI Knowledge 学习台：http://" + host + ":" + str(selected_port))
    print("按 Ctrl+C 停止服务")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
