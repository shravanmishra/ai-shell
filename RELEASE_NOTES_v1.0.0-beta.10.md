# ai-shell v1.0.0-beta.10

Natural-language → shell command translator running a **local** LLM.

## What's new since beta.9

Docs only — no code change.

- **Windows/Linux `[llama]` install guidance.** `llama-cpp-python` builds from C
  source when pip finds no prebuilt wheel, failing on machines without MSVC/CMake
  (`CMAKE_C_COMPILER not set`, `nmake`). README now shows the fix: point pip at
  llama-cpp-python's prebuilt-wheel index, and note that those wheels stop at
  Python 3.12.

## Install

```bash
# macOS, Apple Silicon
pipx install --force "/path/to/ai_shell_cli-1.0.0b10-py3-none-any.whl[mlx]"

# Windows / Linux / Intel Mac  (prebuilt llama.cpp wheel, no compiler needed)
pipx install --force \
  --pip-args "--extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu" \
  "/path/to/ai_shell_cli-1.0.0b10-py3-none-any.whl[llama]"
```

Prebuilt `llama-cpp-python` wheels require **Python ≤ 3.12** — on 3.13/3.14 use
`pipx install --python python3.12 ...`. Repo is private, so download the wheel
from the release assets first. Requires Python ≥ 3.10.

## Verify (optional)

```bash
shasum -a 256 -c SHA256SUMS.txt
```
