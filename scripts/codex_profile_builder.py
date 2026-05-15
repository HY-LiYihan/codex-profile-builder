#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import statistics
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


START_MARKER = "<!-- codex-profile-builder:start -->"
END_MARKER = "<!-- codex-profile-builder:end -->"

SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_-]{12,}"),
    re.compile(r"(?i)\b(api[_-]?key|token|secret|password|passwd)\s*[:=]\s*[^\s'\"`]+"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{12,}"),
    re.compile(r"(?is)-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"(?i)\b(cookie|authorization)\s*:\s*[^\n]+"),
    re.compile(r"\b[A-Za-z0-9_/-]{48,}\b"),
]

TECH_TERMS = [
    "Codex",
    "AGENTS.md",
    "skill",
    "plugin",
    "GitHub",
    "PR",
    "CI",
    "MCP",
    "provider",
    "OpenAI",
    "Claude",
    "RAG",
    "SQLite",
    "rollout",
    "subagent",
    "agent",
]

ACTION_TERMS = [
    "研究",
    "检索",
    "查",
    "看",
    "阅读",
    "分析",
    "讲解",
    "总结",
    "整理",
    "设计",
    "实现",
    "改",
    "修",
    "写",
    "生成",
    "测试",
    "验证",
    "跑",
    "审查",
    "推送",
]

PROJECT_HINTS = [
    "rosetta",
    "rosetta-docs-agent",
    "rlt-openpi",
    "venom_vnv",
    "agent-bootstrap",
    "CodexPlusPlus",
    "OpenWebUI",
    "pointlio",
    "Isaac",
    "Zotero",
]


@dataclass
class Message:
    role: str
    text: str
    timestamp: str = ""


@dataclass
class ThreadRecord:
    id: str
    title: str
    cwd: str
    updated_at: int
    rollout_path: Path
    messages: list[Message] = field(default_factory=list)


@dataclass
class RedactionStats:
    hits: int = 0


def codex_home(path: str | None) -> Path:
    return Path(path).expanduser() if path else Path.home() / ".codex"


def redact(text: str, stats: RedactionStats | None = None) -> str:
    redacted = text
    for pattern in SECRET_PATTERNS:
        redacted, count = pattern.subn("[REDACTED_SECRET]", redacted)
        if stats is not None:
            stats.hits += count
    return redacted


def unix_to_iso(value: int) -> str:
    if not value:
        return ""
    try:
        return datetime.fromtimestamp(value, tz=timezone.utc).isoformat()
    except (OSError, OverflowError, ValueError):
        return ""


def load_threads(home: Path, limit: int | None = None, since_days: int | None = None) -> list[ThreadRecord]:
    db_path = home / "state_5.sqlite"
    if not db_path.exists():
        raise SystemExit(f"Codex database not found: {db_path}")

    where = ""
    params: list[object] = []
    if since_days:
        cutoff = int(datetime.now(tz=timezone.utc).timestamp()) - since_days * 24 * 60 * 60
        where = "where updated_at >= ?"
        params.append(cutoff)

    sql = f"""
        select id, title, cwd, updated_at, rollout_path
        from threads
        {where}
        order by updated_at desc
    """
    if limit:
        sql += " limit ?"
        params.append(limit)

    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute(sql, params).fetchall()
    finally:
        con.close()

    return [
        ThreadRecord(
            id=str(row["id"]),
            title=str(row["title"] or ""),
            cwd=str(row["cwd"] or ""),
            updated_at=int(row["updated_at"] or 0),
            rollout_path=Path(str(row["rollout_path"] or "")),
        )
        for row in rows
    ]


def message_text(payload: dict[str, object], stats: RedactionStats) -> str:
    content = payload.get("content")
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        if block.get("type") not in {"input_text", "output_text"}:
            continue
        text = str(block.get("text") or "")
        if text:
            parts.append(redact(text, stats))
    return "\n".join(parts).strip()


def parse_rollout(path: Path, stats: RedactionStats, max_messages: int = 80) -> list[Message]:
    messages: list[Message] = []
    if not path.is_file():
        return messages
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("type") != "response_item":
                continue
            payload = event.get("payload")
            if not isinstance(payload, dict) or payload.get("type") != "message":
                continue
            role = str(payload.get("role") or "")
            if role not in {"user", "assistant"}:
                continue
            text = message_text(payload, stats)
            if not text:
                continue
            messages.append(Message(role=role, text=text, timestamp=str(event.get("timestamp") or "")))
            if len(messages) >= max_messages:
                break
    return messages


def hydrate_threads(threads: list[ThreadRecord], stats: RedactionStats, max_messages: int = 80) -> list[ThreadRecord]:
    for thread in threads:
        thread.messages = parse_rollout(thread.rollout_path, stats, max_messages=max_messages)
    return threads


def user_messages(threads: Iterable[ThreadRecord]) -> list[str]:
    return [m.text for t in threads for m in t.messages if m.role == "user"]


def assistant_messages(threads: Iterable[ThreadRecord]) -> list[str]:
    return [m.text for t in threads for m in t.messages if m.role == "assistant"]


def is_natural_user_text(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    if len(stripped) > 5000:
        return False
    noisy_markers = ["<environment_context>", "<INSTRUCTIONS>", "```", "Traceback", "BEGIN ", "PRIVATE KEY"]
    return not any(marker in stripped for marker in noisy_markers)


def count_terms(texts: Iterable[str], terms: Iterable[str]) -> dict[str, int]:
    joined = "\n".join(texts)
    return {term: joined.count(term) for term in terms if joined.count(term)}


def top_cwds(threads: Iterable[ThreadRecord], limit: int = 10) -> list[tuple[str, int]]:
    counts = Counter(t.cwd for t in threads if t.cwd)
    return counts.most_common(limit)


def infer_project_themes(threads: list[ThreadRecord]) -> list[str]:
    cwd_counts = top_cwds(threads, 8)
    themes: list[str] = []
    for cwd, count in cwd_counts:
        name = Path(cwd).name or cwd
        if name == str(Path.home().name):
            continue
        themes.append(f"- `{name}`: appears in {count} recent Codex thread(s).")
    return themes


def infer_preferences(texts: list[str]) -> list[str]:
    joined = "\n".join(texts)
    prefs = [
        "- User often collaborates in Chinese, with English technical terms mixed in.",
        "- User prefers direct, actionable engineering guidance over abstract suggestions.",
    ]
    if joined.count("subagent") + joined.count("sub agent") + joined.count("Agent") > 5:
        prefs.append("- User values main-agent decision making with subagents for exploration, verification, and long-running checks.")
    if joined.count("验证") + joined.count("测试") + joined.count("跑") > 10:
        prefs.append("- User cares about verification, tests, and closing the loop after implementation.")
    if joined.count("token") + joined.count("成本") + joined.count("限量") > 3:
        prefs.append("- User is sensitive to token cost and prefers bounded, incremental processing.")
    if joined.count("隐私") + joined.count("token") + joined.count("key") + joined.count("secret") > 5:
        prefs.append("- User treats credentials and sensitive command output as memory-exclusion zones.")
    if joined.count("AGENTS.md") + joined.count("skill") + joined.count("plugin") > 5:
        prefs.append("- User is actively shaping Codex skills, plugins, AGENTS.md workflows, and local memory tooling.")
    return prefs


def agents_block(threads: list[ThreadRecord], stats: RedactionStats) -> str:
    texts = [text for text in user_messages(threads) if is_natural_user_text(text)]
    preferences = infer_preferences(texts)
    themes = infer_project_themes(threads)
    updated = datetime.now().strftime("%Y-%m-%d")

    lines = [
        START_MARKER,
        "",
        "## User Collaboration Preferences",
        "",
        *preferences,
        "",
        "## Long-Running Project Themes",
        "",
        *(themes or ["- No stable project themes detected in the selected history window."]),
        "",
        "## Memory Hygiene",
        "",
        "- Do not persist API keys, tokens, secrets, private keys, auth headers, full sensitive commands, or raw logs.",
        "- Prefer small, source-aware, incremental memory updates over full-history summaries.",
        "",
        "## Last Updated",
        "",
        f"- {updated}",
        f"- Redaction hits while preparing this preview: {stats.hits}",
        "",
        END_MARKER,
    ]
    return "\n".join(lines) + "\n"


def replace_managed_block(existing: str, block: str) -> str:
    if START_MARKER in existing and END_MARKER in existing:
        pattern = re.compile(re.escape(START_MARKER) + r".*?" + re.escape(END_MARKER), re.DOTALL)
        return pattern.sub(block.strip(), existing) + ("\n" if existing.endswith("\n") else "")
    separator = "\n\n" if existing.strip() else ""
    return existing.rstrip() + separator + block


def collaboration_scores(texts: list[str]) -> dict[str, int]:
    joined = "\n".join(texts)
    categories = {
        "execution": ["实现", "改", "修", "写", "生成", "跑", "推送", "提交"],
        "research": ["研究", "检索", "查", "阅读", "调研", "找"],
        "verification": ["验证", "测试", "审查", "review", "CI", "PR"],
        "orchestration": ["agent", "Agent", "subagent", "并行", "主 agent", "工作流"],
        "co_creation": ["我想", "我希望", "方案", "设计", "产品", "爆火", "MVP"],
        "learning": ["讲解", "解释", "是什么", "原理", "学习"],
    }
    return {name: sum(joined.count(term) for term in terms) for name, terms in categories.items()}


def collaboration_type(scores: dict[str, int]) -> str:
    top = sorted(scores.items(), key=lambda item: item[1], reverse=True)[:3]
    names = [name for name, _ in top]
    if "orchestration" in names and "execution" in names:
        return "Architect Director"
    if "research" in names and "learning" in names:
        return "Research Cartographer"
    if "co_creation" in names and "execution" in names:
        return "Product Builder"
    if "verification" in names and "execution" in names:
        return "Quality Shipper"
    return "AI Power Collaborator"


def render_vibe_report(threads: list[ThreadRecord], stats: RedactionStats) -> str:
    texts = [text for text in user_messages(threads) if is_natural_user_text(text)]
    joined = "\n".join(texts)
    lengths = [len(text) for text in texts]
    scores = collaboration_scores(texts)
    type_name = collaboration_type(scores)
    pronouns = count_terms(texts, ["你", "您", "我", "我们", "咱们"])
    actions = Counter(count_terms(texts, ACTION_TERMS)).most_common(12)
    tech = Counter(count_terms(texts, TECH_TERMS)).most_common(10)
    question_ratio = (sum(1 for text in texts if "?" in text or "？" in text) / len(texts)) if texts else 0
    multi_step_ratio = (
        sum(1 for text in texts if any(marker in text for marker in ["首先", "其次", "然后", "同时", "第一", "第二"]))
        / len(texts)
        if texts
        else 0
    )
    avg_len = statistics.mean(lengths) if lengths else 0
    median_len = statistics.median(lengths) if lengths else 0

    score_lines = [f"- {name}: {value}" for name, value in sorted(scores.items(), key=lambda item: item[1], reverse=True)]
    action_lines = [f"- {term}: {value}" for term, value in actions]
    tech_lines = [f"- {term}: {value}" for term, value in tech]
    pronoun_lines = [f"- {term}: {value}" for term, value in pronouns.items()]

    return "\n".join(
        [
            "# AI Collaboration Personality",
            "",
            f"Type: **{type_name}**",
            "",
            "This is an entertainment-style collaboration report based only on local Codex chat behavior. It is not a psychological diagnosis.",
            "",
            "## Signature",
            "",
            f"- Natural user-message sample: {len(texts)}",
            f"- Average length: {avg_len:.1f} characters",
            f"- Median length: {median_len:.1f} characters",
            f"- Question-mark ratio: {question_ratio:.1%}",
            f"- Multi-step instruction ratio: {multi_step_ratio:.1%}",
            f"- Redaction hits before report generation: {stats.hits}",
            "",
            "## Pronoun Style",
            "",
            *(pronoun_lines or ["- No pronoun signal detected."]),
            "",
            "## Collaboration Scores",
            "",
            *score_lines,
            "",
            "## Common Action Words",
            "",
            *(action_lines or ["- No action terms detected."]),
            "",
            "## Technical Surface",
            "",
            *(tech_lines or ["- No technical terms detected."]),
            "",
            "## Suggested Agent Pairing",
            "",
            "The user likely benefits from an agent that can read context first, make a crisp judgment, implement, verify, and summarize the result with privacy awareness.",
            "",
        ]
    )


def scan(args: argparse.Namespace) -> None:
    stats = RedactionStats()
    threads = hydrate_threads(load_threads(codex_home(args.codex_home), args.limit, args.since_days), stats)
    users = user_messages(threads)
    assistants = assistant_messages(threads)
    payload = {
        "threads": len(threads),
        "user_messages": len(users),
        "assistant_messages": len(assistants),
        "redaction_hits": stats.hits,
        "top_cwds": top_cwds(threads, args.top),
        "action_terms": count_terms([t for t in users if is_natural_user_text(t)], ACTION_TERMS),
        "tech_terms": count_terms([t for t in users if is_natural_user_text(t)], TECH_TERMS),
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    print(f"Threads: {payload['threads']}")
    print(f"User messages: {payload['user_messages']}")
    print(f"Assistant messages: {payload['assistant_messages']}")
    print(f"Redaction hits: {payload['redaction_hits']}")
    print("\nTop project paths:")
    for cwd, count in payload["top_cwds"]:
        print(f"- {count:>3} {cwd}")


def agents_preview(args: argparse.Namespace) -> None:
    stats = RedactionStats()
    threads = hydrate_threads(load_threads(codex_home(args.codex_home), args.limit, args.since_days), stats)
    block = agents_block(threads, stats)
    if not args.apply:
        print(block)
        return
    if not args.agents_md:
        raise SystemExit("--apply requires --agents-md")
    path = Path(args.agents_md).expanduser()
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    path.write_text(replace_managed_block(existing, block), encoding="utf-8")
    print(f"Updated managed memory block in {path}")


def vibe_check(args: argparse.Namespace) -> None:
    stats = RedactionStats()
    threads = hydrate_threads(load_threads(codex_home(args.codex_home), args.limit, args.since_days), stats)
    report = render_vibe_report(threads, stats)
    if args.output:
        path = Path(args.output).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(report, encoding="utf-8")
        print(f"Wrote vibe-check report to {path}")
        return
    print(report)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Local-first Codex history memory and AI collaboration reports")
    parser.add_argument("--codex-home", default=None, help="Codex home directory, default ~/.codex")
    sub = parser.add_subparsers(dest="command", required=True)

    scan_parser = sub.add_parser("scan", help="Summarize local Codex history without writing files")
    scan_parser.add_argument("--limit", type=int, default=20)
    scan_parser.add_argument("--since-days", type=int, default=None)
    scan_parser.add_argument("--top", type=int, default=10)
    scan_parser.add_argument("--json", action="store_true")
    scan_parser.set_defaults(func=scan)

    agents_parser = sub.add_parser("agents-preview", help="Preview or apply an AGENTS.md managed memory block")
    agents_parser.add_argument("--limit", type=int, default=30)
    agents_parser.add_argument("--since-days", type=int, default=None)
    agents_parser.add_argument("--agents-md", default=None)
    agents_parser.add_argument("--apply", action="store_true")
    agents_parser.set_defaults(func=agents_preview)

    vibe_parser = sub.add_parser("vibe-check", help="Generate an AI collaboration personality report")
    vibe_parser.add_argument("--limit", type=int, default=80)
    vibe_parser.add_argument("--since-days", type=int, default=None)
    vibe_parser.add_argument("--output", default=None)
    vibe_parser.set_defaults(func=vibe_check)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
