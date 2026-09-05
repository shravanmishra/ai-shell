# ai-shell v1.0.0-beta.13

Natural-language → shell command translator running a **local** LLM.

## What's new since beta.12

- **`find -exec` terminator repair.** The model would emit
  `find / -type f -size +50M -exec ls -lh {} \ 2>/dev/null` — a dangling `\`
  instead of the required `{} \;` — and the command got rejected as malformed.
  A new pass fixes `{} \`, a bare `{} ;`, and a missing terminator before a
  redirect / pipe / end of line, all to `{} \;`. Valid `{} \;` and `{} +` are
  left alone.

## Install

```bash
# macOS, Apple Silicon
pipx install --force "/path/to/ai_shell_cli-1.0.0b13-py3-none-any.whl[mlx]"

# Windows / Linux / Intel Mac  (prebuilt llama.cpp wheel, no compiler needed)
pipx install --force \
  --pip-args "--extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu" \
  "/path/to/ai_shell_cli-1.0.0b13-py3-none-any.whl[llama]"
```

Prebuilt `llama-cpp-python` wheels need **Python ≤ 3.12**. Requires Python ≥ 3.10.

## Verify (optional)

```bash
shasum -a 256 -c SHA256SUMS.txt
```
