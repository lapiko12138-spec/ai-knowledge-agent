from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta, timezone
from html import unescape
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from .core import KnowledgeStore, _atomic_json


HF_PAPERS_URL = "https://huggingface.co/papers"
TRANSLATE_URL = "https://translate.googleapis.com/translate_a/single"
PODCAST_URL = "https://www.xiaoyuzhoufm.com/podcast/667d1ecfc13b46d76c3f64b8"
DATA_ROOT = Path(__file__).resolve().parent.parent / "data"
X_BEARER_TOKEN_PATH = (
    Path.home()
    / "Library"
    / "Application Support"
    / "AI Knowledge Agent"
    / "x-bearer-token"
)

DEFAULT_X_SOURCES = [
    {
        "handle": "karpathy",
        "name": "Andrej Karpathy",
        "role": "研究者 / 工程师",
        "focus": ["LLM", "AI Coding", "模型教育"],
    },
    {
        "handle": "simonw",
        "name": "Simon Willison",
        "role": "独立开发者",
        "focus": ["LLM Tools", "Agent", "AI Engineering"],
    },
    {
        "handle": "DrJimFan",
        "name": "Jim Fan",
        "role": "Research Lead",
        "focus": ["Robotics", "World Models", "Embodied AI"],
    },
    {
        "handle": "AndrewYNg",
        "name": "Andrew Ng",
        "role": "研究者 / 教育者",
        "focus": ["AI Education", "AI Product", "Industry"],
    },
    {
        "handle": "emollick",
        "name": "Ethan Mollick",
        "role": "研究者 / 教育者",
        "focus": ["AI Adoption", "AI Product", "Work"],
    },
    {
        "handle": "swyx",
        "name": "swyx",
        "role": "开发者 / 社区",
        "focus": ["AI Engineering", "Agent", "Developer Tools"],
    },
]

CONCEPT_PATTERNS = [
    ("World Models", ("world model", "world modeling")),
    ("Agent", ("agent", "agentic")),
    ("Memory", ("memory", "memorization")),
    ("Reinforcement Learning", ("reinforcement learning", " rl ", "reward")),
    ("Diffusion Models", ("diffusion",)),
    ("Multimodal", ("multimodal", "audio-video", "vision-language")),
    ("Video Generation", ("video generation", "video model", "streaming video")),
    ("Mixture of Experts", ("mixture-of-experts", "moe")),
    ("Post-training", ("post-training", "distillation")),
    ("AI Evaluation", ("benchmark", "evaluation", "reviewer")),
    ("Robotics", ("robot", "humanoid", "manipulation")),
]


def _sentences(value: str) -> List[str]:
    return [
        item.strip()
        for item in re.split(r"(?<=[.!?])\s+", value.strip())
        if item.strip()
    ]


def _find_sentence(sentences: Iterable[str], needles: Iterable[str]) -> str:
    lowered_needles = tuple(item.casefold() for item in needles)
    for sentence in sentences:
        lower = sentence.casefold()
        if any(needle in lower for needle in lowered_needles):
            return sentence
    return ""


def extract_concepts(title: str, summary: str, limit: int = 5) -> List[str]:
    haystack = " " + (title + " " + summary).casefold() + " "
    concepts = [
        concept
        for concept, patterns in CONCEPT_PATTERNS
        if any(pattern in haystack for pattern in patterns)
    ]
    return concepts[:limit]


def build_teaching_view(title: str, summary: str) -> Dict[str, Any]:
    sentences = _sentences(summary)
    problem = " ".join(sentences[:2])
    method = _find_sentence(
        sentences,
        ("we introduce", "we propose", "we present", "we develop", "our method"),
    )
    evidence = _find_sentence(
        sentences,
        (
            "achieves",
            "outperforms",
            "results show",
            "ablations show",
            "benchmark",
            "improves",
        ),
    )
    if not method and len(sentences) > 2:
        method = sentences[2]
    return {
        "research_question": problem or summary,
        "new_method": method or "摘要未明确给出方法句，需要进入论文正文确认。",
        "evidence": evidence or "摘要未给出可独立核验的实验结论，需要进入实验章节确认。",
        "limitation": "Daily Papers 摘要不等于完整评审；限制条件、数据边界与失败案例需回看正文。",
        "concepts": extract_concepts(title, summary),
    }


def parse_huggingface_daily_html(raw_html: str) -> List[Dict[str, Any]]:
    decoded = unescape(raw_html)
    marker = '"dailyPapers":'
    start = decoded.find(marker)
    if start < 0:
        raise ValueError("Hugging Face 页面中未找到 Daily Papers 数据")
    values, _ = json.JSONDecoder().raw_decode(decoded[start + len(marker) :])
    if not isinstance(values, list):
        raise ValueError("Hugging Face Daily Papers 数据格式无效")
    return values


