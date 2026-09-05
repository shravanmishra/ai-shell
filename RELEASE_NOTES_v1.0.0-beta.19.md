# ai-shell v1.0.0-beta.19

Natural-language → shell command translator running a **local** LLM.

## What's new since beta.18

- **Stop "correcting" literal folder/file names.** The model was treating
  short names it half-recognized as typos and silently substituting a more
  common word -- e.g. `go to rnd` (or even the literal `cd rnd`) became
  `cd ~/random`. Added an explicit "names are literal data, don't autocorrect"
  rule to both system prompts, plus a `go to rnd -> cd rnd` few-shot example
  for each of the four shell dialects (macOS, Linux, PowerShell, cmd.exe).

## Install

Straight from this GitHub release (no manual download needed):

```bash
# macOS, Apple Silicon
pipx install --force "ai-shell-cli[mlx] @ https://github.com/shravanmishra/ai-shell/releases/download/v1.0.0-beta.19/ai_shell_cli-1.0.0b19-py3-none-any.whl"

# Windows / Linux / Intel Mac  (prebuilt llama.cpp wheel, no compiler needed)
pipx install --force \
  --pip-args "--extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu" \
  "ai-shell-cli[llama] @ https://github.com/shravanmishra/ai-shell/releases/download/v1.0.0-beta.19/ai_shell_cli-1.0.0b19-py3-none-any.whl"
```

Or from a wheel you already downloaded (e.g. from this release's assets):

```bash
# macOS, Apple Silicon
pipx install --force "/path/to/ai_shell_cli-1.0.0b19-py3-none-any.whl[mlx]"

# Windows / Linux / Intel Mac  (prebuilt llama.cpp wheel, no compiler needed)
pipx install --force \
  --pip-args "--extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu" \
  "/path/to/ai_shell_cli-1.0.0b19-py3-none-any.whl[llama]"
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
  "C:\path\to\ai_shell_cli-1.0.0b19-py3-none-any.whl[llama]"
```

Also check the system clock — a wrong date triggers the same error.

### Offline model install (`llama` backend)

On first run, ai-shell downloads the GGUF model from HuggingFace Hub. If that
network path is blocked but github.com isn't, grab
`Qwen2.5-Coder-1.5B-Instruct-Q4_K_M.gguf` from the
[v1.0.0-beta.18 release assets](https://github.com/shravanmishra/ai-shell/releases/tag/v1.0.0-beta.18)
(unchanged since then) and drop it in the cache dir yourself — ai-shell finds
it there and skips the download entirely:

```powershell
# Windows
mkdir "$env:USERPROFILE\.cache\ai-shell\gguf" -Force
Move-Item Qwen2.5-Coder-1.5B-Instruct-Q4_K_M.gguf "$env:USERPROFILE\.cache\ai-shell\gguf\"
```

```bash
# macOS / Linux
mkdir -p ~/.cache/ai-shell/gguf
mv Qwen2.5-Coder-1.5B-Instruct-Q4_K_M.gguf ~/.cache/ai-shell/gguf/
```

(Setting `XDG_CACHE_HOME` moves the whole cache dir; `SHELLAI_GGUF_FILE` changes
just the expected filename — set both to non-default values consistently.)

## Verify (optional)

```bash
shasum -a 256 -c SHA256SUMS.txt
```
