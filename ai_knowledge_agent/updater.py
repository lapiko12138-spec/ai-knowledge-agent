from __future__ import annotations

import fcntl
import json
import os
import plistlib
import shutil
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional

from .core import KnowledgeStore, _atomic_json
from .feeds import (
    PODCAST_URL,
    fetch_huggingface_daily,
    refresh_x_radar,
)
from .feishu import build_learning_reminder_card, send_card


SCHEDULE_LABEL = "com.ai-knowledge-agent.daily-update"
PROJECT_ROOT = Path(__file__).resolve().parent.parent
KNOWLEDGE_SNAPSHOT = PROJECT_ROOT / "knowledge"
DEFAULT_HOUR = 8
DEFAULT_MINUTE = 0


def _now() -> datetime:
    return datetime.now().astimezone()


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def notification_config_path(store: KnowledgeStore) -> Path:
    return store.system_dir / "notification-config.json"


def load_notification_config(store: KnowledgeStore) -> Dict[str, Any]:
    payload = _read_json(notification_config_path(store))
    return {
        "version": 1,
        "enabled": bool(payload.get("enabled", False)),
        "user_id": str(payload.get("user_id") or ""),
        "identity": str(payload.get("identity") or "bot"),
    }


def configure_notification(
    store: KnowledgeStore,
    user_id: str,
    identity: str = "bot",
    enabled: bool = True,
) -> Dict[str, Any]:
    user_id = user_id.strip()
    if enabled and not user_id:
        raise ValueError("启用飞书提醒时必须提供 user_id")
    if identity not in {"bot", "user"}:
        raise ValueError("飞书发送身份必须是 bot 或 user")
    config = {
        "version": 1,
        "enabled": enabled,
        "user_id": user_id,
        "identity": identity,
        "updated_at": _now().isoformat(timespec="seconds"),
    }
    store.initialize()
    _atomic_json(notification_config_path(store), config)
    return config


def _message_id(result: Dict[str, Any]) -> str:
    candidates = [
        result.get("message_id"),
        result.get("data", {}).get("message_id")
        if isinstance(result.get("data"), dict)
        else None,
        result.get("data", {}).get("message", {}).get("message_id")
        if isinstance(result.get("data"), dict)
        and isinstance(result.get("data", {}).get("message"), dict)
        else None,
    ]
    return next((str(item) for item in candidates if item), "")


def send_learning_reminder(
    store: KnowledgeStore,
    target: date,
    dry_run: bool = False,
) -> Dict[str, Any]:
    config = load_notification_config(store)
    if not config["enabled"]:
        return {"status": "disabled", "message": "飞书学习提醒未启用"}
    if not config["user_id"]:
        return {"status": "not_configured", "message": "缺少飞书 user_id"}
    card = build_learning_reminder_card(store, target)
    result = send_card(
        card,
        user_id=config["user_id"],
        identity=config["identity"],
        dry_run=dry_run,
        confirm_send=not dry_run,
        cwd=PROJECT_ROOT,
        idempotency_key="ai-learning-" + target.isoformat(),
    )
    return {
        "status": "dry_run" if dry_run else "success",
        "identity": config["identity"],
        "user_id": config["user_id"],
        "message_id": _message_id(result),
    }


def _editorial_model() -> Dict[str, Any]:
    return {
        "source": PODCAST_URL,
        "daily_scan": 8,
        "daily_choices": [5, 8, 10],
        "daily_focus": 2,
        "weekly_top": 5,
        "monthly_top": 10,
        "stages": [
            "全量扫描",
            "热度与相关性筛选",
            "教学拆解",
            "概念入图",
        ],
    }


def _ignore_snapshot_files(directory: str, names: list) -> set:
    ignored = set()
    for name in names:
        if name in {
            "logs",
            "daily-update.lock",
            "daily-update-status.json",
            "notification-config.json",
        }:
            ignored.add(name)
        elif name.endswith((".tmp", ".log", ".lock")):
            ignored.add(name)
    return ignored