def _normalize_papers(items: List[Dict[str, Any]], limit: int = 20) -> List[Dict[str, Any]]:
    normalized = []
    seen = set()
    for item in items:
        paper = item.get("paper") or {}
        paper_id = str(paper.get("id") or "").strip()
        if not paper_id or paper_id in seen:
            continue
        seen.add(paper_id)
        title = str(paper.get("title") or item.get("title") or "").strip()
        summary = str(paper.get("summary") or item.get("summary") or "").strip()
        authors = [
            str(author.get("name") or "").strip()
            for author in paper.get("authors", [])
            if str(author.get("name") or "").strip()
        ]
        organization = paper.get("organization") or item.get("organization") or {}
        upvotes = int(paper.get("upvotes") or 0)
        daily_date = str(paper.get("submittedOnDailyAt") or "")[:10]
        normalized.append(
            {
                "id": paper_id,
                "title": title,
                "summary": summary,
                "authors": authors[:8],
                "organization": organization.get("fullname")
                or organization.get("name")
                or "",
                "upvotes": upvotes,
                "comments": int(item.get("numComments") or 0),
                "daily_date": daily_date,
                "published_at": paper.get("publishedAt") or item.get("publishedAt") or "",
                "url": "https://huggingface.co/papers/" + paper_id,
                "thumbnail": item.get("thumbnail") or "",
                "project_page": paper.get("projectPage") or "",
                "github_repo": paper.get("githubRepo") or "",
                "teaching": build_teaching_view(title, summary),
            }
        )
    normalized.sort(key=lambda item: (-item["upvotes"], item["title"]))
    for rank, item in enumerate(normalized, start=1):
        item["rank"] = rank
        item["editorial_tier"] = (
            "focus" if rank <= 2 else "scan" if rank <= 15 else "archive"
        )
    return normalized[:limit]


def _load_json_file(path: Path) -> Dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def apply_paper_localizations(papers: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    localizations = _load_json_file(DATA_ROOT / "paper-localizations.json")
    for paper in papers:
        localized = localizations.get(paper["id"], {})
        paper["localized"] = {
            "status": "curated" if localized else "pending",
            "title_zh": localized.get("title_zh", ""),
            "summary_zh": localized.get("summary_zh", ""),
            "research_question_zh": localized.get("research_question_zh", ""),
            "new_method_zh": localized.get("new_method_zh", ""),
            "evidence_zh": localized.get("evidence_zh", ""),
            "editor_note": localized.get("editor_note", ""),
        }
    return papers


def _normalize_zh_translation(translated: str) -> str:
    replacements = {
        "零射击": "零样本",
        "少射击": "少样本",
        "代币": "token",
        "大型语言模型": "大语言模型",
        "视觉语言动作": "视觉-语言-动作",
        "长视野": "长时程",
    }
    for source, target in replacements.items():
        translated = translated.replace(source, target)
    return translated


def _translate_to_zh(value: str, timeout: int = 20) -> str:
    value = " ".join(value.split())
    if not value:
        return ""
    request = Request(
        TRANSLATE_URL,
        data=urlencode(
            {
                "client": "gtx",
                "sl": "en",
                "tl": "zh-CN",
                "dt": "t",
                "q": value,
            }
        ).encode("utf-8"),
        headers={
            "User-Agent": "AI-Knowledge-Agent/0.1",
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        },
        method="POST",
    )
    with urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, list) or not payload or not isinstance(payload[0], list):
        raise ValueError("翻译服务返回格式无效")
    translated = "".join(
        str(segment[0])
        for segment in payload[0]
        if isinstance(segment, list) and segment and segment[0]
    ).strip()
    if not translated:
        raise ValueError("翻译服务未返回中文内容")
    return _normalize_zh_translation(translated)


