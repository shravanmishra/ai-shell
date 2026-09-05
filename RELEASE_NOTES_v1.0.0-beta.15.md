# ai-shell v1.0.0-beta.15

Natural-language → shell command translator running a **local** LLM.

## What's new since beta.14

- **`find … 2>/dev/null` no longer reports a bogus `[exit status 1]`.** `find`
  exits `1` just for skipping a directory it can't read; with `2>/dev/null` the
  user already asked for those errors to be suppressed, so the scan succeeded.
  ai-shell now treats that case as exit `0` — no failure note, and it doesn't
  trip the `↻ Fix it?` prompt. A non-`find` command that exits `1` is still a
  failure. (PowerShell had the equivalent fix in beta.8.)

## Install

```bash
# macOS, Apple Silicon
pipx install --force "/path/to/ai_shell_cli-1.0.0b15-py3-none-any.whl[mlx]"

# Windows / Linux / Intel Mac  (prebuilt llama.cpp wheel, no compiler needed)
pipx install --force \
  --pip-args "--extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu" \
  "/path/to/ai_shell_cli-1.0.0b15-py3-none-any.whl[llama]"
```

Prebuilt `llama-cpp-python` wheels need **Python ≤ 3.12**. Requires Python ≥ 3.10.

## Verify (optional)

```bash
shasum -a 256 -c SHA256SUMS.txt
```
