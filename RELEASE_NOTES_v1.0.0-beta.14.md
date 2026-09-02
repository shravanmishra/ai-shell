# ai-shell v1.0.0-beta.14

Natural-language → shell command translator running a **local** LLM.

## What's new since beta.13

- **Conversation history is now in-memory only, and smaller.** Kept the last 5
  request/command exchanges (was 20 messages) so an immediate follow-up still
  works, but nothing is written to disk anymore. Removed
  `SHELLAI_PERSIST_HISTORY`, `SHELLAI_HISTORY_FILE`, the `history.json`
  load/save/wipe, and the readline seeding. A smaller window also keeps the
  1.5B model from being nudged off-track by stale earlier commands.

## Install

```bash
# macOS, Apple Silicon
pipx install --force "/path/to/ai_shell_cli-1.0.0b14-py3-none-any.whl[mlx]"

# Windows / Linux / Intel Mac  (prebuilt llama.cpp wheel, no compiler needed)
pipx install --force \
  --pip-args "--extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu" \
  "/path/to/ai_shell_cli-1.0.0b14-py3-none-any.whl[llama]"
```

Prebuilt `llama-cpp-python` wheels need **Python ≤ 3.12**. Requires Python ≥ 3.10.

## Verify (optional)

```bash
shasum -a 256 -c SHA256SUMS.txt
```
