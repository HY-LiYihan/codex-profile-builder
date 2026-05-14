# Privacy Model

Codex Nuwa Memory reads local Codex history. That makes privacy the central design constraint.

## Defaults

- No network calls.
- No external Python dependencies.
- No writes unless `--apply` is passed.
- No raw secrets in output.

## Redacted Patterns

The CLI redacts likely:

- OpenAI-style `sk-...` keys.
- API key assignments.
- Token assignments.
- Bearer tokens.
- Private key blocks.
- Cookies and auth headers.
- Very long high-entropy strings.

Redaction is defense in depth, not a guarantee. The project should continue improving secret detection.

## Safe Persistence

The first persistence target is a managed `AGENTS.md` block. It should contain operational preferences, not raw history.

Do not persist:

- Real credentials.
- Complete sensitive commands.
- Internal service URLs or auth headers.
- Full logs.
- Identity, health, finance, legal, or psychological claims inferred from casual chat.

## Personality Reports

Vibe-check reports are entertainment and collaboration analytics. They should not be described as formal psychological assessments.
