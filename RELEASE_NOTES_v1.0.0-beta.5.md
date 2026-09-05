# ai-shell v1.0.0-beta.5

Natural-language → shell command translator running a **local** LLM.

## What's new: refine on failure

Until now, when a command was wrong or failed you had to retype the whole
request. Now ai-shell closes the loop:

- **Non-zero exit** → `↻ that exited N. Ask the model to fix it? (y/N)`. On yes,
  it hands the failing command and its error output back to the model and
  proposes a correction.
- **You reject a command** (`n` at the y/N prompt) → `what should it do
  differently? (Enter to just retry)`. Type a one-line hint and it re-proposes.

Bounded by `SHELLAI_REFINE_MAX` (default 2) per request; `SHELLAI_NO_REFINE=1`
disables it. Same 1.5B model, no new dependencies, and every re-proposal still
goes through the same confirm / typed-`yes` gate. Quick read-only lookups are
now run captured so their error text can be fed back; long recursive scans
(`find`, `forfiles`, `-Recurse`) keep the live-streaming + ESC-to-stop path.

## Install / upgrade

```bash
pipx install --force "ai-shell-cli[llama] @ https://github.com/shravanmishra/ai-shell/releases/download/v1.0.0-beta.5/ai_shell_cli-1.0.0b5-py3-none-any.whl"
```

macOS Apple Silicon: swap `[llama]` for `[mlx]`. Requires Python ≥ 3.10.

## Verify (optional)

```bash
shasum -a 256 -c SHA256SUMS.txt
```
