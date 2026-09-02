# ai-shell v1.0.0-beta.8

Natural-language → shell command translator running a **local** LLM.

## What's new since beta.7

- **PowerShell: no more spurious `[exit status 1]`.** `Get-ChildItem -Recurse`
  over `C:\` skips folders it can't read; with `-ErrorAction SilentlyContinue`
  those messages are hidden, but `powershell.exe -Command` still exited `1` for
  the otherwise-successful pipeline — and that tripped the refine-on-failure
  prompt. PowerShell commands are now wrapped
  `try { <cmd> } catch { …; exit 1 }; exit 0`, so only a *terminating* error
  yields a non-zero exit; skipped-folder noise doesn't.

## Install / upgrade

Repo is private — download the wheel from the release assets, then:

```bash
pipx install --force "/path/to/ai_shell_cli-1.0.0b8-py3-none-any.whl[llama]"
```

`[mlx]` on Apple Silicon. Requires Python ≥ 3.10.

## Verify (optional)

```bash
shasum -a 256 -c SHA256SUMS.txt
```
