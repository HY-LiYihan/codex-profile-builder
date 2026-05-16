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
    re.compile(r"\b[A-Za-z0-9_+=.-]{64,}\b"),
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


def is_auto_context_message(text: str) -> bool:
    stripped = text.lstrip()
    auto_prefixes = (
        "# AGENTS.md instructions",
        "<environment_context>",
        "<subagent_notification>",
        "<turn_aborted>",
    )
    return stripped.startswith(auto_prefixes)


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
            if is_auto_context_message(text):
                continue
            messages.append(Message(role=role, text=text, timestamp=str(event.get("timestamp") or "")))
            if len(messages) >= max_messages:
                break
    return messages


def hydrate_threads(threads: list[ThreadRecord], stats: RedactionStats, max_messages: int = 80) -> list[ThreadRecord]:
    for thread in threads:
        thread.title = redact(thread.title, stats)
        thread.cwd = redact(thread.cwd, stats)
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


def query_terms(query: str) -> list[str]:
    terms = re.findall(r"[A-Za-z0-9_.+-]+|[\u4e00-\u9fff]{2,}", query.lower())
    return list(dict.fromkeys(term for term in terms if term.strip()))


def compact_text(text: str, limit: int = 220) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    return text[: limit - 1] + "…" if len(text) > limit else text


def safe_display_text(text: str, limit: int = 220) -> str:
    if "[REDACTED_SECRET]" in text:
        return "[REDACTED_SENSITIVE_TITLE]"
    return compact_text(text, limit)


def first_snippet(messages: list[Message], terms: list[str], role: str = "user") -> str:
    candidates = [message.text for message in messages if role == "both" or message.role == role]
    lowered_terms = [term.lower() for term in terms]
    for text in candidates:
        low = text.lower()
        if any(term in low for term in lowered_terms):
            return compact_text(text)
    return compact_text(candidates[0]) if candidates else ""


def score_thread(thread: ThreadRecord, terms: list[str], max_updated: int) -> tuple[float, list[str], int]:
    title = thread.title.lower()
    cwd = thread.cwd.lower()
    user_text = "\n".join(message.text for message in thread.messages if message.role == "user").lower()
    assistant_text = "\n".join(message.text for message in thread.messages if message.role == "assistant").lower()
    lexical = 0.0
    matched = 0
    reasons: list[str] = []
    for term in terms:
        term_score = 0.0
        if term in title:
            term_score += 14
            reasons.append(f"title:{term}")
        if term in cwd:
            term_score += 8
            reasons.append(f"cwd:{term}")
        user_hits = user_text.count(term)
        assistant_hits = assistant_text.count(term)
        if user_hits:
            term_score += min(user_hits, 5) * 5
            reasons.append(f"user:{term}")
        if assistant_hits:
            term_score += min(assistant_hits, 5) * 1.2
            reasons.append(f"assistant:{term}")
        if term_score:
            matched += 1
            lexical += term_score
    if lexical == 0:
        return 0.0, [], 0
    coverage = matched / max(len(terms), 1)
    recency = max(0.0, 2.0 - ((max_updated - thread.updated_at) / 86400 / 30)) if max_updated else 0.0
    return lexical * (0.55 + coverage) + recency, reasons[:8], matched


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


def project_theme_details(threads: list[ThreadRecord], limit: int = 10) -> list[dict[str, object]]:
    grouped: dict[str, list[ThreadRecord]] = {}
    for thread in threads:
        if not thread.cwd:
            continue
        grouped.setdefault(thread.cwd, []).append(thread)
    details = []
    for cwd, items in sorted(grouped.items(), key=lambda item: len(item[1]), reverse=True)[:limit]:
        title_terms = Counter()
        for thread in items:
            for term in PROJECT_HINTS + TECH_TERMS + ACTION_TERMS:
                if term.lower() in thread.title.lower():
                    title_terms[term] += 1
        titles = [safe_display_text(thread.title, 90) for thread in sorted(items, key=lambda item: item.updated_at, reverse=True)[:3]]
        details.append(
            {
                "name": Path(cwd).name or cwd,
                "cwd": cwd,
                "threads": len(items),
                "recent_titles": titles,
                "signals": [term for term, _ in title_terms.most_common(6)],
            }
        )
    return details


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


