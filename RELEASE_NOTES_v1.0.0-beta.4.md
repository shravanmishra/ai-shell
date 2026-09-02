# ai-shell v1.0.0-beta.4

Natural-language → shell command translator running a **local** LLM.

## What's new since beta.3

- **Ctrl-C no longer dumps a traceback.** At the prompt it exits cleanly; during
  model generation or a running command it drops that request and returns to
  the prompt. One-shot mode exits with status 130.
- **ESC-to-stop now works on Windows.** The interactive runner polls the
  keyboard with `msvcrt`; a lone ESC (or Ctrl-C) kills the command's whole
  process tree (`taskkill /T`) and hands control back. Previously ESC only
  worked on macOS/Linux.
- **PowerShell: read-only `Get-*` pipelines auto-run.** `Get-ChildItem … |
  Where-Object … | Select-Object …` (and `Sort-Object`, `Measure-Object`,
  `Format-Table`, …) no longer prompt. Anything with a mutating verb
  (`Remove-Item`, `Set-*`, `Stop-*`, `Out-File`, `ForEach-Object { … }`, …)
  still asks first.
- **cmd: `forfiles` size filter is auto-repaired.** The model reliably gets the
  byte threshold but garbles the `/C` payload (repeats `@fsize`, drops
  `@path`); it's now normalised to
  `forfiles /P <path> /S /M * /C "cmd /c if @fsize GEQ <n> echo @path (@fsize bytes)"`.

## Install / upgrade

```bash
pipx install --force "ai-shell-cli[llama] @ https://github.com/shravanmishra/ai-shell/releases/download/v1.0.0-beta.4/ai_shell_cli-1.0.0b4-py3-none-any.whl"
```

macOS Apple Silicon: swap `[llama]` for `[mlx]`. Requires Python ≥ 3.10.

## Verify (optional)

```bash
shasum -a 256 -c SHA256SUMS.txt
```
