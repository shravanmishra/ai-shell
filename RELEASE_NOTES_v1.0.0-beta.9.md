# ai-shell v1.0.0-beta.9

Natural-language → shell command translator running a **local** LLM.

## What's new since beta.8

- **PowerShell read-only pipelines with calculated properties now auto-run.**
  `Get-ChildItem … | Where-Object … | Select-Object FullName,
  @{n='GB';e={[math]::Round($_.Length/1GB,2)}}` was asking for confirmation:
  `is_trivial` saw the `;` inside the `@{…}` hashtable and treated it as a
  command chain. It now strips quoted strings and `{…}` / `@{…}` blocks before
  looking for chain separators, so `;` / `|` inside a calculated property or a
  `Where-Object { … }` filter block no longer disqualifies the command. A real
  chain (`Get-ChildItem; Get-Date`) and any mutating verb still do.

## Install / upgrade

Repo is private — download the wheel from the release assets, then:

```bash
pipx install --force "/path/to/ai_shell_cli-1.0.0b9-py3-none-any.whl[llama]"
```

`[mlx]` on Apple Silicon. Requires Python ≥ 3.10.

## Verify (optional)

```bash
shasum -a 256 -c SHA256SUMS.txt
```