def profile_metrics(threads: list[ThreadRecord], stats: RedactionStats) -> dict[str, object]:
    texts = [text for text in user_messages(threads) if is_natural_user_text(text)]
    lengths = [len(text) for text in texts]
    pronouns = count_terms(texts, ["你", "您", "我", "我们", "咱们"])
    scores = collaboration_scores(texts)
    action_terms = Counter(count_terms(texts, ACTION_TERMS)).most_common(14)
    tech_terms = Counter(count_terms(texts, TECH_TERMS)).most_common(12)
    question_ratio = (sum(1 for text in texts if "?" in text or "？" in text) / len(texts)) if texts else 0
    multi_step_ratio = (
        sum(1 for text in texts if any(marker in text for marker in ["首先", "其次", "然后", "同时", "第一", "第二"]))
        / len(texts)
        if texts
        else 0
    )
    return {
        "natural_user_messages": len(texts),
        "assistant_messages": len(assistant_messages(threads)),
        "avg_length": statistics.mean(lengths) if lengths else 0,
        "median_length": statistics.median(lengths) if lengths else 0,
        "question_ratio": question_ratio,
        "multi_step_ratio": multi_step_ratio,
        "pronouns": pronouns,
        "scores": scores,
        "collaboration_type": collaboration_type(scores),
        "action_terms": action_terms,
        "tech_terms": tech_terms,
        "redaction_hits": stats.hits,
        "project_details": project_theme_details(threads),
    }


