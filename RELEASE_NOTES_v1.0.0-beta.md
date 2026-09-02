# ai-shell v1.0.0-beta

Natural-language → shell command translator running a **local** LLM. Nothing
leaves your machine. This beta ships the first `1.0` release candidate line.

## Install (from this release)

Download `ai_shell_cli-1.0.0b0-py3-none-any.whl` from the assets below, then
install it into an isolated environment with [pipx](https://pipx.pypa.io) and
pick the backend for your machine:

```bash
# macOS, Apple Silicon (MLX)
pipx install "ai_shell_cli-1.0.0b0-py3-none-any.whl[mlx]"

# Linux / Windows / Intel Mac (llama.cpp)
pipx install "ai_shell_cli-1.0.0b0-py3-none-any.whl[llama]"
```

Or install straight from GitHub without downloading first:

```bash
pipx install "ai-shell-cli[mlx] @ https://github.com/shravanmishra/ai-shell/releases/download/v1.0.0-beta/ai_shell_cli-1.0.0b0-py3-none-any.whl"
```

Plain `pip` into a virtualenv works too:

```bash
python -m venv .venv && source .venv/bin/activate
pip install "./ai_shell_cli-1.0.0b0-py3-none-any.whl[mlx]"
```

Requires Python ≥ 3.10. The model (`Qwen2.5-Coder-1.5B`, ~1 GB, 4-bit) runs
fully locally and downloads once on first run into `~/.cache/ai-shell/`.

## Verify the download (optional)

```bash
shasum -a 256 -c SHA256SUMS.txt
```

## Quick start

```bash
ai-shell                                   # interactive shell
ai-shell "count the python files here"      # one-shot: translate, confirm, run
ai-shell -p "delete node_modules everywhere"  # print only, don't run
```

## Notes

- Backend auto-selects (`SHELLAI_BACKEND=auto`): MLX if importable, else llama.cpp.
- Override the model with `-m <repo>` or `SHELLAI_MODEL_REPO`.
- The `Source code` archives GitHub attaches automatically are **not** the
  install artifact — use the `.whl` above.
