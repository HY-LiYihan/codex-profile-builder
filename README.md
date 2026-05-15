# Codex Profile Builder

Give Codex memory of you, without uploading your history.

Codex Profile Builder is a local-first Codex skill and CLI that reads your Codex Desktop history, redacts sensitive data, and turns repeated patterns into useful `AGENTS.md` memory. It also includes a playful `vibe-check` report that describes how you collaborate with AI.

## Why

Codex already has rich local history, but every new window can feel like it is meeting you for the first time. This project bridges that gap:

- It extracts stable collaboration preferences and project context.
- It updates only a managed block in `AGENTS.md`.
- It keeps token cost low by processing bounded batches.
- It treats privacy as a default, not an add-on.
- It creates shareable AI collaboration personality reports.

## Features

- Read Codex Desktop history from `~/.codex/state_5.sqlite` and rollout JSONL files.
- Parse only normal user/assistant messages.
- Redact API keys, tokens, bearer strings, private keys, cookies, and auth headers.
- Preview a managed `AGENTS.md` memory block.
- Apply updates only with `--apply`.
- Generate an `AI Collaboration Personality` vibe-check report.
- Run without external Python dependencies.

## Usage

From this repository:

```bash
python3 scripts/codex_profile_builder.py scan --limit 20
python3 scripts/codex_profile_builder.py search "AGENTS.md memory" --top 5
python3 scripts/codex_profile_builder.py agents-preview --limit 30
python3 scripts/codex_profile_builder.py vibe-check --limit 80
```

Apply to an `AGENTS.md` file only after reviewing the preview:

```bash
python3 scripts/codex_profile_builder.py agents-preview --limit 30 --agents-md ./AGENTS.md --apply
```

## Skill Install

Install as a Codex skill from GitHub:

```text
$skill-installer install https://github.com/HY-LiYihan/codex-profile-builder
```

Then ask Codex:

```text
Use $codex-profile-builder to preview an AGENTS.md memory update from my recent Codex history.
```

## Product Vision

This project has two complementary surfaces:

- Practical: a low-cost memory updater that makes future Codex sessions better.
- Playful: a shareable personality-style report about how you collaborate with AI.

The practical side creates retention. The playful side creates distribution.

See [docs/vision.md](docs/vision.md) for the deeper product direction.

## Privacy

Default behavior is read-only and dry-run. The CLI redacts secrets before producing summaries and never needs a cloud service. See [docs/privacy.md](docs/privacy.md).

## Development

Validate the skill and run the zero-dependency test suite:

```bash
python3 /path/to/skill-creator/scripts/quick_validate.py .
python3 -m unittest discover -s tests -v
python3 -m py_compile scripts/codex_profile_builder.py
```

## Status

MVP. The current implementation is heuristic and local-only. It is intended as a safe base for a later LLM-assisted summarization layer.
