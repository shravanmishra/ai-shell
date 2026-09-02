# ai-shell v1.0.0-beta.3

Natural-language → shell command translator running a **local** LLM.

## What's new since beta.2

- **Startup banner.** `ai-shell` now opens with a big `AI SHELL` wordmark and a
  Claude-Code-style info box (platform, model, key bindings). Colour is used
  only on a TTY and is disabled by `NO_COLOR`. Set `SHELLAI_NO_BANNER=1` for a
  one-line greeting, and it degrades to plain text automatically on terminals
  that can't render the box-drawing glyphs (legacy Windows code pages).

Carried over from beta.1 / beta.2: native Windows PowerShell + cmd dialects,
and the cmd `forfiles`/`@fsize` size-filter fix.

## Install (from this release)

```bash
pipx install --force "ai-shell-cli[llama] @ https://github.com/shravanmishra/ai-shell/releases/download/v1.0.0-beta.3/ai_shell_cli-1.0.0b3-py3-none-any.whl"
```

macOS Apple Silicon: swap `[llama]` for `[mlx]`. Requires Python ≥ 3.10. The
model (~1 GB) downloads once on first run into `~/.cache/ai-shell/`.

## Verify (optional)

```bash
shasum -a 256 -c SHA256SUMS.txt
```

The `Source code` archives GitHub attaches automatically are not the install
artifact — use the `.whl`.