def sync_knowledge_snapshot(store: KnowledgeStore) -> Dict[str, Any]:
    source = store.root.resolve()
    temporary = KNOWLEDGE_SNAPSHOT.with_name(".knowledge-sync.tmp")
    previous = KNOWLEDGE_SNAPSHOT.with_name(".knowledge-sync.previous")
    if temporary.exists():
        shutil.rmtree(temporary)
    shutil.copytree(source, temporary, ignore=_ignore_snapshot_files)
    if previous.exists():
        shutil.rmtree(previous)
    if KNOWLEDGE_SNAPSHOT.exists():
        KNOWLEDGE_SNAPSHOT.rename(previous)
    temporary.rename(KNOWLEDGE_SNAPSHOT)
    if previous.exists():
        shutil.rmtree(previous)
    files = [item for item in KNOWLEDGE_SNAPSHOT.rglob("*") if item.is_file()]
    return {"path": str(KNOWLEDGE_SNAPSHOT), "file_count": len(files)}


def _github_cli_path() -> Optional[Path]:
    candidates = [
        Path.home() / ".local" / "bin" / "gh",
        Path("/opt/homebrew/bin/gh"),
        Path("/usr/local/bin/gh"),
    ]
    return next((path for path in candidates if path.is_file()), None)


def sync_github(store: KnowledgeStore) -> Dict[str, Any]:
    lock_path = store.system_dir / "github-sync.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        return _sync_github_locked(store)


def _sync_github_locked(store: KnowledgeStore) -> Dict[str, Any]:
    if not (PROJECT_ROOT / ".git").exists():
        return {"status": "not_configured", "message": "本地 Git 仓库尚未初始化"}
    remote = subprocess.run(
        ["/usr/bin/git", "remote", "get-url", "origin"],
        cwd=str(PROJECT_ROOT),
        check=False,
        capture_output=True,
        text=True,
    )
    if remote.returncode != 0:
        return {"status": "not_configured", "message": "GitHub origin 尚未配置"}

    snapshot = sync_knowledge_snapshot(store)
    changed = subprocess.run(
        ["/usr/bin/git", "status", "--porcelain", "--", "knowledge"],
        cwd=str(PROJECT_ROOT),
        check=False,
        capture_output=True,
        text=True,
    )
    if changed.returncode != 0:
        return {"status": "failed", "message": changed.stderr.strip()}
    if not changed.stdout.strip():
        return {"status": "unchanged", **snapshot}

    staged = subprocess.run(
        ["/usr/bin/git", "add", "--", "knowledge"],
        cwd=str(PROJECT_ROOT),
        check=False,
        capture_output=True,
        text=True,
    )
    if staged.returncode != 0:
        return {"status": "failed", "message": staged.stderr.strip()}
    message = "chore: sync knowledge " + date.today().isoformat() + "\n"
    commit_environment = os.environ.copy()
    commit_environment.setdefault("GIT_AUTHOR_NAME", "AI Knowledge Agent")
    commit_environment.setdefault(
        "GIT_AUTHOR_EMAIL", "ai-knowledge-agent@users.noreply.github.com"
    )
    commit_environment.setdefault("GIT_COMMITTER_NAME", "AI Knowledge Agent")
    commit_environment.setdefault(
        "GIT_COMMITTER_EMAIL", "ai-knowledge-agent@users.noreply.github.com"
    )
    committed = subprocess.run(
        ["/usr/bin/git", "commit", "-F", "-"],
        cwd=str(PROJECT_ROOT),
        input=message,
        env=commit_environment,
        check=False,
        capture_output=True,
        text=True,
    )
    if committed.returncode != 0:
        return {"status": "failed", "message": committed.stderr.strip()}
    gh_path = _github_cli_path()
    if gh_path is None:
        return {"status": "failed", "message": "未找到 GitHub CLI"}
    credential_helper = "!" + str(gh_path) + " auth git-credential"
    pushed = subprocess.run(
        [
            "/usr/bin/git",
            "-c",
            "credential.https://github.com.helper=" + credential_helper,
            "push",
            "origin",
            "HEAD",
        ],
        cwd=str(PROJECT_ROOT),
        check=False,
        capture_output=True,
        text=True,
    )
    if pushed.returncode != 0:
        return {"status": "failed", "message": pushed.stderr.strip()}
    commit = subprocess.run(
        ["/usr/bin/git", "rev-parse", "--short", "HEAD"],
        cwd=str(PROJECT_ROOT),
        check=False,
        capture_output=True,
        text=True,
    )
    return {
        "status": "pushed",
        "commit": commit.stdout.strip(),
        "remote": remote.stdout.strip(),
        **snapshot,
    }


