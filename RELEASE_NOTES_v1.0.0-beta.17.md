# ai-shell v1.0.0-beta.17

Natural-language → shell command translator running a **local** LLM.

## What's new since beta.16

- **"what is my current directory" now works on Windows.** The model was
  emitting `cd /d %cd%` — a no-op that prints nothing. Fixes:
  - `cd /d %cd%` / `cd %cd%` → `cd` (cmd) or `Get-Location` (PowerShell).
  - Few-shot examples added: `what is my current directory` → `cd` / `Get-Location`.
  - On the Windows dialects a bare `cd` now runs (cmd prints the working
    directory) instead of being intercepted as "chdir to home" — POSIX
    `cd` → home is unchanged.

## Install

```bash
# macOS, Apple Silicon
pipx install --force "/path/to/ai_shell_cli-1.0.0b17-py3-none-any.whl[mlx]"

# Windows / Linux / Intel Mac  (prebuilt llama.cpp wheel, no compiler needed)
pipx install --force \
  --pip-args "--extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu" \
  "/path/to/ai_shell_cli-1.0.0b17-py3-none-any.whl[llama]"
```

Prebuilt `llama-cpp-python` wheels need **Python ≤ 3.12**. Requires Python ≥ 3.10.

## Verify (optional)

```bash
shasum -a 256 -c SHA256SUMS.txt
```
