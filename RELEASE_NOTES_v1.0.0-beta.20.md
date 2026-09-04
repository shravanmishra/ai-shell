# ai-shell v1.0.0-beta.20

Natural-language → shell command translator running a **local** LLM.

## What's new since beta.19

- **The GGUF model now ships inside the wheel.** Previously, the `llama.cpp`
  backend downloaded `Qwen2.5-Coder-1.5B-Instruct-Q4_K_M.gguf` from Hugging
  Face on first run. This release bundles it directly into the wheel, so
  installs on Windows / Linux / Intel Mac are fully offline from the start —
  no first-run download, no dependency on Hugging Face being reachable. As a
  result this wheel is **~920MB** instead of a few KB (it's a single
  cross-platform wheel, so the bundled weights ship regardless of which
  backend a given install ends up using).
- The MLX backend (Apple Silicon) is unchanged and still downloads its
  weights from Hugging Face on first run.

## Install

Straight from this GitHub release (no manual download needed):

```bash
# macOS, Apple Silicon
pipx install --force "ai-shell-cli[mlx] @ https://github.com/shravanmishra/ai-shell/releases/download/v1.0.0-beta.20/ai_shell_cli-1.0.0b20-py3-none-any.whl"

# Windows / Linux / Intel Mac  (prebuilt llama.cpp wheel, no compiler needed; model bundled, fully offline)
pipx install --force \
  --pip-args "--extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu" \
  "ai-shell-cli[llama] @ https://github.com/shravanmishra/ai-shell/releases/download/v1.0.0-beta.20/ai_shell_cli-1.0.0b20-py3-none-any.whl"
```

Or from a wheel you already downloaded (e.g. from this release's assets):

```bash
# macOS, Apple Silicon
pipx install --force "/path/to/ai_shell_cli-1.0.0b20-py3-none-any.whl[mlx]"

# Windows / Linux / Intel Mac  (prebuilt llama.cpp wheel, no compiler needed; model bundled, fully offline)
pipx install --force \
  --pip-args "--extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu" \
  "/path/to/ai_shell_cli-1.0.0b20-py3-none-any.whl[llama]"
```

Prebuilt `llama-cpp-python` wheels need **Python ≤ 3.12**. Requires Python ≥ 3.10.

Note this wheel is ~920MB — the download itself takes longer than previous
releases, but there's no separate model download afterward for `llama`-backend
installs.

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
  "C:\path\to\ai_shell_cli-1.0.0b20-py3-none-any.whl[llama]"
```

Also check the system clock — a wrong date triggers the same error.

### Offline model install (`mlx` backend)

The MLX backend still downloads its weights from Hugging Face Hub on first
run. If that network path is blocked but github.com isn't, grab
`Qwen2.5-Coder-1.5B-Instruct-Q4_K_M.gguf` from the
[v1.0.0-beta.18 release assets](https://github.com/shravanmishra/ai-shell/releases/tag/v1.0.0-beta.18)
and drop it in the cache dir yourself for the `llama` backend, or use the
`mlx-community/Qwen2.5-Coder-1.5B-Instruct-4bit` weights directly for `mlx`.
`llama`-backend installs from this release don't need this — the model is
already in the wheel.

## Verify (optional)

```bash
shasum -a 256 -c SHA256SUMS.txt
```