def ensure_paper_translations(
    store: KnowledgeStore,
    papers: List[Dict[str, Any]],
    timeout: int = 20,
) -> List[Dict[str, Any]]:
    cache_path = store.system_dir / "paper-translations.json"
    cache = _load_json_file(cache_path)
    changed = False
    for paper in papers:
        paper_id = str(paper.get("id") or "")
        title = str(paper.get("title") or "")
        summary = str(paper.get("summary") or "")
        cached = cache.get(paper_id, {})
        source_matches = (
            cached.get("source_title") == title
            and cached.get("source_summary") == summary
        )
        title_zh = str(cached.get("title_zh") or "") if source_matches else ""
        summary_zh = str(cached.get("summary_zh") or "") if source_matches else ""
        localized = paper.setdefault("localized", {})
        title_zh = _normalize_zh_translation(
            str(localized.get("title_zh") or title_zh)
        )
        summary_zh = _normalize_zh_translation(
            str(localized.get("summary_zh") or summary_zh)
        )
        try:
            if not title_zh:
                title_zh = _translate_to_zh(title, timeout=timeout)
            if not summary_zh:
                summary_zh = _translate_to_zh(summary, timeout=timeout)
        except (OSError, TimeoutError, ValueError, json.JSONDecodeError) as error:
            localized["translation_error"] = str(error)
        if title_zh:
            localized["title_zh"] = title_zh
        if summary_zh:
            localized["summary_zh"] = summary_zh
        localized["status"] = (
            "curated"
            if localized.get("research_question_zh")
            else "machine_translated"
            if title_zh and summary_zh
            else "pending"
        )
        if title_zh or summary_zh:
            translated_at = (
                str(cached.get("translated_at") or "")
                if source_matches
                and cached.get("title_zh") == title_zh
                and cached.get("summary_zh") == summary_zh
                else datetime.now(timezone.utc).isoformat(timespec="seconds")
            )
            record = {
                "source_title": title,
                "source_summary": summary,
                "title_zh": title_zh,
                "summary_zh": summary_zh,
                "provider": "google_translate",
                "translated_at": translated_at,
            }
            if cache.get(paper_id) != record:
                cache[paper_id] = record
                changed = True
    if changed:
        _atomic_json(cache_path, cache)
    return papers


def _x_api_json(
    path: str,
    bearer_token: str,
    params: Optional[Dict[str, Any]] = None,
    timeout: int = 20,
) -> Dict[str, Any]:
    url = "https://api.x.com/2/" + path.lstrip("/")
    if params:
        url += "?" + urlencode(params)
    request = Request(
        url,
        headers={
            "Authorization": "Bearer " + bearer_token,
            "User-Agent": "AI-Knowledge-Agent/0.1",
            "Accept": "application/json",
        },
    )
    with urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("X API 返回格式无效")
    return payload


def fetch_x_radar(
    bearer_token: Optional[str] = None,
    days: int = 7,
    posts_per_person: int = 5,
    timeout: int = 20,
) -> Dict[str, Any]:
    token = (bearer_token or os.getenv("X_BEARER_TOKEN") or "").strip()
    if not token:
        try:
            token = X_BEARER_TOKEN_PATH.read_text(encoding="utf-8").strip()
        except OSError:
            token = ""
    if not token:
        raise ValueError(
            "缺少 X_BEARER_TOKEN，无法刷新人物雷达；也未找到 "
            + str(X_BEARER_TOKEN_PATH)
        )
    now = datetime.now(timezone.utc)
    window_start = now - timedelta(days=days)
    people = []
    for source in DEFAULT_X_SOURCES:
        handle = source["handle"]
        user_payload = _x_api_json(
            "users/by/username/" + quote(handle),
            token,
            params={"user.fields": "name,description"},
            timeout=timeout,
        )
        user = user_payload.get("data") or {}
        user_id = str(user.get("id") or "")
        if not user_id:
            raise ValueError("X API 未找到用户 @" + handle)
        tweets_payload = _x_api_json(
            "users/" + quote(user_id) + "/tweets",
            token,
            params={
                "max_results": max(5, min(100, posts_per_person)),
                "start_time": window_start.isoformat(timespec="seconds").replace(
                    "+00:00", "Z"
                ),
                "exclude": "retweets,replies",
                "tweet.fields": "created_at,lang,public_metrics",
            },
            timeout=timeout,
        )
        viewpoints = []
        for item in tweets_payload.get("data") or []:
            text = " ".join(str(item.get("text") or "").split())
            tweet_id = str(item.get("id") or "")
            if not text or not tweet_id:
                continue
            sentences = _sentences(text)
            title = sentences[0] if sentences else text
            viewpoints.append(
                {
                    "id": "x-" + tweet_id,
                    "published_at": str(item.get("created_at") or "")[:10],
                    "type": "Source",
                    "title": title[:120],
                    "summary": text,
                    "original_excerpt": text,
                    "url": "https://x.com/" + handle + "/status/" + tweet_id,
                    "language": item.get("lang") or "",
                    "public_metrics": item.get("public_metrics") or {},
                }
            )
        people.append(
            {
                **source,
                "name": str(user.get("name") or source["name"]),
                "connection_status": "official_api",
                "viewpoints": viewpoints,
            }
        )
    topics = [
        {
            **item,
            "person_handle": person["handle"],
            "person_name": person["name"],
        }
        for person in people
        for item in person["viewpoints"]
    ]
    return {
        "status": "official_api",
        "message": "近 7 天观点已通过 X 官方 API 刷新。",
        "window_start": window_start.date().isoformat(),
        "window_end": now.date().isoformat(),
        "captured_at": now.isoformat(timespec="seconds"),
        "sources": people,
        "topics": topics,
    }


