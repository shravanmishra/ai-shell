# ai-shell v1.0.0-beta.2

Natural-language → shell command translator running a **local** LLM.

## What's new since beta.1

- **cmd.exe dialect: size filtering fixed.** "list all files larger than 3 gb"
  was producing `dir /s /b | findstr /i "3 gb"` (matches the text "3 gb" in a
  path, not the size). The `windows-cmd` prompt now teaches `forfiles` +
  `@fsize` with the byte thresholds, and explicitly forbids `findstr` for
  numeric/size filters. PowerShell already handled this via `Where-Object
  Length -gt 3GB`.

Note: the PowerShell dialect is the default and the better choice on Windows.
If you landed on the cmd dialect, switch with:

```
# PowerShell:  $env:SHELLAI_SHELL = "powershell"
# cmd:         set SHELLAI_SHELL=powershell
```

## Install (from this release)

```bash
pipx install --force "ai-shell-cli[llama] @ https://github.com/shravanmishra/ai-shell/releases/download/v1.0.0-beta.2/ai_shell_cli-1.0.0b2-py3-none-any.whl"
```

macOS Apple Silicon: swap `[llama]` for `[mlx]`. Requires Python ≥ 3.10. The
model (~1 GB) downloads once on first run into `~/.cache/ai-shell/`.

## Verify (optional)

```bash
shasum -a 256 -c SHA256SUMS.txt
```

The `Source code` archives GitHub attaches automatically are not the install
artifact — use the `.whl`.
