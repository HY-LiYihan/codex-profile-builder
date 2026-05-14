# Vision

Codex Nuwa Memory is built around a simple observation:

> Codex history contains enough signal to understand how a user works, but that signal is trapped in past sessions.

The project should make that signal useful without making users feel watched, exposed, or charged for a giant summarization job.

## Core Product

The serious product is an `AGENTS.md` memory updater:

1. Scan local Codex history.
2. Parse only normal user/assistant messages.
3. Redact sensitive information.
4. Extract stable preferences, project themes, and workflow patterns.
5. Preview a short managed block.
6. Apply only after explicit approval.

The best output is not a huge biography. It is a compact operating manual that helps future agents collaborate better.

## Growth Hook

The playful product is `vibe-check`:

- How do you talk to AI?
- Are you directive, exploratory, reflective, or orchestration-heavy?
- Do you treat AI like a tool, teammate, reviewer, teacher, or research partner?
- What is your "AI Collaboration Type"?

This is not a clinical personality test. It is a collaboration-style mirror, borrowing presentation ideas from MBTI, Big Five, DiSC, and language-style analytics.

## Design Principles

- Local-first by default.
- Dry-run by default.
- Bounded batches by default.
- Redaction before summarization.
- Sources and timestamps over vague memory.
- `AGENTS.md` as the first persistence layer.
- Optional richer indexes later.

## What Makes It Different

Most memory tools start remembering today. Codex Nuwa Memory can wake up the history the user already has.

That makes the first-run experience unusually strong:

> Install it, scan recent Codex history, and immediately get a useful collaboration profile.

## Future Directions

- FTS5 index for local search over redacted messages.
- LLM-assisted consolidation with strict token budgets.
- Per-project memory blocks.
- Memory diff review UI.
- Exportable personality report cards.
- Optional support for Claude Code, Cursor, ChatGPT exports, and other AI chat histories.
