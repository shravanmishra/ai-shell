# ai-shell v1.0.0-beta.1

Natural-language → shell command translator running a **local** LLM. Nothing
leaves your machine.

## What's new

- **Native Windows support** — no WSL required. Two dialects, auto-detected:
  - **PowerShell** (default): generates cmdlets (`Get-ChildItem`, `Select-String`,
    `Measure-Object`) and runs them through `powershell -Command`.
  - **cmd.exe**: generates `dir` / `findstr` / `where` builtins.
  - Detection picks cmd when `%PROMPT%` is set, PowerShell otherwise.
    Force it with `SHELLAI_SHELL=powershell|cmd`.
- Per-dialect safety list (`Remove-Item -Recurse -Force`, `Format-Volume`,
  `diskpart`, `del`, `rd /s`, `reg delete`, … all gated behind a typed `yes`).
- `cd` / `Set-Location` now persists across turns on Windows too.

macOS and Linux behaviour is unchanged.

## Install (from this release)

Download `ai_shell_cli-1.0.0b1-py3-none-any.whl` from the assets below.

```bash
# macOS, Apple Silicon (MLX)
pipx install "ai_shell_cli-1.0.0b1-py3-none-any.whl[mlx]"

# Linux / Windows / Intel Mac (llama.cpp)
pipx install "ai_shell_cli-1.0.0b1-py3-none-any.whl[llama]"
```

Or straight from GitHub:

```bash
pipx install "ai-shell-cli[llama] @ https://github.com/shravanmishra/ai-shell/releases/download/v1.0.0-beta.1/ai_shell_cli-1.0.0b1-py3-none-any.whl"
```

Requires Python ≥ 3.10. The model (`Qwen2.5-Coder-1.5B`, ~1 GB, 4-bit) runs
fully locally and downloads once on first run into `~/.cache/ai-shell/`.

## Verify the download (optional)

```bash
shasum -a 256 -c SHA256SUMS.txt
```

## Quick start

```bash
ai-shell "list all files here"          # Windows PowerShell -> Get-ChildItem
ai-shell "delete the temp folder"       # -> gated behind a typed "yes"
```

The `Source code` archives GitHub attaches automatically are **not** the install
artifact — use the `.whl` above.
