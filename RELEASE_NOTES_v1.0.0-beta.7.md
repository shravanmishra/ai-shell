# ai-shell v1.0.0-beta.7

Natural-language → shell command translator running a **local** LLM.

## What's new since beta.6

- **Unquoted paths with spaces are auto-quoted.** The model would emit
  `cat ./Library/Application Support/CloudDocs/x.txt`; the shell split it on the
  space into two failing arguments. Now, when the whole argument joined actually
  exists on disk, it's wrapped in quotes -> `cat "./Library/Application
  Support/CloudDocs/x.txt"`. Covers `cat`/`less`/`head`/`tail`/`wc`/`stat`/
  `file`/`open`/`ls`/`cd`/`type`/`Get-Content`. The on-disk check keeps it from
  touching genuine multi-argument commands.

## Install / upgrade

Repo is private, so download the wheel from the release assets, then:

```bash
pipx install --force "/path/to/ai_shell_cli-1.0.0b7-py3-none-any.whl[mlx]"
```

`[llama]` instead of `[mlx]` on Linux / Windows / Intel Mac. Requires Python ≥ 3.10.

## Verify (optional)

```bash
shasum -a 256 -c SHA256SUMS.txt
```
