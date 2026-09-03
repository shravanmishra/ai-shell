# ai-shell v1.0.0-beta.17

Natural-language → shell command translator running a **local** LLM.

## What's new since beta.16

- **"what is my current directory" now works on Windows.** The model was
  emitting `cd /d %cd%` — a no-op that prints nothing. Fixes:
  - `cd /d %cd%` / `cd %cd%` → `cd` (cmd) or `Get-Location` (PowerShell).
  - Few-shot examples added: `what is my current directory` → `cd` / `Get-Location`.
  - On the Windows dialects a bare `cd` now runs (cmd prints the working
    directory) instead of being intercepted as "chdir to home" — POSIX
    `cd` → home is unchanged.

## Install

```bash
# macOS, Apple Silicon
pipx install --force "/path/to/ai_shell_cli-1.0.0b17-py3-none-any.whl[mlx]"

# Windows / Linux / Intel Mac  (prebuilt llama.cpp wheel, no compiler needed)
pipx install --force \
  --pip-args "--extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu" \
  "/path/to/ai_shell_cli-1.0.0b17-py3-none-any.whl[llama]"
```

Prebuilt `llama-cpp-python` wheels need **Python ≤ 3.12**. Requires Python ≥ 3.10.

### Windows: `CERTIFICATE_VERIFY_FAILED` / SSL cert error on install

Usually a corporate proxy/AV (Zscaler, Netskope, Kaspersky, etc.) doing SSL
inspection with a root CA that Python doesn't trust. Fixes, in order:

```powershell
# 1. Update pip/certifi
python -m pip install --upgrade pip certifi

# 2. Use the Windows cert store instead of bypassing verification
pip install pip-system-certs

# 3. One-off unblock if 1-2 aren't enough (not a real fix)
pipx install --force `
  --pip-args "--extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu --trusted-host pypi.org --trusted-host files.pythonhosted.org --trusted-host abetlen.github.io" `
  "C:\path\to\ai_shell_cli-1.0.0b17-py3-none-any.whl[llama]"
```

Also check the system clock — a wrong date triggers the same error.

## Verify (optional)

```bash
shasum -a 256 -c SHA256SUMS.txt
```
