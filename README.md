# ai-shell 🐚

**Type what you want; get the shell command. Runs a local LLM — nothing leaves your machine.**

```
$ ai-shell
[~/projects/api] AI-Shell> list every file over 1gb, sizes in GB

Proposed Command: find / -type f -size +1G -exec stat -f "%z	%N" {} \; 2>/dev/null | awk -F'\t' '{printf "%.2f GB\t%s\n", $1/1073741824, $2}'
(auto-running: simple read-only command)
6.62 GB	/System/Volumes/.../os.dmg
```

## Install

`ai-shell` is a CLI — install it with [pipx](https://pipx.pypa.io) so it lands in
its own isolated environment. Pick the backend for your machine:

```bash
pipx install "ai-shell-cli[mlx]"      # macOS, Apple Silicon  (MLX)
pipx install "ai-shell-cli[llama]"    # Linux / Windows / Intel Mac  (llama.cpp)
```

Plain `pip` into a virtualenv works too. The same model
(`Qwen2.5-Coder-1.5B`, ~1 GB, 4-bit) runs **fully locally** either way and
downloads once on first run into `~/.cache/ai-shell/`.

Backend selection is automatic (`SHELLAI_BACKEND=auto`): MLX when it's
importable, otherwise llama.cpp. Force it with `SHELLAI_BACKEND=mlx|llama`.

## Use

```bash
ai-shell                              # interactive shell (default)
ai-shell "count the python files here" # one-shot: translate, confirm, run
ai-shell -p "delete node_modules everywhere"   # print only, don't run
ai-shell -m mlx-community/Qwen2.5-Coder-7B-Instruct-4bit   # bigger model
```

**In the interactive shell:**

- Plain read-only lookups (`ls`, `pwd`, `find …`) run without a prompt.
- Anything that writes asks `y/N`; anything destructive (`rm`, `mv`, `sudo`, …) makes you type `yes`.
- `cd` persists across turns; the prompt shows the current directory.
- While a command runs, **ESC** stops it and returns you to the prompt.
- Multi-line: end a line with `\`, or wrap a block in `"""`.
- **Refine on failure:** if a command exits non-zero, or you reject it, ai-shell
  hands the error back to the model for a corrected command. At the `↻ Fix it?`
  prompt (and the rejection prompt) you can just press `y`/Enter, or type a hint
  ("look in ~/Downloads", "use ripgrep") that's passed along too. Up to
  `SHELLAI_REFINE_MAX` rounds (default 2); `SHELLAI_NO_REFINE=1` turns it off.
  Still one model, still confirms every step.

## Platforms

Command generation is dialect-aware — each OS gets its own prompt, repair rules,
and safety list:

- **macOS** (BSD userland) and **Linux** (GNU coreutils)
- **Windows** — native, no WSL needed. Two dialects:
  - **PowerShell** (default) — generates cmdlets (`Get-ChildItem`, `Select-String`,
    `Measure-Object`) and runs them through `powershell -Command`.
  - **cmd.exe** — generates `dir` / `findstr` / `where` builtins.

  The dialect auto-detects (cmd.exe exports `%PROMPT%`, PowerShell doesn't),
  defaulting to PowerShell. Force it with `SHELLAI_SHELL=powershell|cmd`.
  On Windows the backend is llama.cpp — `pipx install "ai-shell-cli[llama]"`
  (MLX is Apple-only).

`SHELLAI_PLATFORM=macos|linux|windows` overrides OS detection.

## Config (env vars)

| Variable | Default |
|---|---|
| `SHELLAI_BACKEND` | `auto` (`mlx` \| `llama`) |
| `SHELLAI_MODEL_REPO` | `mlx-community/Qwen2.5-Coder-1.5B-Instruct-4bit` (MLX) |
| `SHELLAI_GGUF_REPO` / `SHELLAI_GGUF_FILE` | `bartowski/Qwen2.5-Coder-1.5B-Instruct-GGUF` / `…-Q4_K_M.gguf` (llama.cpp) |
| `SHELLAI_LLM_DIR` | `~/.cache/ai-shell/models` |
| `SHELLAI_LOG_FILE` / `SHELLAI_HISTORY_FILE` | `~/.local/state/ai-shell/` |
| `SHELLAI_PERSIST_HISTORY` | unset — history is per-session; each restart starts fresh. Set to `1` to carry it across restarts. |
| `SHELLAI_TIMEOUT` | `120` (seconds per command) |
| `SHELLAI_REFINE_MAX` / `SHELLAI_NO_REFINE` | `2` retries on failure/rejection; set `SHELLAI_NO_REFINE=1` to disable |
| `SHELLAI_PLATFORM` | auto-detected (`macos` \| `linux` \| `windows`) |
| `SHELLAI_SHELL` | Windows only: `powershell` (default) \| `cmd` |

## Develop

```bash
uv pip install -e ".[dev,mlx]"
python appp1.py            # run straight from the source tree
uv run pytest
uv build                  # -> dist/*.whl + *.tar.gz
```

Source of truth is [`src/ai_shell/app.py`](src/ai_shell/app.py); `appp1.py` is a thin dev shim.

## License

MIT
