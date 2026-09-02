# ai-shell v1.0.0-beta.12

Natural-language → shell command translator running a **local** LLM.

## What's new since beta.11

- Dropped the `model  Qwen2.5-Coder-1.5B-Instruct-4bit` line from the startup
  box. The box now shows only the platform plus the key bindings.

## Install

```bash
# macOS, Apple Silicon
pipx install --force "/path/to/ai_shell_cli-1.0.0b12-py3-none-any.whl[mlx]"

# Windows / Linux / Intel Mac  (prebuilt llama.cpp wheel, no compiler needed)
pipx install --force \
  --pip-args "--extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu" \
  "/path/to/ai_shell_cli-1.0.0b12-py3-none-any.whl[llama]"
```

Prebuilt `llama-cpp-python` wheels need **Python ≤ 3.12**. Repo is private, so
grab the wheel from the release assets first. Requires Python ≥ 3.10.

## Verify (optional)

```bash
shasum -a 256 -c SHA256SUMS.txt
```
