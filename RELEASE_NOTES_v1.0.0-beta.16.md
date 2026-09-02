# ai-shell v1.0.0-beta.16

Natural-language → shell command translator running a **local** LLM.

## What's new since beta.15

- **"Combined / total size" now has a recipe.** The model had no pattern for
  "total size of all .txt files" and would just list them. Added a
  `SYSTEM_PROMPT_CORE` line plus few-shot examples to the macOS, Linux and
  PowerShell profiles:
  - POSIX: `find . -type f -name "*.txt" -exec du -ch {} + 2>/dev/null`
    (each file + a `total` line); append `| tail -1` for only the total.
  - PowerShell: `Measure-Object Length -Sum` formatted to MB.

## Install

```bash
# macOS, Apple Silicon
pipx install --force "/path/to/ai_shell_cli-1.0.0b16-py3-none-any.whl[mlx]"

# Windows / Linux / Intel Mac  (prebuilt llama.cpp wheel, no compiler needed)
pipx install --force \
  --pip-args "--extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu" \
  "/path/to/ai_shell_cli-1.0.0b16-py3-none-any.whl[llama]"
```

Prebuilt `llama-cpp-python` wheels need **Python ≤ 3.12**. Requires Python ≥ 3.10.

## Verify (optional)

```bash
shasum -a 256 -c SHA256SUMS.txt
```