def render_profile_report(threads: list[ThreadRecord], stats: RedactionStats, language: str = "zh") -> str:
    metrics = profile_metrics(threads, stats)
    block = agents_block(threads, stats).strip()
    if language == "en":
        projects = "\n".join(
            f"- `{item['name']}`: {item['threads']} thread(s). Signals: {', '.join(item['signals']) or 'general work'}. Recent: {'; '.join(item['recent_titles'])}"
            for item in metrics["project_details"]
        )
        actions = "\n".join(f"- {term}: {count}" for term, count in metrics["action_terms"])
        tech = "\n".join(f"- {term}: {count}" for term, count in metrics["tech_terms"])
        scores = "\n".join(f"- {name}: {value}" for name, value in sorted(metrics["scores"].items(), key=lambda item: item[1], reverse=True))
        pronouns = "\n".join(f"- {name}: {value}" for name, value in metrics["pronouns"].items())
        return f"""# Generated Agent Profile

This file was generated by Codex Profile Builder from local Codex history. It is a draft and does not replace any existing `AGENTS.md`.

## Executive Profile

- Collaboration type: {metrics['collaboration_type']}
- The user primarily collaborates in Chinese with English technical terms mixed in.
- The user prefers direct, actionable engineering guidance and clear implementation/verification loops.
- The user values bounded, incremental, privacy-aware memory updates.

## Preferred Agent Protocol

- Read relevant local context before making strong claims.
- Make a crisp judgment once enough evidence is available.
- Implement and verify when the request implies action.
- Use subagents for exploration, verification, large scans, and long-running checks when authorized.
- Keep progress updates short and informative.
- Never persist or print secrets, tokens, private keys, auth headers, or full sensitive commands.

## Project Map

{projects or '- No stable project themes detected.'}

## Communication Fingerprint

- Natural user messages: {metrics['natural_user_messages']}
- Assistant messages: {metrics['assistant_messages']}
- Average user-message length: {metrics['avg_length']:.1f} characters
- Median user-message length: {metrics['median_length']:.1f} characters
- Question-mark ratio: {metrics['question_ratio']:.1%}
- Multi-step instruction ratio: {metrics['multi_step_ratio']:.1%}
- Redaction hits: {metrics['redaction_hits']}

## Pronoun Style

{pronouns or '- No pronoun signal detected.'}

## Collaboration Scores

{scores}

## High-Signal Action Terms

{actions or '- No action signal detected.'}

## High-Signal Technical Terms

{tech or '- No technical signal detected.'}

## Memory Hygiene

- Do not persist API keys, tokens, secrets, private keys, cookies, auth headers, full sensitive commands, or raw logs.
- Do not infer medical, legal, financial, identity, or formal psychological facts from casual chat.
- Treat personality labels as collaboration analytics, not psychological assessment.
- Prefer concise, operational memory over biography.

## Candidate Managed Block

{block}
"""

    projects = "\n".join(
        f"- `{item['name']}`：{item['threads']} 个线程。信号：{('、'.join(item['signals']) if item['signals'] else '通用工作')}。近期标题：{'；'.join(item['recent_titles'])}"
        for item in metrics["project_details"]
    )
    actions = "\n".join(f"- {term}：{count}" for term, count in metrics["action_terms"])
    tech = "\n".join(f"- {term}：{count}" for term, count in metrics["tech_terms"])
    scores = "\n".join(f"- {name}：{value}" for name, value in sorted(metrics["scores"].items(), key=lambda item: item[1], reverse=True))
    pronouns = "\n".join(f"- {name}：{value}" for name, value in metrics["pronouns"].items())
    return f"""# 生成版 Agent 用户画像

本文件由 Codex Profile Builder 基于本机 Codex 历史生成。这是候选草案，不会替换任何现有的 `AGENTS.md`。

## 总体画像

- 协作类型：{metrics['collaboration_type']}
- 用户主要用中文与 Codex 协作，会自然混用英文技术术语。
- 用户偏好直接、有判断、可执行的工程建议，不喜欢只停留在抽象方案。
- 用户常从探索、检索或可行性判断开始，然后推进到实现、测试和总结闭环。
- 用户对 token 成本敏感，偏好限量、增量、可追溯、按需检索的处理方式。
- 用户把凭据和敏感命令输出视为记忆禁区。

## 推荐 Agent 协作协议

- 在做强判断前，先阅读相关代码、文档或本地状态。
- 一旦证据足够，要给出清晰判断，不要一直停留在模糊可能性。
- 当请求明显指向行动时，优先推进实现和验证，而不是只给建议。
- 在用户授权或明确要求时，用 subagent 并行处理探索、状态检查、验证、大规模扫描等任务。
- 工作过程中给用户简洁、有信息量的进度更新。
- 完成后总结改了什么、验证了什么、还有哪些风险。
- 不输出原始 secret、token、API key、auth header、私钥或完整敏感 shell 命令。

## 项目地图

{projects or '- 未检测到稳定项目主题。'}

## 沟通指纹

- 用户自然消息：{metrics['natural_user_messages']} 条。
- assistant 消息：{metrics['assistant_messages']} 条。
- 用户消息平均长度：{metrics['avg_length']:.1f} 字符。
- 用户消息中位长度：{metrics['median_length']:.1f} 字符。
- 问号比例：{metrics['question_ratio']:.1%}。
- 多步骤指令比例：{metrics['multi_step_ratio']:.1%}。
- 画像生成过程中的脱敏命中：{metrics['redaction_hits']} 次。

## 人称风格

{pronouns or '- 未检测到明显人称信号。'}

## 协作需求分布

{scores}

## 高频动作词

{actions or '- 未检测到明显动作信号。'}

## 高频技术词

{tech or '- 未检测到明显技术信号。'}

## AI 协作人格

类型：{metrics['collaboration_type']}

- 这是娱乐化协作分析，不是正式心理测评。
- 用户更像项目 owner 和研究合伙人，而不是被动问答用户。
- 用户经常先表达自己的判断，再把 agent 拉入共同推进状态。
- 用户很多问题不是用问号表达，而是用探索式指令或目标描述表达。
- 常见工作流：探索 -> 判断可行性 -> 设计 MVP -> 实现 -> 测试 -> 修正 -> 总结沉淀。

## 记忆卫生规则

- 不持久化 API key、token、secret、私钥、cookie、auth header、完整敏感命令或原始日志。
- 不从闲聊中推断医疗、法律、财务、身份或正式心理结论。
- AI 协作人格标签只作为娱乐化协作分析，不作为正式心理测评。
- 长期记忆应该简洁、可操作，不写成长篇传记。
- 优先做可追溯、增量式的小更新，不做一次性全历史大摘要。

## 可放入 AGENTS.md 的候选托管区块

{block}
"""


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