def update_status_path(store: KnowledgeStore) -> Path:
    return store.system_dir / "daily-update-status.json"


def load_update_status(store: KnowledgeStore) -> Dict[str, Any]:
    return _read_json(update_status_path(store))


def next_scheduled_run(
    now: Optional[datetime] = None,
    hour: int = DEFAULT_HOUR,
    minute: int = DEFAULT_MINUTE,
) -> datetime:
    current = now or _now()
    candidate = current.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate <= current:
        candidate += timedelta(days=1)
    return candidate


def update_daily(store: KnowledgeStore) -> Dict[str, Any]:
    store.initialize()
    lock_path = store.system_dir / "daily-update.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    started = _now()

    with lock_path.open("a+", encoding="utf-8") as lock_file:
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {
                "ok": False,
                "status": "already_running",
                "message": "每日更新任务正在运行",
            }

        status = {
            "version": 1,
            "status": "running",
            "started_at": started.isoformat(timespec="seconds"),
            "finished_at": "",
            "last_success_at": load_update_status(store).get("last_success_at", ""),
            "next_run_at": next_scheduled_run(started).isoformat(timespec="seconds"),
            "sources": {},
            "errors": [],
        }
        _atomic_json(update_status_path(store), status)

        cache_path = store.system_dir / "daily-intelligence.json"
        previous = _read_json(cache_path)
        huggingface = previous.get("huggingface", {})

        try:
            huggingface = fetch_huggingface_daily(limit=10)
            localized_count = sum(
                bool(item.get("localized", {}).get("title_zh"))
                for item in huggingface.get("papers", [])
            )
            status["sources"]["huggingface"] = {
                "status": "success",
                "paper_date": huggingface.get("daily_date", ""),
                "paper_count": len(huggingface.get("papers", [])),
                "localized_count": localized_count,
                "fetched_at": huggingface.get("fetched_at", ""),
            }
        except (OSError, TimeoutError, ValueError, json.JSONDecodeError) as error:
            status["sources"]["huggingface"] = {
                "status": "stale_cache" if huggingface else "failed",
                "paper_date": huggingface.get("daily_date", ""),
                "paper_count": len(huggingface.get("papers", [])),
            }
            status["errors"].append("Hugging Face: " + str(error))

        x_radar = refresh_x_radar()
        status["sources"]["x_radar"] = {
            "status": x_radar.get("status", "not_configured"),
            "window_start": x_radar.get("window_start", ""),
            "window_end": x_radar.get("window_end", ""),
            "captured_at": x_radar.get("captured_at", ""),
            "viewpoint_count": len(x_radar.get("topics", [])),
            "message": x_radar.get("message", ""),
        }

        intelligence = {
            "version": 1,
            "huggingface": huggingface,
            "x_radar": x_radar,
            "editorial_model": _editorial_model(),
            "updated_at": _now().isoformat(timespec="seconds"),
        }
        _atomic_json(cache_path, intelligence)

        digest_path = store.daily_digest(date.today())
        try:
            feishu = send_learning_reminder(store, date.today())
        except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as error:
            feishu = {"status": "failed", "message": str(error)}
            status["errors"].append("Feishu: " + str(error))
        status["sources"]["feishu"] = feishu

        github = sync_github(store)
        status["sources"]["github"] = github
        if github.get("status") == "failed":
            status["errors"].append(
                "GitHub: " + str(github.get("message") or "同步失败")
            )
        finished = _now()
        hf_success = status["sources"]["huggingface"]["status"] == "success"
        github_success = github.get("status") != "failed"
        feishu_success = feishu.get("status") != "failed"
        run_success = hf_success and github_success and feishu_success
        status.update(
            {
                "status": "success" if run_success else "partial",
                "finished_at": finished.isoformat(timespec="seconds"),
                "last_success_at": (
                    finished.isoformat(timespec="seconds")
                    if hf_success
                    else status["last_success_at"]
                ),
                "duration_seconds": round(
                    (finished - started).total_seconds(), 2
                ),
                "digest_path": str(digest_path),
            }
        )
        _atomic_json(update_status_path(store), status)
        return {"ok": run_success, **status}