def load_x_radar_snapshot() -> Dict[str, Any]:
    snapshot = _load_json_file(DATA_ROOT / "x-radar-7d.json")
    if not snapshot:
        return {
            "status": "not_configured",
            "message": "尚未配置 X 官方 API，且没有可用的公开时间线快照。",
            "sources": [
                {**source, "connection_status": "awaiting_api", "viewpoints": []}
                for source in DEFAULT_X_SOURCES
            ],
            "topics": [],
        }
    people = snapshot.get("people", [])
    viewpoints = [
        {**item, "person_handle": person.get("handle"), "person_name": person.get("name")}
        for person in people
        for item in person.get("viewpoints", [])
    ]
    captured_at = str(snapshot.get("captured_at") or "")
    try:
        captured = datetime.fromisoformat(captured_at).astimezone(timezone.utc)
        stale = datetime.now(timezone.utc) - captured > timedelta(hours=24)
    except ValueError:
        stale = True
    return {
        "status": "stale_snapshot" if stale else "public_snapshot",
        "message": (
            "人物观点为缓存快照，截止 "
            + str(snapshot.get("window_end") or "未知日期")
            + "；配置 X_BEARER_TOKEN 后可每日自动刷新。"
            if stale
            else "近 7 天观点来自公开 X 个人主页快照。"
        ),
        "window_start": snapshot.get("window_start", ""),
        "window_end": snapshot.get("window_end", ""),
        "captured_at": snapshot.get("captured_at", ""),
        "sources": [
            {**person, "connection_status": "public_snapshot"}
            for person in people
        ],
        "topics": viewpoints,
    }


def refresh_x_radar() -> Dict[str, Any]:
    try:
        return fetch_x_radar()
    except (OSError, TimeoutError, ValueError, json.JSONDecodeError) as error:
        snapshot = load_x_radar_snapshot()
        snapshot["refresh_error"] = str(error)
        return snapshot


def fetch_huggingface_daily(
    timeout: int = 20,
    limit: int = 10,
    store: Optional[KnowledgeStore] = None,
) -> Dict[str, Any]:
    request = Request(
        HF_PAPERS_URL,
        headers={
            "User-Agent": "AI-Knowledge-Agent/0.1 (+local educational dashboard)",
            "Accept": "text/html",
        },
    )
    with urlopen(request, timeout=timeout) as response:
        raw_html = response.read().decode("utf-8", "replace")
    papers = apply_paper_localizations(
        _normalize_papers(parse_huggingface_daily_html(raw_html), limit=limit)
    )
    if store is not None:
        ensure_paper_translations(store, papers, timeout=timeout)
    daily_date = max((item["daily_date"] for item in papers), default="")
    return {
        "source": HF_PAPERS_URL,
        "daily_date": daily_date,
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "papers": papers,
    }


def _cache_is_fresh(path: Path, minutes: int) -> bool:
    if not path.exists():
        return False
    modified = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    return datetime.now(timezone.utc) - modified < timedelta(minutes=minutes)


def load_daily_intelligence(
    store: KnowledgeStore,
    refresh: bool = False,
    cache_minutes: int = 1440,
) -> Dict[str, Any]:
    cache_path = store.system_dir / "daily-intelligence.json"
    cached: Optional[Dict[str, Any]] = None
    if cache_path.exists():
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            cached = None

    if refresh or not _cache_is_fresh(cache_path, cache_minutes):
        try:
            hf = fetch_huggingface_daily(store=store)
            cached = {
                "version": 1,
                "huggingface": hf,
                "x_radar": refresh_x_radar(),
                "editorial_model": {
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
                },
            }
            _atomic_json(cache_path, cached)
        except (OSError, TimeoutError, ValueError, json.JSONDecodeError) as error:
            if cached is None:
                cached = {
                    "version": 1,
                    "huggingface": {
                        "source": HF_PAPERS_URL,
                        "daily_date": "",
                        "fetched_at": "",
                        "papers": [],
                        "error": str(error),
                    },
                    "x_radar": {**load_x_radar_snapshot()},
                    "editorial_model": {
                        "source": PODCAST_URL,
                        "daily_scan": 8,
                        "daily_choices": [5, 8, 10],
                        "daily_focus": 2,
                        "weekly_top": 5,
                        "monthly_top": 10,
                        "stages": ["全量扫描", "筛选", "教学拆解", "概念入图"],
                    },
                }
    if cached:
        if "x_radar" not in cached:
            cached["x_radar"] = load_x_radar_snapshot()
        papers = cached.get("huggingface", {}).get("papers", [])
        del papers[10:]
        apply_paper_localizations(papers)
        ensure_paper_translations(store, papers)
        cached.setdefault("editorial_model", {})["daily_scan"] = 8
        cached["editorial_model"]["daily_choices"] = [5, 8, 10]
    return cached or {}
