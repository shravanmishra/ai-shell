# ai-shell v1.0.0-beta.6

Natural-language → shell command translator running a **local** LLM.

## What's new since beta.5

- **Type a hint at the `↻ Fix it?` prompt.** After a failed command the prompt
  is now `↻ that exited N. Fix it? (y/N, or type a hint)`. `y`/Enter refines
  with just the error as before; anything else you type (e.g.
  `from the current directory`, `use ripgrep`) is passed to the model as a hint
  alongside the error. Previously only a literal `y` did anything and any other
  text silently cancelled.

## Install / upgrade

Repo is private, so the `pipx install "... @ <github url>"` form won't fetch.
Download the wheel from the release assets, then:

```bash
pipx install --force "/path/to/ai_shell_cli-1.0.0b6-py3-none-any.whl[mlx]"
```

`[llama]` instead of `[mlx]` on Linux / Windows / Intel Mac. Requires Python ≥ 3.10.

## Verify (optional)

```bash
shasum -a 256 -c SHA256SUMS.txt
```