def should_catch_up(store: KnowledgeStore, today: Optional[date] = None) -> bool:
    target = today or date.today()
    status = load_update_status(store)
    last_success = str(status.get("last_success_at") or "")
    return not last_success.startswith(target.isoformat())


def ensure_daily_update(store: KnowledgeStore) -> Dict[str, Any]:
    if should_catch_up(store):
        return update_daily(store)
    return {"ok": True, "status": "current", **load_update_status(store)}


def launch_agent_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / (
        SCHEDULE_LABEL + ".plist"
    )


def prepare_background_storage(vault: Path) -> Dict[str, Any]:
    store = KnowledgeStore(vault)
    store.initialize()
    source = store.root
    if source.is_symlink():
        return {
            "migrated": False,
            "link": str(source),
            "target": str(source.resolve()),
            "backup": "",
        }

    target = (
        Path.home()
        / "Library"
        / "Application Support"
        / "AI Knowledge Agent"
        / "Obsidian"
        / "AI Knowledge"
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, target, dirs_exist_ok=True)

    backup = source.parent / ".AI Knowledge-before-scheduler"
    if backup.exists():
        raise FileExistsError("后台存储迁移备份已存在：" + str(backup))
    source.rename(backup)
    try:
        source.symlink_to(target, target_is_directory=True)
    except OSError:
        backup.rename(source)
        raise
    return {
        "migrated": True,
        "link": str(source),
        "target": str(target),
        "backup": str(backup),
    }


def install_schedule(
    vault: Path,
    hour: int = DEFAULT_HOUR,
    minute: int = DEFAULT_MINUTE,
) -> Dict[str, Any]:
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError("计划时间无效")
    path = launch_agent_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    storage = prepare_background_storage(vault)
    store = KnowledgeStore(vault)
    store.initialize()
    logs_dir = store.system_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    plist = {
        "Label": SCHEDULE_LABEL,
        "ProgramArguments": [
            sys.executable,
            "-m",
            "ai_knowledge_agent",
            "--vault",
            str(vault.expanduser().resolve()),
            "update-daily",
        ],
        "WorkingDirectory": str(PROJECT_ROOT),
        "RunAtLoad": True,
        "StartCalendarInterval": {"Hour": hour, "Minute": minute},
        "StandardOutPath": str(logs_dir / "daily-update.out.log"),
        "StandardErrorPath": str(logs_dir / "daily-update.err.log"),
        "ProcessType": "Background",
        "EnvironmentVariables": {
            "PATH": (
                str(
                    Path.home()
                    / ".trae-cn"
                    / "plugins"
                    / "trae-remote-official"
                    / "lark"
                    / "1.0.5"
                    / "bin"
                )
                + ":/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
            )
        },
    }
    temporary = path.with_suffix(".plist.tmp")
    with temporary.open("wb") as handle:
        plistlib.dump(plist, handle, sort_keys=True)
    temporary.replace(path)

    domain = "gui/" + str(os.getuid())
    subprocess.run(
        ["/bin/launchctl", "bootout", domain + "/" + SCHEDULE_LABEL],
        check=False,
        capture_output=True,
        text=True,
    )
    loaded = subprocess.run(
        ["/bin/launchctl", "bootstrap", domain, str(path)],
        check=False,
        capture_output=True,
        text=True,
    )
    if loaded.returncode != 0:
        raise RuntimeError(loaded.stderr.strip() or "launchd 任务加载失败")
    return {
        "ok": True,
        "label": SCHEDULE_LABEL,
        "path": str(path),
        "hour": hour,
        "minute": minute,
        "next_run_at": next_scheduled_run(hour=hour, minute=minute).isoformat(
            timespec="seconds"
        ),
        "storage": storage,
    }


def schedule_info(store: KnowledgeStore) -> Dict[str, Any]:
    domain = "gui/" + str(os.getuid())
    result = subprocess.run(
        ["/bin/launchctl", "print", domain + "/" + SCHEDULE_LABEL],
        check=False,
        capture_output=True,
        text=True,
    )
    return {
        "installed": launch_agent_path().exists(),
        "loaded": result.returncode == 0,
        "label": SCHEDULE_LABEL,
        "path": str(launch_agent_path()),
        "update": load_update_status(store),
    }
