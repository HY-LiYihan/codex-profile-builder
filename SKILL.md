---
name: codex-profile-builder
description: |
  Build local-first memory from Codex Desktop history. Use when the user asks to understand their prior Codex conversations, update AGENTS.md memory, summarize work habits, extract stable project/user preferences, or generate an AI collaboration personality/vibe-check report. Trigger phrases include "profile builder", "read my Codex history", "update AGENTS.md", "what do you know about me", "AI collaboration personality", and "vibe-check".
---

# Codex Profile Builder

Codex Profile Builder turns local Codex Desktop history into two outputs:

1. Practical memory: stable preferences, project themes, and workflows that can be patched into `AGENTS.md`.
2. Playful insight: an "AI collaboration personality" report based on how the user talks to agents.

The skill is local-first. It reads Codex history from the user's machine, redacts sensitive strings, and defaults to dry-run previews.

## Safety Rules

- Never print, persist, or summarize real API keys, tokens, bearer strings, private keys, cookies, auth headers, or complete sensitive commands.
- Prefer recent and relevant sessions. Do not load all history into context unless the user explicitly asks for a full audit.
- Only parse normal `user` and `assistant` message items from rollout JSONL. Ignore system/developer/tool schema content.
- Treat personality reports as entertainment and collaboration-style analysis, not clinical or psychological diagnosis.
- When updating `AGENTS.md`, only replace the managed block between:
  - `<!-- codex-profile-builder:start -->`
  - `<!-- codex-profile-builder:end -->`
- Default to `--dry-run`. Use `--apply` only when the user explicitly asks to write changes.

## Quick Workflow

1. Inspect current memory:

   ```bash
   python3 scripts/codex_profile_builder.py scan --limit 20
   ```

2. Preview an `AGENTS.md` memory block:

   ```bash
   python3 scripts/codex_profile_builder.py agents-preview --limit 30
   ```

3. Search relevant history before summarizing:

   ```bash
   python3 scripts/codex_profile_builder.py search "AGENTS.md memory" --top 5
   ```

4. Generate a playful collaboration report:

   ```bash
   python3 scripts/codex_profile_builder.py vibe-check --limit 80
   ```

5. Apply a managed block only after the user approves:

   ```bash
   python3 scripts/codex_profile_builder.py agents-preview --limit 30 --agents-md ./AGENTS.md --apply
   ```

## What To Extract

Good long-term memories:

- Collaboration preferences that appear repeatedly or were explicitly requested.
- Stable project names and project roles.
- Durable workflow patterns, such as "read first, plan, implement, verify, summarize".
- Privacy, token-budget, and tooling preferences.
- How the user wants main agents and subagents to coordinate.

Avoid:

- Secrets and credentials.
- Temporary errors, one-off logs, raw command output, or complete shell snippets with sensitive env vars.
- Overconfident personal claims not supported by repeated evidence.
- Medical, legal, financial, or identity claims inferred from casual language.

## Recommended Output Shape

For `AGENTS.md`, keep memory short and operational:

```md
<!-- codex-profile-builder:start -->

## User Collaboration Preferences

- ...

## Long-Running Project Themes

- ...

<!-- codex-profile-builder:end -->
```

For vibe-check reports, present the result as a fun collaboration profile:

```text
AI Collaboration Type: Architect Director
Workflow Loop: Explore -> Judge -> Build -> Verify -> Distill
```

Always include a short note that the report is based only on Codex chat behavior.