def search(args: argparse.Namespace) -> None:
    stats = RedactionStats()
    threads = hydrate_threads(load_threads(codex_home(args.codex_home), args.limit, args.since_days), stats, max_messages=args.max_messages)
    terms = query_terms(args.query)
    if not terms:
        raise SystemExit("No searchable query terms found")
    max_updated = max((thread.updated_at for thread in threads), default=0)
    scored = []
    for thread in threads:
        score, reasons, matched = score_thread(thread, terms, max_updated)
        if score <= 0:
            continue
        if args.require_all_terms and matched < len(terms):
            continue
        scored.append((score, thread, reasons, matched))
    scored.sort(key=lambda item: item[0], reverse=True)
    results = []
    for score, thread, reasons, matched in scored[: args.top]:
        results.append(
            {
                "score": round(score, 2),
                "matched_terms": matched,
                "thread_id": thread.id,
                "title": safe_display_text(thread.title, 160),
                "cwd": thread.cwd,
                "updated_at": unix_to_iso(thread.updated_at),
                "snippet": first_snippet(thread.messages, terms, args.snippet_role),
                "reasons": reasons,
            }
        )
    if args.json:
        print(json.dumps({"query": args.query, "terms": terms, "redaction_hits": stats.hits, "results": results}, ensure_ascii=False, indent=2))
        return
    print(f"Query: {args.query}")
    print(f"Terms: {', '.join(terms)}")
    print(f"Redaction hits: {stats.hits}")
    print("")
    for index, item in enumerate(results, 1):
        print(f"{index}. {item['title']}")
        print(f"   score={item['score']} matched={item['matched_terms']}/{len(terms)} cwd={item['cwd']}")
        print(f"   updated={item['updated_at']}")
        if item["snippet"]:
            print(f"   snippet={item['snippet']}")
        print(f"   reasons={', '.join(item['reasons'])}")


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


def profile_report(args: argparse.Namespace) -> None:
    stats = RedactionStats()
    threads = hydrate_threads(load_threads(codex_home(args.codex_home), args.limit, args.since_days), stats, max_messages=args.max_messages)
    report = render_profile_report(threads, stats, args.language)
    if args.output:
        path = Path(args.output).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(report, encoding="utf-8")
        print(f"Wrote profile report to {path}")
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

    search_parser = sub.add_parser("search", help="Search local Codex history with redaction and thread-level ranking")
    search_parser.add_argument("query")
    search_parser.add_argument("--limit", type=int, default=200, help="Maximum recent threads to scan")
    search_parser.add_argument("--since-days", type=int, default=None)
    search_parser.add_argument("--top", type=int, default=8)
    search_parser.add_argument("--max-messages", type=int, default=120)
    search_parser.add_argument("--require-all-terms", action="store_true")
    search_parser.add_argument("--snippet-role", choices=["user", "assistant", "both"], default="user")
    search_parser.add_argument("--json", action="store_true")
    search_parser.set_defaults(func=search)

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

    profile_parser = sub.add_parser("profile-report", help="Generate a detailed user profile and AGENTS.md candidate block")
    profile_parser.add_argument("--limit", type=int, default=120)
    profile_parser.add_argument("--since-days", type=int, default=None)
    profile_parser.add_argument("--max-messages", type=int, default=120)
    profile_parser.add_argument("--language", choices=["zh", "en"], default="zh")
    profile_parser.add_argument("--output", default=None)
    profile_parser.set_defaults(func=profile_report)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
