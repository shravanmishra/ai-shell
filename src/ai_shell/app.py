
import os
import re
import sys
import time
import shutil
import signal
import logging
import subprocess
from dataclasses import dataclass
from typing import Callable
try:
    import readline
except ImportError:  # readline unavailable (e.g. non-Unix) -> arrows won't work
    readline = None
try:
    import termios
    import tty
    import select as _select
except ImportError:  # non-Unix -> ESC-to-stop degrades to a plain blocking run
    termios = None
try:
    import msvcrt  # Windows: keyboard polling for ESC-to-stop
except ImportError:
    msvcrt = None

try:  # MLX backend (Apple Silicon) -- extra: ai-shell-cli[mlx]
    from mlx_lm import load as mlx_load, generate as mlx_generate
except ImportError:
    mlx_load = mlx_generate = None
try:  # llama.cpp backend (any OS, local GGUF) -- extra: ai-shell-cli[llama]
    from llama_cpp import Llama as _Llama
except ImportError:
    _Llama = None
try:
    from huggingface_hub import snapshot_download, hf_hub_download
except ImportError:
    snapshot_download = hf_hub_download = None


def _user_dir(kind: str) -> str:
    """Per-user cache/state directory, XDG-style, created on first use.

    kind is "cache" (model weights) or "state" (log + history).
    """
    var, default = {
        "cache": ("XDG_CACHE_HOME", "~/.cache"),
        "state": ("XDG_STATE_HOME", "~/.local/state"),
    }[kind]
    base = os.environ.get(var) or os.path.expanduser(default)
    path = os.path.join(base, "ai-shell")
    os.makedirs(path, exist_ok=True)
    return path


# Every path / knob below can be overridden with a SHELLAI_* environment
# variable. Weights live in the user cache dir, log + history in the state dir,
# so an installed `ai-shell` never writes into site-packages.
MODEL_REPO = os.environ.get(
    "SHELLAI_MODEL_REPO", "mlx-community/Qwen2.5-Coder-1.5B-Instruct-4bit"
)
LLM_DIR = os.environ.get("SHELLAI_LLM_DIR") or os.path.join(_user_dir("cache"), "models")
MODEL_DIR = os.path.join(LLM_DIR, MODEL_REPO.split("/")[-1])
MAX_TOKENS = int(os.environ.get("SHELLAI_MAX_TOKENS", "256"))
EXEC_TIMEOUT = int(os.environ.get("SHELLAI_TIMEOUT", "120"))

# Refine-on-failure: when a command exits non-zero or you reject it, ask the
# model for a corrected command (feeding back the error / your hint). Bounded
# by REFINE_MAX retries per request; NO_REFINE=1 disables it entirely.
REFINE_MAX = int(os.environ.get("SHELLAI_REFINE_MAX", "2"))
NO_REFINE = os.environ.get("SHELLAI_NO_REFINE", "").strip() not in ("", "0", "false")

# Model backend: "auto" prefers MLX when importable (Apple Silicon) and
# otherwise uses llama.cpp with a local GGUF -- which works on Linux and
# Windows too. Same model either way (Qwen2.5-Coder-1.5B, 4-bit).
BACKEND = os.environ.get("SHELLAI_BACKEND", "auto").strip().lower()
LLAMA_MODEL_REPO = os.environ.get(
    "SHELLAI_GGUF_REPO", "bartowski/Qwen2.5-Coder-1.5B-Instruct-GGUF"
)
LLAMA_MODEL_FILE = os.environ.get(
    "SHELLAI_GGUF_FILE", "Qwen2.5-Coder-1.5B-Instruct-Q4_K_M.gguf"
)

# --- Platform profiles ----------------------------------------------------
# The translator, the deterministic repair passes, and the safety classifier
# are all shell-dialect specific. A PlatformProfile bundles everything that
# differs between macOS (BSD userland), Linux (GNU coreutils), and -- once
# implemented -- Windows. Detect once; every dialect-specific site reads the
# selected PROFILE instead of hard-coding BSD.

def _detect_platform() -> str:
    forced = os.environ.get("SHELLAI_PLATFORM", "").strip().lower()
    if forced in ("macos", "darwin"):
        return "macos"
    if forced in ("linux",):
        return "linux"
    if forced in ("windows", "win", "win32"):
        return "windows"
    if os.name == "nt":
        return "windows"
    return "macos" if sys.platform == "darwin" else "linux"


def _detect_windows_shell() -> str:
    """Pick the Windows dialect: "powershell" (default) or "cmd".

    Honour SHELLAI_SHELL; otherwise fall back to a heuristic -- cmd.exe exports
    %PROMPT% (default "$P$G"), PowerShell does not -- and default to PowerShell,
    which is the shell Windows 10/11 open by default and can run almost anything.
    """
    forced = os.environ.get("SHELLAI_SHELL", "").strip().lower()
    if forced in ("powershell", "pwsh", "ps"):
        return "powershell"
    if forced in ("cmd", "cmd.exe", "bat", "batch"):
        return "cmd"
    if os.environ.get("PROMPT"):
        return "cmd"
    return "powershell"


PLATFORM = _detect_platform()
WINDOWS_SHELL = _detect_windows_shell()


@dataclass(frozen=True)
class PlatformProfile:
    name: str
    os_label: str                 # goes in the system prompt's first line
    compat_fix: Callable[[str], str]
    prompt_extra: str             # dialect rules + few-shot examples
    family: str = "posix"         # "posix" (macOS/Linux) | "windows"
    primary_ipv4: str = ""        # shell snippet -> the active interface's IPv4
    wifi_ssid: str = ""           # shell snippet -> current Wi-Fi SSID
    battery: str = ""             # shell snippet -> battery status
    # POSIX `stat` dialect -- unused (left empty) for the Windows family.
    stat_flag: str = ""           # "-f" (BSD) | "-c" (GNU)
    stat_size: str = ""           # "%z" | "%s"
    stat_name: str = ""           # "%N" | "%n"
    stat_mtime: str = ""          # "%Sm" | "%y"
    stat_interprets_escapes: bool = False  # BSD stat -f does NOT expand \t/\n; GNU -c does
    danger_extra: tuple = ()      # extra (compiled_regex, reason) pairs
    trivial_cmds: frozenset = frozenset()
    # Maps a command string to (argv-or-string, shell_bool) for the runner.
    # None -> run the string through the system shell (POSIX sh / cmd.exe).
    exec_argv: "Callable[[str], tuple] | None" = None

    def stat_expr(self, fmt: str) -> str:
        """`stat` invocation printing `fmt` (fmt may contain real \\t/\\n)."""
        return f'stat {self.stat_flag} "{fmt}"'


# Populated at the bottom of this section once the compat_fix callables exist.
PROFILES: dict[str, PlatformProfile] = {}


def _get_profile() -> PlatformProfile:
    if PLATFORM == "windows":
        return PROFILES[f"windows-{WINDOWS_SHELL}"]
    if PLATFORM in PROFILES:
        return PROFILES[PLATFORM]
    return PROFILES["linux"]

# The model is loaded once per process and reused for every prompt,
# so repeated calls never re-load the weights.
_model = None
_tokenizer = None


_active_backend: str | None = None
_llama = None  # llama.cpp singleton


def _resolve_backend() -> str:
    """Pick the backend once: honour SHELLAI_BACKEND, else auto-detect.

    auto -> MLX if importable (Apple Silicon), else llama.cpp.
    """
    global _active_backend
    if _active_backend:
        return _active_backend
    choice = BACKEND
    if choice not in ("auto", "mlx", "llama"):
        sys.exit(f"ai-shell: SHELLAI_BACKEND={BACKEND!r} (use auto | mlx | llama)")
    if choice == "auto":
        choice = "mlx" if mlx_load is not None else "llama"
    _active_backend = choice
    return choice


def ensure_model_downloaded() -> None:
    """Download the MLX weights into the user cache exactly once (idempotent)."""
    marker = os.path.join(MODEL_DIR, "config.json")
    if os.path.exists(marker):
        return
    if snapshot_download is None:
        sys.exit("ai-shell: huggingface-hub is missing; reinstall the package.")
    os.makedirs(MODEL_DIR, exist_ok=True)
    print(f"Downloading {MODEL_REPO} into {MODEL_DIR} ...")
    snapshot_download(MODEL_REPO, local_dir=MODEL_DIR)
    print("Download complete.")


def _ensure_gguf() -> str:
    """Fetch the GGUF for the llama.cpp backend into the cache; return its path."""
    if hf_hub_download is None:
        sys.exit("ai-shell: huggingface-hub is missing; reinstall the package.")
    gguf_dir = os.path.join(_user_dir("cache"), "gguf")
    os.makedirs(gguf_dir, exist_ok=True)
    dest = os.path.join(gguf_dir, LLAMA_MODEL_FILE)
    if not os.path.exists(dest):
        print(f"Downloading {LLAMA_MODEL_FILE} ...")
        hf_hub_download(
            repo_id=LLAMA_MODEL_REPO, filename=LLAMA_MODEL_FILE, local_dir=gguf_dir
        )
        print("Download complete.")
    return dest


def _llama_chat(messages: list[dict], max_tokens: int) -> str:
    resp = _llama.create_chat_completion(
        messages=messages, temperature=0.0, max_tokens=max_tokens
    )
    return resp["choices"][0]["message"]["content"]


def get_local_model():
    """Prepare the active backend (idempotent). Called once at startup.

    Both backends run the same 4-bit Qwen2.5-Coder-1.5B locally; nothing leaves
    the machine.
    """
    backend = _resolve_backend()
    if backend == "mlx":
        global _model, _tokenizer
        if mlx_load is None:
            sys.exit("ai-shell: backend 'mlx' needs mlx-lm.\n"
                     "    pip install mlx-lm            (Apple Silicon)\n"
                     "or:  SHELLAI_BACKEND=llama ai-shell  (any OS)")
        if _model is None or _tokenizer is None:
            ensure_model_downloaded()
            ensure_logging()
            logger.info(f"Loading local model from {MODEL_DIR} ...")
            t0 = time.perf_counter()
            _model, _tokenizer = mlx_load(MODEL_DIR)
            logger.info(f"Model ready in {time.perf_counter() - t0:.1f}s")
        return _model, _tokenizer

    # backend == "llama"
    global _llama
    if _Llama is None:
        sys.exit("ai-shell: backend 'llama' needs llama-cpp-python.\n"
                 "    pip install 'ai-shell-cli[llama]'")
    if _llama is None:
        path = _ensure_gguf()
        ensure_logging()
        logger.info(f"Loading local model from {path} ...")
        t0 = time.perf_counter()
        _llama = _Llama(model_path=path, n_ctx=4096, verbose=False)
        logger.info(f"Model ready in {time.perf_counter() - t0:.1f}s")
    return _llama


# File logging: records the user query, raw model response, and response time
# for every turn. The file handler is attached lazily by ensure_logging() so a
# bare `import ai_shell.app` creates nothing on disk.
LOG_FILE = os.environ.get("SHELLAI_LOG_FILE") or os.path.join(_user_dir("state"), "shellai.log")
logger = logging.getLogger("shellai")
logger.setLevel(logging.INFO)
logger.propagate = False  # don't echo to the console
_logging_ready = False


def ensure_logging() -> None:
    """Attach the file handler on first use (idempotent)."""
    global _logging_ready
    if _logging_ready:
        return
    if not logger.handlers:
        handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
        handler.setFormatter(
            logging.Formatter("%(asctime)s | %(message)s", "%Y-%m-%d %H:%M:%S")
        )
        logger.addHandler(handler)
    _logging_ready = True


# Conversation history: the last few messages (user + assistant turns) give the
# model multi-turn context so an immediate follow-up ("now the same for /var",
# "sort that by size") works. In-memory only -- nothing is written to disk, and
# every restart starts fresh. Kept small on purpose: a 1.5B model is easily
# nudged off-track by stale earlier commands sitting in the window.
MAX_HISTORY = 10  # messages == 5 request/command exchanges
history: list[dict] = []


def load_history() -> None:
    """Reset conversation history for a fresh session (in-memory only)."""
    history.clear()


SYSTEM_PROMPT_CORE = """You are a precise shell-command translator for {os_label}. Given a short
natural-language request, reply with EXACTLY ONE raw, ready-to-run shell command.

Strict output rules:
- Start your answer directly with the command (e.g. ls, find, grep).
- Do NOT wrap it in markdown, backticks, code fences, or labels.
- Do NOT explain, think aloud, or add commentary. One line, one command.
- If the request is ambiguous, pick the most common intent and do NOT ask
  clarifying questions.

Scope rules (very important):
- If the user says "the entire drive", "everything", or does NOT specify a
  folder, search from / (the filesystem root), NOT from . .
- If the user names a specific directory (e.g. Downloads, ~/Documents, /var/log),
  use that path.
- If the user says "in this folder", "here", or "current directory", use . .

IMPORTANT: find outputs one bare path per line. To get size/date, you MUST use
-exec stat or -exec ls. NEVER pipe bare find output into awk to extract
"columns" -- there are no columns.

Multiple asks: if ONE request bundles several unrelated questions ("my IP and
the wifi name and the battery and the time"), join the commands with ;
(semicolon) so every part runs even if one fails. Never chain unrelated
lookups with && (a single failure would hide all the rest).

Converting stat's byte count to KB/MB/GB/TB: divide by 1024 once per step
(KB=1024, MB=1024*1024, GB=1024*1024*1024, TB=1024^4) -- get the number of
/1024s right for the unit you print, and always keep the filename in the
output, never just the bare number.

If the request filters by a size in a human unit ("files larger than 3gb",
"bigger than 500mb"), report each match's size in THAT unit, not raw bytes.
"""


SYSTEM_PROMPT_CORE_WINDOWS = """You are a precise shell-command translator for {os_label}. Given a short
natural-language request, reply with EXACTLY ONE raw, ready-to-run {shell} command.

Strict output rules:
- Start your answer directly with the command.
- Do NOT wrap it in markdown, backticks, code fences, or labels.
- Do NOT explain, think aloud, or add commentary. One line, one command.
- If the request is ambiguous, pick the most common intent and do NOT ask
  clarifying questions.

Scope rules (very important):
- If the user says "the whole drive", "everything", or does NOT specify a
  folder, start from the drive root (C:\\), NOT the current directory.
- If the user names a specific directory, use that path.
- If the user says "in this folder", "here", or "current directory", use "." .

Multiple asks: if ONE request bundles several unrelated questions ("my IP and
the wifi name and the battery and the time"), join the commands with ; so every
part runs.

If the request filters by a size in a human unit ("files larger than 3gb",
"bigger than 500mb"), report each match's size in THAT unit, not raw bytes.
"""


def build_system_prompt(profile: "PlatformProfile") -> str:
    if profile.family == "windows":
        shell = "PowerShell" if "powershell" in profile.name else "cmd.exe"
        core = SYSTEM_PROMPT_CORE_WINDOWS.format(
            os_label=profile.os_label, shell=shell
        )
    else:
        core = SYSTEM_PROMPT_CORE.format(os_label=profile.os_label)
    return core.strip() + "\n\n" + profile.prompt_extra.strip()


def extract_command(raw: str) -> str:
    """Strip markdown fences, reasoning text, and stray prose from model output.

    A fenced code block is trusted verbatim, so multi-line commands
    (heredocs, backslash continuations, && chains) survive intact. Without a
    fence we assume any prose is leading commentary and keep the last
    non-empty line.
    """
    text = raw.strip().replace("\n</think>", "").replace("<|im_end|>", "").strip()

    # A fenced code block anywhere in the reply is the command; trust its full
    # body so multi-line commands survive, and ignore any surrounding prose.
    fence = re.search(r"```(?:bash|sh|shell|zsh)?[ \t]*\n?(.*?)```", text, re.S)
    if fence:
        body = fence.group(1).strip()
        body = re.sub(r"^(?:A|Answer|Command|Output)\s*:\s*", "", body, flags=re.I)
        return re.sub(r"(\||&&|;)\s*$", "", body).strip()

    # No fence: the model may have rambled across lines. Take the last non-empty
    # line, re-joining a command that was split before a leading bare pipe.
    candidate_lines = [l for l in text.splitlines() if l.strip()]
    if candidate_lines:
        text = candidate_lines[-1].strip()
    if text.startswith("|") and len(candidate_lines) > 1:
        text = candidate_lines[-2].strip() + " " + text.lstrip("|").strip()
    text = re.sub(r"^(?:A|Answer|Command|Output)\s*:\s*", "", text, flags=re.I)
    # Strip a trailing bare pipe / && / ; that would break the shell.
    text = re.sub(r"(\||&&|;)\s*$", "", text).strip()
    if not text or text == "|":
        text = candidate_lines[0].strip() if candidate_lines else text
    return text.strip()


def quiet_broad_find(command: str) -> str:
    """Append 2>/dev/null to broad find commands to suppress permission errors."""
    tokens = command.split()
    if not tokens or tokens[0] != "find":
        return command
    path = None
    for tok in tokens[1:]:
        if tok.startswith("-"):
            continue
        path = tok
        break
    if path in (None, "/") or path in ("~", "$HOME") or path.startswith("~/"):
        if "2>/dev/null" not in command:
            return command + " 2>/dev/null"
    return command


def fix_find_exec_terminator(cmd: str) -> str:
    """Repair a `find ... -exec CMD {}` whose `\\;` (or `+`) terminator the model
    mangled: `{} \\` / `{} \\ 2>/dev/null` (dangling backslash), a bare `{} ;`
    that the shell would eat, or `{}` with no terminator at all before a
    redirect / pipe / end of line. All -> `{} \\;`.
    """
    if "-exec" not in cmd:
        return cmd
    # `{} \` where the backslash is NOT already `\;`
    cmd = re.sub(r"(\{\}\s*)\\(?!;)(\s|$)", r"\1\\;\2", cmd)
    # bare, unescaped `{} ;`
    cmd = re.sub(r"(\{\}\s*)(?<!\\);(\s|$)", r"\1\\;\2", cmd)
    # `{}` immediately followed by a redirect / pipe / EOL and no `\;` or `+`
    cmd = re.sub(r"(\{\})(\s*)(?=$|[|&]|\d*>)", r"\1 \\;\2", cmd)
    return cmd


def repair_command(cmd: str) -> str:
    """Deterministic repair for common 1.5B-model mistakes.

    The model often emits `find <predicates> | awk '{print $5, $6, $7}'`,
    treating find's output as if it were `ls -l` columns. But bare `find`
    prints one filename per line with NO columns, so the awk selects nothing.
    Fix: rewrite the find to attach real metadata via `stat -f` (size, date,
    name) and drop the broken awk.
    """
    cmd = cmd.strip()
    m = re.match(r"^(find\b.*?)(\s*\|\s*awk\b.*)$", cmd)
    if not m:
        return cmd
    find_part = m.group(1).strip()
    # Only repair if the find itself doesn't already emit columns/records.
    if any(tok in find_part for tok in ("-exec", "-ls", "-printf")):
        return cmd
    # Strip a trailing stderr redirect, then append -exec stat to emit real fields.
    find_core = re.sub(r"\s+2>/dev/null\s*$", "", find_part)
    fmt = f"{PROFILE.stat_size} bytes  {PROFILE.stat_mtime}  {PROFILE.stat_name}"
    return f'{find_core} -exec {PROFILE.stat_expr(fmt)} {{}} \\; 2>/dev/null'


def _shared_compat_fix(cmd: str) -> str:
    """Fixups that hold on every POSIX shell dialect."""
    # date: an unquoted +FORMAT with spaces splits into bad args; quote it.
    cmd = re.sub(
        r"(\bdate\b(?:\s+-u)?\s+)\+([^\s\"'|&;]+(?:\s+[^\s\"'|&;]+)+)",
        r'\1"+\2"', cmd,
    )
    # `ls -d` with no operand only ever prints "." -- for "list folders" the
    # model meant `ls -d */`. Only touch a bare `ls` + flags (no path, pipe...).
    toks = cmd.split()
    if (
        toks[:1] == ["ls"]
        and len(toks) > 1
        and all(t.startswith("-") for t in toks[1:])
        and any("d" in t[1:] for t in toks[1:] if not t.startswith("--"))
    ):
        cmd += " */"
    return cmd


def _linux_compat_fix(cmd: str) -> str:
    """Rewrite BSD/macOS-isms the model slips in back to GNU coreutils.

    The reverse of the macOS pass: the model sometimes emits `stat -f`,
    `du -d N`, or macOS-only net tools even when told the target is Linux.
    """
    # stat: BSD `-f 'fmt'` -> GNU `-c 'fmt'`, and BSD field codes -> GNU codes.
    def _stat_c(m):
        body = m.group(1).replace("%Sm", "%y").replace("%z", "%s").replace("%N", "%n")
        return f'stat -c "{body}"'
    cmd = re.sub(r'stat\s+-f\s+"([^"]*)"', _stat_c, cmd)
    # du: BSD `-d N` -> GNU `--max-depth=N`
    cmd = re.sub(r"(\bdu\b[^|&;]*?)\s-d\s+(\d+)", r"\1 --max-depth=\2", cmd)
    # macOS network tools -> Linux equivalents
    cmd = re.sub(r"(?<!\S)ipconfig\s+getifaddr\s+\S+", PROFILE.primary_ipv4, cmd)
    cmd = re.sub(
        r"(?<!\S)networksetup\s+-getairportnetwork(?:\s+\"[^\"]*\"|\s+\S+)?",
        PROFILE.wifi_ssid, cmd,
    )
    cmd = re.sub(r"(?<!\S)pmset\s+-g\s+batt\b", PROFILE.battery, cmd)
    cmd = re.sub(r"(?<!\S)sw_vers\b", "lsb_release -a 2>/dev/null || uname -a", cmd)
    return _shared_compat_fix(cmd)


def _macos_compat_fix(cmd: str) -> str:
    """Rewrite common GNU-only flags to their BSD/macOS equivalents.

    The 1.5B model is heavily biased toward GNU/Linux tooling. This
    deterministic pass catches the most frequent offenders so the
    command actually runs on a stock macOS shell.
    """
    # du: --max-depth=N / --max-depth N / bare --max-depth  ->  -d N
    cmd = re.sub(r"--max-depth=(\d+)", r"-d \1", cmd)
    cmd = re.sub(r"--max-depth\s+(\d+)", r"-d \1", cmd)
    cmd = re.sub(r"--max-depth\b", "-d 1", cmd)
    # du: --all-levels -> -a ; --apparent-size -> -A ; --human-readable -> -h
    cmd = re.sub(r"--all-levels\b", "-a", cmd)
    cmd = re.sub(r"--apparent-size\b", "-A", cmd)
    cmd = re.sub(r"--human-readable\b", "-h", cmd)
    # grep: -P / --perl-regexp / --extended-regexp -> -E (BSD grep has no PCRE)
    cmd = re.sub(r"(grep\s+)(-P)\b", r"\1-E", cmd)
    cmd = re.sub(r"(grep\b[^|&;]*?\s)--perl-regexp\b", r"\1-E", cmd)
    cmd = re.sub(r"(grep\b[^|&;]*?\s)--extended-regexp\b", r"\1-E", cmd)
    # ps: GNU `--sort=KEY` is unsupported; map the usual memory/cpu sorts to BSD.
    cmd = re.sub(r"\s+--sort=-?(?:%mem|rss)\b", " -m", cmd)
    cmd = re.sub(r"\s+--sort=-?%cpu\b", " -r", cmd)
    # ls: --time-style=... not supported on macOS; drop it
    cmd = re.sub(r"\s+--time-style=\S+", "", cmd)
    # find: GNU long flags -> BSD short flags
    cmd = re.sub(r"\s+--type\b", " -type", cmd)
    cmd = re.sub(r"\s+--name\s+", " -name ", cmd)
    # du: on macOS (BSD) -s and -d are mutually exclusive; when a depth is
    # requested, drop the summarize flag so the per-directory listing wins.
    if re.search(r"\bdu\b", cmd) and re.search(r"(?:^|\s)-d\s+\d+", cmd):
        cmd = re.sub(r"-sh\b", "-h", cmd)
        cmd = re.sub(r"(^|\s)-s(\s|$)", r"\1\2", cmd)
    # stat: GNU -c 'fmt' -> BSD -f 'fmt'
    cmd = re.sub(r"(stat\s+)-c\s+", r"\1-f ", cmd)

    # ipconfig: on macOS it is a sub-command tool, not a dumper. `ipconfig`
    # (Linux/Windows habit), `ipconfig | grep ...IP...`, and a hard-coded
    # `getifaddr en0` (wrong when the IP lives on en1/Ethernet) all fail here;
    # rewrite to resolve the *active* interface's IPv4.
    cmd = re.sub(
        r"(?<!\S)ipconfig\s*\|\s*grep\s+[\"']?[^\"'|&;]*[\"']?",
        _PRIMARY_IPV4, cmd, flags=re.I,
    )
    cmd = re.sub(
        r"(?<!\S)ipconfig(?!\s+(?:getifaddr|waitall|ifcount|getoption|getiflist|"
        r"getsummary|getpacket|getv6packet|getra|getdhcpduid|getdhcpiaid|set|"
        r"setverbose))(?=\s*(?:$|[|&;]))",
        _PRIMARY_IPV4, cmd,
    )
    cmd = re.sub(r"(?<!\S)ipconfig\s+getifaddr\s+en\d\b", _PRIMARY_IPV4, cmd)
    # networksetup -getairportnetwork needs the real Wi-Fi device, not en0.
    cmd = re.sub(
        r"networksetup\s+-getairportnetwork(?:\s+en\d|\s+\"[^\"]*\")?",
        f'networksetup -getairportnetwork "{_WIFI_DEVICE}"', cmd,
    )
    return _shared_compat_fix(cmd)


def _windows_ps_compat_fix(cmd: str) -> str:
    """Nudge POSIX-isms the model still emits into PowerShell.

    The 1.5B model is Linux-biased; this deterministic pass rewrites the most
    common leftovers so the line actually runs in `powershell -Command`.
    """
    # Strip POSIX stderr-to-null; PowerShell uses -ErrorAction instead.
    cmd = re.sub(r"\s*2>\s*/dev/null\b", "", cmd)
    cmd = re.sub(r"\s*2>\s*nul\b", "", cmd, flags=re.I)
    # `find . -name "*.py"` (and -iname) -> Get-ChildItem -Recurse -Filter
    m = re.match(
        r'find\s+(\S+)\s+(?:-type\s+f\s+)?-i?name\s+["\']?([^"\']+)["\']?\s*$', cmd
    )
    if m:
        path = "." if m.group(1) in (".", "./") else m.group(1)
        return f'Get-ChildItem -Path {path} -Recurse -File -Filter {m.group(2)}'
    toks = cmd.split()
    if toks:
        alias = {
            "ls": "Get-ChildItem", "ll": "Get-ChildItem", "dir": "Get-ChildItem",
            "cat": "Get-Content", "pwd": "Get-Location", "clear": "Clear-Host",
            "rm": "Remove-Item", "cp": "Copy-Item", "mv": "Move-Item",
            "which": "Get-Command", "head": "Get-Content", "wc": "Measure-Object",
        }.get(toks[0])
        if alias and toks[0] not in ("head", "wc"):
            toks[0] = alias
            cmd = " ".join(toks)
    # `grep PATTERN` (not part of a pipe stage keyword) -> Select-String PATTERN
    cmd = re.sub(r"(?<!\S)grep\s+(-\w+\s+)*", "Select-String ", cmd)
    return cmd


def _fix_forfiles_size(cmd: str) -> str:
    """Rebuild a `forfiles ... /C "..."` size filter into a known-good form.

    The 1.5B model reliably picks the byte threshold but mangles the /C payload
    (repeats @fsize, drops @path, adds stray slashes). When we can see an
    `@fsize <op> <bytes>` test, normalise the whole command to:
        forfiles /P <path> /S /M * /C "cmd /c if @fsize GEQ <bytes> echo @path (@fsize bytes)"
    """
    if "forfiles" not in cmd.lower():
        return cmd
    thr = re.search(r"@fsize\s*(?:GEQ|GTR|>=?|-ge|-gt)\s*(\d[\d,]*)", cmd, re.I)
    if not thr:
        return cmd
    n = thr.group(1).replace(",", "")
    p = re.search(r"/P\s+(\"[^\"]+\"|\S+)", cmd, re.I)
    path = p.group(1) if p else "C:\\"
    return (
        f'forfiles /P {path} /S /M * '
        f'/C "cmd /c if @fsize GEQ {n} echo @path (@fsize bytes)" 2>nul'
    )


def _windows_cmd_compat_fix(cmd: str) -> str:
    """Nudge POSIX-isms into classic cmd.exe builtins."""
    cmd = re.sub(r"\s*2>\s*/dev/null\b", " 2>nul", cmd)
    toks = cmd.split()
    if toks:
        alias = {
            "ls": "dir", "ll": "dir", "cat": "type", "pwd": "cd", "clear": "cls",
            "rm": "del", "cp": "copy", "mv": "move", "which": "where",
        }.get(toks[0])
        if alias:
            toks[0] = alias
            cmd = " ".join(toks)
    cmd = re.sub(r"(?<!\S)grep\s+(-\w+\s+)*", "findstr ", cmd)
    cmd = _fix_forfiles_size(cmd)
    return cmd


# --- Register the profiles and select the active one --------------------------
_MACOS_IPV4 = (
    "ipconfig getifaddr $(route -n get default 2>/dev/null "
    "| awk '/interface:/{print $2}')"
)
_MACOS_WIFI = (
    'networksetup -getairportnetwork "$(networksetup -listallhardwareports '
    "| awk '/Wi-Fi|AirPort/{getline; print $2; exit}')\""
)
_LINUX_IPV4 = "ip route get 1.1.1.1 2>/dev/null | awk '{print $7; exit}'"
_LINUX_WIFI = (
    "iwgetid -r 2>/dev/null || nmcli -t -f active,ssid dev wifi 2>/dev/null "
    "| sed -n 's/^yes://p'"
)
_LINUX_BATT = (
    "acpi -b 2>/dev/null || cat /sys/class/power_supply/BAT*/capacity 2>/dev/null"
)

PROFILES["macos"] = PlatformProfile(
    name="macos",
    os_label="macOS (Bash / Zsh)",
    stat_flag="-f", stat_size="%z", stat_name="%N", stat_mtime="%Sm",
    stat_interprets_escapes=False,
    primary_ipv4=_MACOS_IPV4,
    wifi_ssid=_MACOS_WIFI,
    battery="pmset -g batt",
    compat_fix=_macos_compat_fix,
    prompt_extra="""Prefer standard macOS utilities that ship by default. Avoid GNU-only flags
(--max-depth, grep -P, --time-style, du -s combined with du -d, stat -c). For
file metadata use `stat -f` and consider piping through `column -t`.

For "my IP address", resolve the active interface rather than hard-coding en0:
  ipconfig getifaddr $(route -n get default 2>/dev/null | awk '/interface:/{print $2}')

Examples (user request -> exact command):
Q: tell me my ip address, the date, and my battery level
A: ipconfig getifaddr en0; date; pmset -g batt
Q: show me all files larger than 3gb, with sizes shown in GB not bytes
A: find / -type f -size +3G -exec stat -f "%z bytes  %N" {} \\; 2>/dev/null | awk '{print $1/1024/1024/1024 "GB"}'
Q: list the 10 largest files in my Downloads folder
A: ls -lS ~/Downloads | tail -n +2 | head -n 10
Q: find all .py files in the current project
A: find . -name "*.py"
Q: count how many .log files are in /var/log
A: find /var/log -type f -name "*.log" 2>/dev/null | wc -l
Q: show a table of the 15 biggest files with size and modified date
A: find / -type f -size +1G -exec stat -f "%z  %Sm  %N" {} \\; 2>/dev/null | sort -rn | head -n 15 | column -t
Q: show the top 5 largest directories in the current folder
A: du -d 1 -h . | sort -rh | head -n 5
Q: list all folders here
A: ls -d */""",
    danger_extra=(),
    trivial_cmds=frozenset(
        "ls pwd clear echo whoami hostname uptime uname cal id sw_vers df date find".split()
    ),
)

PROFILES["linux"] = PlatformProfile(
    name="linux",
    os_label="Linux (Bash, GNU coreutils)",
    stat_flag="-c", stat_size="%s", stat_name="%n", stat_mtime="%y",
    stat_interprets_escapes=True,
    primary_ipv4=_LINUX_IPV4,
    wifi_ssid=_LINUX_WIFI,
    battery=_LINUX_BATT,
    compat_fix=_linux_compat_fix,
    prompt_extra="""Target GNU coreutils. Use `stat -c` (not BSD `stat -f`): %s = size in bytes,
%n = name, %y = mtime. `du --max-depth=N`, `grep -P` for PCRE, `sort -h` for
human sizes are all fine.

For "my IP address":
  ip route get 1.1.1.1 2>/dev/null | awk '{print $7; exit}'
For the current Wi-Fi network: iwgetid -r
For battery: acpi -b   (or cat /sys/class/power_supply/BAT0/capacity)

Examples (user request -> exact command):
Q: tell me my ip address, the date, and my battery level
A: ip route get 1.1.1.1 2>/dev/null | awk '{print $7; exit}'; date; acpi -b
Q: show me all files larger than 3gb, with sizes shown in GB not bytes
A: find / -type f -size +3G -exec stat -c "%s bytes  %n" {} \\; 2>/dev/null | awk '{print $1/1024/1024/1024 "GB"}'
Q: list the 10 largest files in my Downloads folder
A: ls -lS ~/Downloads | tail -n +2 | head -n 10
Q: find all .py files in the current project
A: find . -name "*.py"
Q: count how many .log files are in /var/log
A: find /var/log -type f -name "*.log" 2>/dev/null | wc -l
Q: show a table of the 15 biggest files with size and modified date
A: find / -type f -size +1G -exec stat -c "%s  %y  %n" {} \\; 2>/dev/null | sort -rn | head -n 15 | column -t
Q: show the top 5 largest directories in the current folder
A: du -h --max-depth=1 . | sort -rh | head -n 5
Q: list all folders here
A: ls -d */""",
    danger_extra=(
        (re.compile(r"(?:^|(?<=[\s;&|(]))(?:apt|apt-get|dnf|yum|pacman|snap)\b.*"
                    r"\b(?:remove|purge|autoremove|-R\w*)\b", re.S | re.I),
         "removes system packages"),
        (re.compile(r"(?:^|(?<=[\s;&|(]))systemctl\s+(?:stop|disable|mask)\b", re.S),
         "stops or disables a system service"),
    ),
    trivial_cmds=frozenset(
        "ls pwd clear echo whoami hostname uptime uname arch id df date find "
        "lsb_release free lsblk".split()
    ),
)

_B_WIN = r"(?:^|(?<=[\s;&|(]))"  # command-token start, Windows dialects

PROFILES["windows-powershell"] = PlatformProfile(
    name="windows-powershell",
    os_label="Windows (PowerShell)",
    family="windows",
    compat_fix=_windows_ps_compat_fix,
    primary_ipv4="(Get-NetIPConfiguration | Where-Object {$_.IPv4DefaultGateway}"
                 ").IPv4Address.IPAddress",
    wifi_ssid="(netsh wlan show interfaces | Select-String '^\\s*SSID')"
              ".ToString().Split(':')[-1].Trim()",
    battery="(Get-CimInstance Win32_Battery).EstimatedChargeRemaining",
    prompt_extra="""Target Windows PowerShell. Use cmdlets, not POSIX tools: Get-ChildItem (not
ls/find), Get-Content (not cat), Select-String (not grep), Measure-Object (not
wc), Sort-Object, Select-Object. For file size/date, project Name, Length,
LastWriteTime. Recurse with -Recurse; suppress errors with
-ErrorAction SilentlyContinue (never `2>/dev/null`).

For "my IP address":
  (Get-NetIPConfiguration | ? {$_.IPv4DefaultGateway}).IPv4Address.IPAddress
For the current Wi-Fi network: netsh wlan show interfaces | Select-String 'SSID'
For battery: (Get-CimInstance Win32_Battery).EstimatedChargeRemaining

Examples (user request -> exact command):
Q: tell me my ip address, the date, and my battery level
A: (Get-NetIPConfiguration | ? {$_.IPv4DefaultGateway}).IPv4Address.IPAddress; Get-Date; (Get-CimInstance Win32_Battery).EstimatedChargeRemaining
Q: show me all files larger than 3gb, with sizes shown in GB not bytes
A: Get-ChildItem C:\\ -Recurse -File -ErrorAction SilentlyContinue | Where-Object Length -gt 3GB | Select-Object FullName, @{n='GB';e={[math]::Round($_.Length/1GB,2)}}
Q: list the 10 largest files in my Downloads folder
A: Get-ChildItem $HOME\\Downloads -File | Sort-Object Length -Descending | Select-Object -First 10 Name, Length
Q: find all .py files in the current project
A: Get-ChildItem -Recurse -File -Filter *.py
Q: count how many .log files are in C:\\Logs
A: (Get-ChildItem C:\\Logs -Recurse -File -Filter *.log -ErrorAction SilentlyContinue).Count
Q: show a table of the 15 biggest files with size and modified date
A: Get-ChildItem C:\\ -Recurse -File -ErrorAction SilentlyContinue | Sort-Object Length -Descending | Select-Object -First 15 Name, Length, LastWriteTime | Format-Table
Q: show the top 5 largest directories in the current folder
A: Get-ChildItem -Directory | Select-Object Name, @{n='MB';e={[math]::Round((Get-ChildItem $_.FullName -Recurse -File -ErrorAction SilentlyContinue | Measure-Object Length -Sum).Sum/1MB,1)}} | Sort-Object MB -Descending | Select-Object -First 5
Q: list all folders here
A: Get-ChildItem -Directory""",
    danger_extra=(
        (re.compile(_B_WIN + r"(?:Remove-Item|ri|rm|del|erase|rd|rmdir)(?![\w-])",
                    re.I | re.S), "deletes files or folders"),
        (re.compile(r"-Recurse\b.*?-Force\b|-Force\b.*?-Recurse\b", re.I | re.S),
         "recursive force delete/overwrite"),
        (re.compile(_B_WIN + r"(?:Format-Volume|Clear-Disk|Initialize-Disk|diskpart"
                    r"|Format(?:\.com)?)(?![\w-])", re.I | re.S),
         "formats or wipes a disk"),
        (re.compile(_B_WIN + r"Set-ExecutionPolicy(?![\w-])", re.I | re.S),
         "changes the script execution policy"),
        (re.compile(_B_WIN + r"(?:Stop|Restart)-Computer(?![\w-])", re.I | re.S),
         "shuts down or reboots the machine"),
        (re.compile(_B_WIN + r"(?:Stop-Process|kill|spps|taskkill)(?![\w-])",
                    re.I | re.S), "kills a running process"),
        (re.compile(r"Start-Process\b.*?-Verb\s+RunAs", re.I | re.S),
         "relaunches elevated (UAC)"),
        (re.compile(_B_WIN + r"(?:reg\s+delete|net\s+user\b.*?/delete)", re.I | re.S),
         "deletes a registry key or user account"),
        (re.compile(r">>?\s*(?:[A-Za-z]:\\|\\\\|\$HOME|\$env:)", re.S),
         "redirects output onto a real path"),
        (re.compile(r"(?:Out-File|Set-Content|Add-Content)\b", re.I | re.S),
         "writes a file"),
    ),
    trivial_cmds=frozenset(
        "Get-ChildItem gci ls dir Get-Location pwd gl Get-Date whoami hostname "
        "Get-Content cat type Get-Process ps Get-ComputerInfo Get-Host "
        "Get-Location Get-Volume".split()
    ),
)

PROFILES["windows-cmd"] = PlatformProfile(
    name="windows-cmd",
    os_label="Windows (cmd.exe)",
    family="windows",
    compat_fix=_windows_cmd_compat_fix,
    primary_ipv4='ipconfig | findstr /C:"IPv4"',
    wifi_ssid='netsh wlan show interfaces | findstr /C:"SSID"',
    battery="wmic path Win32_Battery get EstimatedChargeRemaining",
    prompt_extra="""Target classic Windows cmd.exe (NOT PowerShell). Use builtins and bundled
tools: dir (not ls/find), type (not cat), findstr (not grep), where, ipconfig,
systeminfo. `dir /s /b` recurses and prints bare paths; `dir /a:-d /o:-s`
sorts by size. Suppress errors with `2>nul`. cmd has no real pipeline maths --
keep commands simple.

findstr matches TEXT in a line, never a number range -- NEVER use it to filter
by file size or date. To filter files by size use `forfiles` with `@fsize`
(bytes): 1 KB=1024, 1 MB=1048576, 1 GB=1073741824 (3 GB = 3221225472,
500 MB = 524288000). The /C command MUST be exactly, with @path only ONCE:
  /C "cmd /c if @fsize GEQ <bytes> echo @path (@fsize bytes)"
cmd cannot do float maths, so report the size in bytes -- do not try to
convert to GB.

For "my IP address": ipconfig | findstr /C:"IPv4"
For the current Wi-Fi network: netsh wlan show interfaces | findstr /C:"SSID"
For battery: wmic path Win32_Battery get EstimatedChargeRemaining

Examples (user request -> exact command):
Q: tell me my ip address, the date, and my battery level
A: ipconfig | findstr /C:"IPv4" & date /t & wmic path Win32_Battery get EstimatedChargeRemaining
Q: list all files larger than 3 gb, show the size
A: forfiles /P C:\\ /S /M * /C "cmd /c if @fsize GEQ 3221225472 echo @path (@fsize bytes)" 2>nul
Q: find files bigger than 500mb in my Downloads folder
A: forfiles /P "%USERPROFILE%\\Downloads" /S /M * /C "cmd /c if @fsize GEQ 524288000 echo @path (@fsize bytes)" 2>nul
Q: list the 10 largest files in my Downloads folder
A: dir /a:-d /o:-s "%USERPROFILE%\\Downloads"
Q: find all .py files in the current project
A: dir /s /b *.py
Q: count how many .log files are in C:\\Logs
A: dir /s /b C:\\Logs\\*.log 2>nul | find /c /v ""
Q: show all files in this folder with size and date
A: dir /a:-d
Q: list all folders here
A: dir /a:d /b
Q: what's my computer name and windows version
A: hostname & ver""",
    danger_extra=(
        (re.compile(_B_WIN + r"(?:del|erase)(?![\w-])", re.I | re.S),
         "deletes files (del)"),
        (re.compile(_B_WIN + r"(?:rd|rmdir)(?![\w-])(?:.*?/s)?", re.I | re.S),
         "removes a directory tree (rd /s)"),
        (re.compile(_B_WIN + r"(?:format|diskpart|label)(?![\w-])", re.I | re.S),
         "formats or relabels a disk"),
        (re.compile(_B_WIN + r"(?:reg\s+delete|sc\s+(?:delete|stop)|net\s+user\b.*?/delete)",
                    re.I | re.S), "deletes a registry key, service, or account"),
        (re.compile(_B_WIN + r"(?:takeown|icacls\b.*?/grant|attrib\b.*?[+-]r)",
                    re.I | re.S), "changes ownership or permissions"),
        (re.compile(_B_WIN + r"(?:shutdown|taskkill)(?![\w-])", re.I | re.S),
         "shuts down or kills processes"),
        (re.compile(r">>?\s*(?:[A-Za-z]:\\|\\\\|%\w)", re.S),
         "redirects output onto a real path"),
    ),
    trivial_cmds=frozenset(
        "dir cd pwd whoami hostname ver vol tree type systeminfo ipconfig "
        "tasklist".split()
    ),
)

# Active profile + everything derived from it. Bound here for import-time
# references and (re)bound by _activate() below -- tests swap profiles through it.
PROFILE = _get_profile()
SYSTEM_PROMPT = build_system_prompt(PROFILE)
_PRIMARY_IPV4 = PROFILE.primary_ipv4
_WIFI_DEVICE = PROFILE.wifi_ssid
_STAT_TAB_EXPR = ""


def _activate(profile: "PlatformProfile") -> None:
    """Point the module at `profile`: rebuild the system prompt, the net-info
    snippets, the `stat` helper, the danger list and the trivial-command set.
    Called once at import; tests call it again to exercise another dialect.
    """
    global PROFILE, SYSTEM_PROMPT, _PRIMARY_IPV4, _WIFI_DEVICE, _STAT_TAB_EXPR
    global _DANGEROUS, _TRIVIAL_CMDS
    PROFILE = profile
    SYSTEM_PROMPT = build_system_prompt(profile)
    _PRIMARY_IPV4 = profile.primary_ipv4
    _WIFI_DEVICE = profile.wifi_ssid
    _STAT_TAB_EXPR = (
        profile.stat_expr(f"{profile.stat_size}\t{profile.stat_name}")
        if profile.family == "posix" else ""
    )
    _DANGEROUS = _DANGEROUS_BASE + list(profile.danger_extra)
    _TRIVIAL_CMDS = profile.trivial_cmds


def compat_fix(cmd: str) -> str:
    """Dialect-specific rewrite pass for the active platform."""
    return PROFILE.compat_fix(cmd)


def fix_stat_format_escapes(cmd: str) -> str:
    """BSD/macOS `stat -f FORMAT` does not interpret backslash escapes -- a
    `\\t`/`\\n` the model writes into the format string (trying to tab- or
    newline-separate fields for a downstream awk) comes out as the literal
    two characters `\\`+`t`, not a real tab. Nothing errors -- it just makes
    `awk -F'\\t'` fail to split, silently dropping every field after the
    first. Turn those literal escapes into the real bytes stat needs.

    No-op where `stat` DOES expand escapes (GNU `stat -c`).
    """
    if PROFILE.stat_interprets_escapes:
        return cmd

    def repl(m):
        body = m.group("body").replace("\\t", "\t").replace("\\n", "\n")
        return f'stat {m.group("flag")} "{body}"'
    return re.sub(r'stat\s+(?P<flag>-[fc])\s+"(?P<body>[^"]*)"', repl, cmd)


_UNIT_DIVISOR = {"B": 1, "KB": 1024, "MB": 1024 ** 2, "GB": 1024 ** 3, "TB": 1024 ** 4}

# `stat -f "%z..%N"` (BSD) or `stat -c "%s..%n"` (GNU) -- matches either dialect.
_STAT_FMT_RE = r'stat\s+-[fc]\s+"%[zs][^"]*%[Nn]"'

# `-exec <stat> {} \; [2>/dev/null] | awk '{print $1/.../... "UNIT"}'` --
# the model's own attempt to convert stat's byte count to KB/MB/GB/TB.
_STAT_AWK_UNIT_PAT = re.compile(
    r'-exec\s+' + _STAT_FMT_RE + r'\s+\{\}\s+\\;'
    r'(\s*2>/dev/null)?\s*\|\s*awk\s+\'\{[^}]*\$1((?:\s*/\s*\d+)+)\s*"?(\w{1,2})B?"?[^}]*\}\'',
    re.I,
)


def fix_size_unit_math(cmd: str) -> str:
    """Repair a stat-to-KB/MB/GB/TB conversion with the wrong number of /1024s.

    The model frequently mislabels its own math -- e.g. `$1/1024/1024 "GB"`
    is actually MB (three divisions make a GB, not two) -- and drops the
    filename from the print, leaving a bare number with no idea which file
    it is. Rewrites to the divisor implied by the label the model wrote, and
    keeps the path (tab-delimited, so a path containing spaces survives).
    """
    m = _STAT_AWK_UNIT_PAT.search(cmd)
    if not m:
        return cmd
    unit = (m.group(3) or "").upper()
    unit = unit if unit.endswith("B") else unit + "B"
    target = _UNIT_DIVISOR.get(unit)
    if not target:
        return cmd
    stderr = m.group(1) or ""
    replacement = (
        f'-exec {_STAT_TAB_EXPR} {{}} \\;' + stderr +
        f" | awk -F'\\t' '{{printf \"%.2f {unit}\\t%s\\n\", $1/{target}, $2}}'"
    )
    return cmd[:m.start()] + replacement + cmd[m.end():]


# `-exec <stat printing "%z bytes  %N"> {} \;` at the very end of the command
# (our own default stat format), with nothing converting the bytes afterwards.
_STAT_BYTES_TAIL = re.compile(
    r'-exec\s+stat\s+-[fc]\s+"%[zs]\s+bytes\s+%[Nn]"\s+\{\}\s+\\;(\s*2>/dev/null)?\s*$'
)


def report_size_in_filter_unit(cmd: str) -> str:
    """`list files larger than 3gb` should answer in GB, not raw bytes.

    When a `find -size +N{G,M,K}` lists matches through the default
    byte-printing stat and nothing converts them, append an awk that reports
    each size in the same unit the filter used, keeping the path.
    """
    m = _STAT_BYTES_TAIL.search(cmd)
    if not m:
        return cmd
    size = re.search(r"-size\s+[-+]?\d+\s*([GMK])\b", cmd, re.I)
    if not size:
        return cmd
    unit = size.group(1).upper() + "B"
    target = _UNIT_DIVISOR[unit]
    stderr = m.group(1) or ""
    tail = (
        f'-exec {_STAT_TAB_EXPR} {{}} \\;' + stderr +
        f" | awk -F'\\t' '{{printf \"%.2f {unit}\\t%s\\n\", $1/{target}, $2}}'"
    )
    return cmd[:m.start()] + tail


# Commands whose failure should not abort the rest of a chain of lookups.
_READONLY_INFO = frozenset("""
ipconfig ifconfig ip networksetup nmcli pmset acpi scutil sysctl system_profiler
networkquality iwgetid date whoami hostname id uptime sw_vers uname arch
sysadminctl lsblk free lsof ps df du ls cat stat wc echo printf head tail grep
awk sed defaults
""".split())


def prefer_semicolons(cmd: str) -> str:
    """Turn `a && b && c` into `a; b; c` when every link is an independent
    read-only lookup, so one failing part no longer hides the others.

    Left untouched when a link could legitimately depend on the previous one
    (unknown leading command) or when `||` / a subshell `&&` is present.
    """
    if "&&" not in cmd or "||" in cmd or re.search(r"\$\([^)]*&&", cmd):
        return cmd
    parts = re.split(r"\s*&&\s*", cmd)
    lead = re.compile(r"^\(?\s*([A-Za-z_\[][\w./\[-]*)")
    for part in parts:
        m = lead.match(part.strip())
        head = m.group(1) if m else ""
        if head not in _READONLY_INFO and head not in ("if", "for", "while", "case", "test", "["):
            return cmd
    return "; ".join(p.strip() for p in parts)


# --- Safety classifier -----------------------------------------------------
# Commands matching any pattern below are gated behind an explicit typed
# "yes" instead of the plain y/N prompt. This is a speed bump on destructive
# or privilege-escalating actions, not a hard block.
_B = r"(?:^|(?<=[\s;&|(]))"  # position at the start of a command token

_DANGEROUS_BASE = [
    (re.compile(_B + r"rm(?!\w)", re.S), "deletes files (rm)"),
    (re.compile(_B + r"rmdir(?!\w)", re.S), "removes directories (rmdir)"),
    (re.compile(_B + r"(?:mv|rename)(?!\w)", re.S), "moves or renames files"),
    (re.compile(_B + r"dd(?!\w)", re.S), "writes directly to a device (dd)"),
    (re.compile(_B + r"(?:mkfs|newfs)\w*(?!\w)", re.S), "formats a filesystem"),
    (re.compile(_B + r"(?:shred|srm)(?!\w)", re.S), "securely wipes files"),
    (re.compile(_B + r"(?:chmod|chown|chgrp|chflags)(?!\w).*?(?<!\w)-R(?!\w)", re.S),
     "recursively changes permissions or ownership"),
    (re.compile(_B + r"find(?!\w).*?(?:(?<!\w)-delete(?!\w)|-exec\s+rm(?!\w))", re.S),
     "deletes matched files (find)"),
    (re.compile(r">>?\s*(?!/dev/null\b)(?:/|~|\$HOME)", re.S),
     "redirects output onto an absolute path"),
    (re.compile(_B + r"sudo(?!\w)", re.S), "runs with root privileges (sudo)"),
    (re.compile(r":\s*\(\s*\)\s*\{.*?:.*?\|.*?&.*?\}", re.S), "looks like a fork bomb"),
    (re.compile(_B + r"(?:curl|wget)(?!\w).*?\|\s*(?:sudo\s+)?(?:sh|bash|zsh)(?!\w)", re.S),
     "pipes a download straight into a shell"),
    (re.compile(_B + r"git(?!\w)\s+(?:reset\s+--hard|clean\s+-\S*f|checkout\s+--)", re.S),
     "discards uncommitted git changes"),
]

# Dialect-specific danger patterns (package removal, service control, ...) are
# appended per-profile by _activate(), which also seeds _DANGEROUS / _TRIVIAL_CMDS.
_DANGEROUS: list = list(_DANGEROUS_BASE)
_activate(_get_profile())


def classify_command(command: str):
    """Classify a command's risk.

    Returns (verdict, reason): verdict is "ok" (normal y/N prompt is enough)
    or "danger" (require an explicit typed "yes" first).
    """
    for pattern, reason in _DANGEROUS:
        if pattern.search(command):
            return "danger", reason
    # A quoted payload (e.g. `sh -c "rm -rf ~"`, `find -exec sh -c '...'`) can
    # hide a destructive command behind quotes, which dodges the token-start
    # boundary the patterns above require. Re-scan each quoted string on its
    # own -- it starts fresh, so the same boundary matches normally.
    for dq, sq in re.findall(r"\"([^\"]*)\"|'([^']*)'", command):
        payload = dq or sq
        for pattern, reason in _DANGEROUS:
            if pattern.search(payload):
                return "danger", reason
    return "ok", ""


# Bare, argument-free lookups that only ever read/display state -- safe to
# run without asking (the per-platform set, seeded by _activate()). Anything
# with a pipe, redirect, chaining, or substitution is excluded below
# regardless of the command name.
_TRIVIAL_CMDS: frozenset = PROFILE.trivial_cmds

# find flags that always mutate, write, or hand control to `find` itself
# (interactive -ok/-okdir) rather than just printing paths -- disqualifying
# no matter what command follows them.
_FIND_UNSAFE_FLAGS = frozenset("-ok -okdir -delete -fprint -fprint0 -fprintf".split())

# -exec / -execdir is only trivial when the executed command is itself a
# read-only lookup (this is exactly what repair_command's own `-exec stat ...`
# rewrite produces for "show me size/date" queries) -- anything else
# (rm, mv, sh, chmod, ...) still needs a confirmation.
_FIND_SAFE_EXEC_CMDS = frozenset(
    "stat ls cat file wc md5 md5sum shasum basename dirname echo".split()
)

# Read-only formatting/filtering stages that may trail a trivial command via a
# pipe without making it need confirmation (this is what the size-in-GB repair
# and the "biggest files" example produce).
_SAFE_FILTER_CMDS = frozenset("awk column sort head tail wc uniq cat tr cut nl".split())

# awk/sed program constructs that reach outside pure text formatting.
_AWK_UNSAFE = re.compile(r"\b(?:system|getline|close|fflush|ENVIRON)\b|>|`|\|")

# PowerShell: read-only source cmdlets (may lead a pipeline) and read-only
# filter/format stages (may follow a pipe). Anything not listed -- ForEach-Object,
# Copy-Item, Out-File, ... -- makes the command need a confirmation.
_PS_READ_CMDLETS = frozenset(x.lower() for x in (
    "Get-ChildItem gci ls dir Get-Content gc cat type Get-Item gi "
    "Get-ItemProperty Get-Location pwd gl Get-Date Get-Process gps ps "
    "Get-Service Get-ComputerInfo Get-Host Get-Volume Get-PSDrive "
    "Get-Command gcm Get-Member gm Get-NetIPConfiguration Get-NetIPAddress "
    "Get-CimInstance Get-WmiObject Get-Clipboard Get-Random Get-History "
    "whoami hostname".split()
))
_PS_SAFE_FILTERS = frozenset(x.lower() for x in (
    "Where-Object where ? Select-Object select Sort-Object sort "
    "Measure-Object measure Format-Table ft Format-List fl Format-Wide fw "
    "Format-Custom Group-Object group Out-String Out-Host Out-Default "
    "Select-String sls Get-Unique ConvertTo-Json ConvertTo-Csv "
    "ConvertTo-Html ConvertFrom-Json".split()
))
# Mutating cmdlet verbs -- if any appears (even inside a Where-Object block) the
# command is not auto-run.
_PS_MUTATING = re.compile(
    r"(?i)(?<![\w-])(?:Remove|Set|Clear|New|Stop|Start|Restart|Move|Copy|"
    r"Rename|Out-File|Export|Import|Invoke|Write|Add|Register|Unregister|"
    r"Disable|Enable|Suspend|Resume|Send|Format-Volume|iex)-?\w*"
)


def _ps_strip(s: str) -> str:
    """Drop quoted strings and balanced {..} / @{..} blocks from a PowerShell
    command, so a `;` or `|` inside a calculated property or a Where-Object
    filter block isn't read as a command separator by is_trivial().
    """
    s = re.sub(r"'[^']*'|\"[^\"]*\"", "", s)
    prev = None
    while prev != s:                       # collapse innermost braces outward
        prev = s
        s = re.sub(r"@?\{[^{}]*\}", "", s)
    return s

# stderr/stdout redirections to the bit-bucket -- harmless, stripped before the
# redirect check so they don't disqualify an otherwise trivial command.
_NULL_REDIR = re.compile(r"\s*\d?>&?\s*(?:/dev/null|[12])\b")


def is_trivial(command: str) -> bool:
    """True for a simple read-only lookup that needs no confirmation.

    Conservative: no chaining (`;`, `&&`, `||`), substitution, or writing
    redirect. `date` is only trivial bare or with -u/+FORMAT (a bare
    positional arg SETS the clock). `find` is only trivial when every
    -exec runs a read-only command and no -ok/-okdir/-delete/-fprint* is
    present. A trailing pipe is allowed ONLY into pure read-only formatters
    (awk/sort/head/column/...), and an awk program that calls system/getline
    or redirects still disqualifies.
    """
    cmd = _NULL_REDIR.sub(" ", command.strip()).strip()

    if PROFILE.family == "windows":
        low = re.sub(r"\s*2>\s*(?:nul|\$null)\s*$", "", cmd, flags=re.I).strip()

        if PROFILE.name == "windows-powershell":
            # A read-only Get-* source, optionally piped through read-only
            # filter/format stages. A mutating verb anywhere (incl. inside a
            # script block) disqualifies -- checked on the raw string first.
            if _PS_MUTATING.search(low):
                return False
            # Strip strings + {..}/@{..} blocks so a `;` or `|` inside a
            # calculated property (`@{n='GB';e={...}}`) or a Where-Object filter
            # block isn't mistaken for a command chain.
            bare = _ps_strip(low)
            if re.search(r"[<>`;&]|\$\(", bare):
                return False
            stages = [s.strip() for s in bare.split("|")]
            if not stages or not stages[0].split():
                return False
            if stages[0].split()[0].lower() not in _PS_READ_CMDLETS:
                return False
            ok = _PS_READ_CMDLETS | _PS_SAFE_FILTERS
            return all(
                st.split() and st.split()[0].lower() in ok for st in stages[1:]
            )

        # cmd.exe has no real pipelines -- a single bare lookup only.
        if re.search(r"[|&<>`;]|\$\(|\$\{", low):
            return False
        toks = low.split()
        return bool(toks) and toks[0].lower() in {c.lower() for c in _TRIVIAL_CMDS}

    if re.search(r"[&<>`]|\$\(", cmd):
        return False
    if re.search(r"(?<!\\);", cmd):  # a *literal* ; chains commands; find's
        return False                 # own \; terminator is left alone

    # Peel off a trailing read-only formatter pipeline; the first stage is the
    # real command and must stand on its own as trivial.
    stages = cmd.split("|")
    for stage in stages[1:]:
        toks = stage.split()
        if not toks or toks[0] not in _SAFE_FILTER_CMDS:
            return False
        if toks[0] == "tail" and any(f in toks for f in ("-f", "-F")):
            return False
        if toks[0] == "awk":
            for dq, sq in re.findall(r"'([^']*)'|\"([^\"]*)\"", stage):
                if _AWK_UNSAFE.search(dq or sq):
                    return False
    tokens = stages[0].split()
    if not tokens:
        return False
    head = tokens[0]
    if head not in _TRIVIAL_CMDS:
        return False
    if head == "date" and not all(t == "-u" or t.startswith("+") for t in tokens[1:]):
        return False
    if head == "find":
        rest = tokens[1:]
        for i, tok in enumerate(rest):
            if tok in _FIND_UNSAFE_FLAGS:
                return False
            if tok in ("-exec", "-execdir"):
                exec_cmd = rest[i + 1].rsplit("/", 1)[-1] if i + 1 < len(rest) else ""
                if exec_cmd not in _FIND_SAFE_EXEC_CMDS:
                    return False
    return True


def get_shell_command(user_query: str, extra_turns: list[dict] | None = None) -> str:
    """Translate a natural-language request into a single shell command.

    Pure "text in -> command out": raises on model/inference failure and
    does NOT touch history. Callers record the turn via record_turn().

    `extra_turns` is appended after the user query -- the refine-on-failure
    path uses it to hand back the previous command plus an error / a hint.
    """
    ensure_logging()

    # Build the message list: system prompt + recent conversation history + new query.
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend(history)
    messages.append({"role": "user", "content": user_query})
    messages.extend(extra_turns or [])

    logger.info("=" * 60)
    logger.info(f"USER QUERY: {user_query}")
    if extra_turns:
        logger.info(f"REFINE TURNS: {extra_turns}")

    try:
        t0 = time.perf_counter()
        if _resolve_backend() == "mlx":
            model, tokenizer = get_local_model()
            prompt = tokenizer.apply_chat_template(
                messages, tokenize=False, add_generation_prompt=True
            )
            raw = mlx_generate(
                model, tokenizer, prompt,
                verbose=False, max_tokens=MAX_TOKENS,  # greedy argmax sampler
            )
        else:  # llama.cpp
            get_local_model()  # ensure the singleton is loaded
            raw = _llama_chat(messages, MAX_TOKENS)
        elapsed = time.perf_counter() - t0
    except Exception as e:
        logger.error(f"ERROR: {e}")
        raise

    raw = raw.strip()
    extracted = extract_command(raw)
    if PROFILE.family == "posix":
        command = fix_find_exec_terminator(extracted)
        command = repair_command(command)
        command = compat_fix(command)
        command = fix_stat_format_escapes(command)
        command = fix_size_unit_math(command)
        command = report_size_in_filter_unit(command)
        command = prefer_semicolons(command)
        command = quiet_broad_find(command)
    else:
        # The POSIX passes above are all find/stat/awk/&&/2>/dev/null specific;
        # the Windows dialects only need their own compat_fix.
        command = compat_fix(extracted)
    command = quote_spaced_path(command)

    logger.info(f"RAW MODEL RESPONSE ({elapsed:.2f}s): {raw}")
    if command != extracted:
        logger.info(f"REPAIRED: {extracted}  ->  {command}")
    logger.info(f"EXTRACTED COMMAND: {command}")
    return command


_SINGLE_PATH_VERBS = re.compile(
    r"^(cat|bat|less|more|head|tail|wc|nl|file|stat|open|xdg-open|ls|cd|"
    r"type|Get-Content|gc)\s+(.+)$", re.I,
)


def quote_spaced_path(command: str) -> str:
    """Quote an unquoted path that contains spaces.

    The 1.5B model writes `cat ./Library/Application Support/x.txt` -- the shell
    then splits it into two failing args. When the whole argument, joined,
    actually exists on disk, wrap it in quotes. The `exists` check keeps this
    from touching real multi-argument commands.
    """
    m = _SINGLE_PATH_VERBS.match(command.strip())
    if not m:
        return command
    verb, rest = m.group(1), m.group(2).strip()
    if rest.startswith("-") or " " not in rest:
        return command
    if any(ch in rest for ch in "|<>;&`\"'*?$()"):
        return command
    probe = os.path.expanduser(os.path.expandvars(rest))
    if os.path.exists(probe):
        return f'{verb} "{rest}"'
    return command


# Command names the model commonly emits. Used only to detect output where
# several answers were concatenated with no separator.
_KNOWN_CMDS = frozenset("""
find grep egrep fgrep rg ls ll du df cat tac head tail wc sort uniq cut tr
awk sed nl paste join comm tee xargs echo printf stat file basename dirname
ps top kill pkill pgrep lsof nc netstat ss ifconfig ipconfig networksetup
curl wget scp rsync ssh tar zip unzip gzip gunzip git svn hg mdfind
python python3 pip pip3 node npm npx yarn pnpm ruby perl php go cargo java
brew port docker kubectl systemctl launchctl defaults osascript pmset
date cal uptime whoami id hostname uname sw_vers pwd mkdir rmdir touch
rm mv cp ln chmod chown chgrp chflags dd shred open say pbcopy pbpaste
column jq yq less more man which env sleep
""".split())

# Tokens that legitimately introduce another command name after them.
_CMD_WRAPPERS = frozenset(
    "xargs sudo time env nice ionice nohup watch command exec then else do".split()
)

# Commands that essentially never appear as a bare argument or grep pattern,
# so a second one mid-segment is a reliable "two answers were joined" signal.
# Kept deliberately tight: things like python / node / docker / curl show up as
# grep patterns and pgrep/kill targets, so they are NOT listed here.
_LEADING_CMDS = frozenset("""
find git du df rsync mdfind kubectl systemctl launchctl
networksetup ifconfig ipconfig netstat lsof pmset sw_vers
""".split())


def looks_malformed(command: str):
    """Reject output that is not a single runnable command.

    Catches the 1.5B model's habit of gluing several answers together with no
    separator (e.g. ``... | head -n 5 find . -name ...``), plus dangling
    operators, unterminated ``-exec``, and trailing line continuations.

    Returns (is_bad, reason); reason is "" when the command looks fine.
    """
    cmd = command.strip()
    if not cmd:
        return True, "empty"
    if cmd.endswith("\\"):
        return True, "ends with a bare line-continuation backslash"
    if re.search(r"(\|\|?|&&?|;)\s*$", cmd):
        return True, "ends with a dangling shell operator"

    # Model degeneration: fed several requests at once, the 1.5B often loops,
    # repeating the same fragment over and over into one giant "command".
    if len(cmd) > 400:
        return True, "the model looped -- ask one thing at a time"
    pipes = cmd.split("|")
    if len(pipes) >= 6:
        norm = [re.sub(r"\s+", " ", p).strip() for p in pipes]
        if len(set(norm)) <= len(norm) // 2:  # half or more of the stages repeat
            return True, "the model looped -- ask one thing at a time"

    # find -exec / -execdir must be terminated by \; or {} + before the next pipe
    for m in re.finditer(r"-execdir\b|-exec\b", cmd):
        seg = re.split(r"\|\||&&|\|", cmd[m.end():], maxsplit=1)[0]
        if "\\;" not in seg and not re.search(r"\{\}\s*\+", seg):
            return True, "find -exec is not terminated with \\; or +"

    # Concatenated commands: within one pipeline/list segment, a second known
    # command name that no wrapper token introduced means two answers were
    # joined without a | && ; between them.
    scrub = re.sub(r"\"[^\"]*\"|'[^']*'", "", cmd)  # ignore quoted text
    for seg in re.split(r"\|\||&&|[|;&]", scrub):
        expecting_cmd = True
        seen_cmd = False
        for tok in seg.split():
            if tok in ("$(", "`", "(", "{") or tok.endswith("=$(") or tok.endswith("$("):
                expecting_cmd = True
                continue
            if tok in _CMD_WRAPPERS or tok in ("-exec", "-execdir", "-ok"):
                expecting_cmd = True
                continue
            base = tok.rsplit("/", 1)[-1]
            if base in _KNOWN_CMDS:
                if seen_cmd and not expecting_cmd and base in _LEADING_CMDS:
                    return True, (
                        f"looks like two commands were joined "
                        f"(no separator before '{base}')"
                    )
                seen_cmd, expecting_cmd = True, False
            else:
                expecting_cmd = False
    return False, ""


def record_turn(user_query: str, command: str) -> None:
    """Append this turn to the in-memory rolling history."""
    history.append({"role": "user", "content": user_query})
    history.append({"role": "assistant", "content": command})
    del history[:-MAX_HISTORY]  # keep only the last MAX_HISTORY messages


def _kill_group(proc: "subprocess.Popen") -> None:
    """SIGTERM the child's whole process group, then SIGKILL if it lingers."""
    try:
        pgid = os.getpgid(proc.pid)
    except ProcessLookupError:
        return
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(pgid, sig)
        except ProcessLookupError:
            return
        try:
            proc.wait(timeout=2)
            return
        except subprocess.TimeoutExpired:
            continue


def _exec_spec(command: str):
    """Return (target, shell_bool) for subprocess: the active profile decides.

    POSIX and Windows-cmd run the string through the system shell (sh / cmd.exe,
    which is what `shell=True` uses). Windows-PowerShell wraps it so the model's
    cmdlet one-liners are interpreted by PowerShell, not cmd.exe.
    """
    if PROFILE.exec_argv is not None:
        return PROFILE.exec_argv(command)
    if PROFILE.name == "windows-powershell":
        exe = shutil.which("pwsh") or shutil.which("powershell") or "powershell"
        # Wrap so a *terminating* error -> exit 1, but non-terminating errors
        # (e.g. Get-ChildItem -Recurse skipping folders it can't read, with
        # -ErrorAction SilentlyContinue) don't -- otherwise `powershell -Command`
        # exits 1 for a pipeline that actually succeeded and produced output,
        # which then trips the refine-on-failure prompt.
        wrapped = f"try {{ {command} }} catch {{ [Console]::Error.WriteLine($_); exit 1 }}; exit 0"
        return [exe, "-NoProfile", "-NonInteractive", "-Command", wrapped], False
    return command, True


def _run_blocking(command: str, timeout: int) -> int:
    target, use_shell = _exec_spec(command)
    try:
        return subprocess.run(target, shell=use_shell, timeout=timeout).returncode
    except subprocess.TimeoutExpired:
        print(f"\nCommand timed out after {timeout}s and was killed.")
        logger.warning(f"TIMEOUT after {timeout}s: {command}")
        return 124
    except KeyboardInterrupt:
        # Ctrl-C reached us via the console; the child got it too and is
        # stopping. Treat it as "stop this command", not "crash the REPL".
        print("\n\033[2m[stopped -- back to AI-Shell]\033[0m")
        logger.info(f"INTERRUPTED (Ctrl-C): {command}")
        return 130


def _run_interruptible(command: str, timeout: int) -> int:
    """Run `command` while watching the keyboard: a lone ESC (or Ctrl-C)
    stops it and hands control back to the AI-Shell prompt. Unix tty only.
    """
    target, use_shell = _exec_spec(command)
    proc = subprocess.Popen(
        target, shell=use_shell, stdin=subprocess.DEVNULL, start_new_session=True
    )
    fd = sys.stdin.fileno()
    saved = termios.tcgetattr(fd)
    deadline = time.monotonic() + timeout
    try:
        tty.setcbreak(fd)
        # also clear ISIG so Ctrl-C arrives as a byte we handle (stop the
        # command), not a SIGINT that would unwind the whole REPL.
        mode = termios.tcgetattr(fd)
        mode[3] &= ~termios.ISIG
        termios.tcsetattr(fd, termios.TCSANOW, mode)
        while True:
            rc = proc.poll()
            if rc is not None:
                return rc
            if time.monotonic() > deadline:
                _kill_group(proc)
                print(f"\nCommand timed out after {timeout}s and was killed.")
                logger.warning(f"TIMEOUT after {timeout}s: {command}")
                return 124
            if _select.select([fd], [], [], 0.1)[0]:
                ch = os.read(fd, 1)
                if ch == b"\x1b":
                    # lone ESC stops; an escape *sequence* (arrow keys) does not
                    if _select.select([fd], [], [], 0.04)[0]:
                        os.read(fd, 16)  # drain and ignore the sequence
                        continue
                elif ch != b"\x03":  # anything but ESC / Ctrl-C: ignore
                    continue
                _kill_group(proc)
                print("\n\033[2m[stopped -- back to AI-Shell]\033[0m")
                logger.info(f"INTERRUPTED (ESC): {command}")
                return 130
    except KeyboardInterrupt:
        _kill_group(proc)
        print("\n\033[2m[stopped -- back to AI-Shell]\033[0m")
        logger.info(f"INTERRUPTED (Ctrl-C): {command}")
        return 130
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, saved)


def _kill_tree_windows(proc: "subprocess.Popen") -> None:
    """Kill the child and everything it spawned (taskkill /T)."""
    try:
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    except OSError:
        proc.terminate()
    try:
        proc.wait(timeout=3)
    except subprocess.TimeoutExpired:
        pass


def _run_interruptible_windows(command: str, timeout: int) -> int:
    """Windows tty equivalent of _run_interruptible: poll the keyboard with
    msvcrt; a lone ESC (or Ctrl-C) kills the command's process tree and
    returns to the AI-Shell prompt.
    """
    target, use_shell = _exec_spec(command)
    proc = subprocess.Popen(
        target, shell=use_shell, stdin=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
    )
    deadline = time.monotonic() + timeout
    try:
        while True:
            rc = proc.poll()
            if rc is not None:
                return rc
            if time.monotonic() > deadline:
                _kill_tree_windows(proc)
                print(f"\nCommand timed out after {timeout}s and was killed.")
                logger.warning(f"TIMEOUT after {timeout}s: {command}")
                return 124
            if msvcrt.kbhit():
                ch = msvcrt.getwch()
                if ch in ("\x00", "\xe0"):  # a function/arrow key -- drain, ignore
                    msvcrt.getwch()
                    continue
                if ch not in ("\x1b", "\x03"):  # only ESC / Ctrl-C stop it
                    continue
                _kill_tree_windows(proc)
                print("\n\033[2m[stopped -- back to AI-Shell]\033[0m")
                logger.info(f"INTERRUPTED (ESC): {command}")
                return 130
            time.sleep(0.05)
    except KeyboardInterrupt:
        _kill_tree_windows(proc)
        print("\n\033[2m[stopped -- back to AI-Shell]\033[0m")
        logger.info(f"INTERRUPTED (Ctrl-C): {command}")
        return 130


# The last command run(), its exit code, and (when we captured it) its output.
# Feeds the refine-on-failure prompt in handle_query.
_LAST_RUN: dict = {"command": None, "exit": None, "output": ""}

# Recursive scanners can run for a long time and stream progress -- keep them on
# the interruptible path (live output + ESC) rather than buffering their output.
_RECURSIVE_SCAN = re.compile(r"^\s*(?:find|forfiles)\b|(?<![\w-])-Recurse\b", re.I)


def _run_capture(command: str, timeout: int) -> tuple[int, str]:
    """Run to completion, echo what it printed, and return (exit_code, output).

    Used for quick read-only lookups so a failure's output can be handed back
    to the model. No ESC-to-stop -- these finish in well under a second.
    """
    target, use_shell = _exec_spec(command)
    try:
        p = subprocess.run(
            target, shell=use_shell, timeout=timeout,
            capture_output=True, text=True,
        )
        out, err, rc = p.stdout or "", p.stderr or "", p.returncode
    except subprocess.TimeoutExpired as e:
        out = (e.stdout or "") if isinstance(e.stdout, str) else ""
        err = (e.stderr or "") if isinstance(e.stderr, str) else ""
        print(f"\nCommand timed out after {timeout}s and was killed.")
        return 124, out + err
    except KeyboardInterrupt:
        print("\n\033[2m[stopped -- back to AI-Shell]\033[0m")
        return 130, ""
    if out:
        sys.stdout.write(out if out.endswith("\n") else out + "\n")
    if err:
        sys.stderr.write(err if err.endswith("\n") else err + "\n")
    return rc, out + err


def run_command(command: str, timeout: int = EXEC_TIMEOUT,
                capture: bool | None = None) -> int:
    """Execute a shell command, streaming its output, and return the exit code.

    While it runs, pressing ESC (or Ctrl-C) stops just that command and
    returns to the prompt -- the REPL keeps going. Falls back to a plain
    blocking run when stdin is not an interactive terminal. Quick read-only
    lookups are captured instead (see `_run_capture` / `_LAST_RUN`).
    """
    ensure_logging()
    if capture is None:
        capture = is_trivial(command) and not _RECURSIVE_SCAN.search(command)
    output = None
    tty_in = sys.stdin.isatty()
    try:
        if capture:
            rc, output = _run_capture(command, timeout)
        elif tty_in and termios is not None:
            rc = _run_interruptible(command, timeout)
        elif tty_in and msvcrt is not None:
            rc = _run_interruptible_windows(command, timeout)
        else:
            rc = _run_blocking(command, timeout)
    except (OSError, ValueError) as e:
        print(f"\nCould not execute command: {e}")
        logger.error(f"EXECUTION ERROR ({e}): {command}")
        _LAST_RUN.update(command=command, exit=1, output="")
        return 1
    _LAST_RUN.update(
        command=command, exit=rc,
        output=(output or "")[-2000:],
    )
    logger.info(f"EXECUTED (exit {rc}): {command}")
    # Surface a non-zero exit so a silent short-circuit isn't mistaken for
    # "it did nothing" -- e.g. `ipconfig getifaddr en0` prints nothing and
    # exits 1 when en0 has no IP, which aborts the rest of an && chain.
    if rc not in (0, 130):
        last = command.rsplit("|", 1)[-1].split()
        if rc == 1 and last and last[0] in ("grep", "egrep", "fgrep", "rg", "ag"):
            print("\033[2m(no matches)\033[0m")  # grep exits 1 when nothing matched
        else:
            note = ""
            if "&&" in command:
                note = " -- an earlier step in the && chain failed, so the rest was skipped"
            print(f"\033[2m[exit status {rc}{note}]\033[0m")
    return rc


_prev_cwd: str | None = None


def _short_cwd() -> str:
    cwd, home = os.getcwd(), os.path.expanduser("~")
    if cwd == home:
        return "~"
    if cwd.startswith(home + os.sep):
        return "~" + cwd[len(home):]
    return cwd


def _resolve_cd_target(arg: str | None) -> str:
    if arg is None:
        return os.path.expanduser("~")
    if arg == "-":
        return _prev_cwd or os.getcwd()
    if len(arg) >= 2 and arg[0] == arg[-1] and arg[0] in "\"'":
        arg = arg[1:-1]
    arg = os.path.expandvars(os.path.expanduser(arg))
    if not os.path.isabs(arg):
        arg = os.path.join(os.getcwd(), arg)
    return os.path.normpath(arg)


def apply_cd(command: str):
    """Apply a leading `cd` to THIS process so it persists across turns.

    `subprocess` children can't change the REPL's cwd, so `cd ~`, `cd ..`,
    `cd /x` etc. are handled in-process with os.chdir. Returns
    (handled, remaining_command): if the command was `cd <dir> && <rest>`
    (or `;`), <rest> is returned to run from the new directory.
    """
    global _prev_cwd
    # `cd` on every dialect, plus PowerShell's Set-Location / sl / chdir aliases.
    m = re.match(
        r"^(?:cd|chdir|sl|Set-Location)(?:\s+(\"[^\"]*\"|'[^']*'|\S+))?"
        r"\s*(?:(?:&&|;)\s*(.+))?$",
        command.strip(), re.I,
    )
    if not m:
        return False, command
    target = _resolve_cd_target(m.group(1))
    try:
        old = os.getcwd()
        os.chdir(target)
        _prev_cwd = old
        print(f"\033[2m(now in {_short_cwd()})\033[0m")
        logger.info(f"CHDIR: {old} -> {os.getcwd()}")
    except OSError as e:
        print(f"\033[1;31mcd: {e}\033[0m")
        return True, ""
    return True, (m.group(2) or "").strip()


def confirm_command(command: str) -> bool:
    """The guard-rail gate: destructive commands need a typed 'yes', bare
    read-only lookups auto-run, everything else asks y/N. The single place
    this decision lives -- handle_query calls it once per attempt.
    """
    verdict, reason = classify_command(command)
    if verdict == "danger":
        print(f"\033[1;31m!  This command {reason}.\033[0m")
        return input(
            "Type 'yes' in full to run it (anything else cancels): "
        ).strip().lower() == "yes"
    if is_trivial(command):
        print("\033[2m(auto-running: simple read-only command)\033[0m")
        return True
    return input("Execute this command? (y/N): ").strip().lower() == "y"


def _refine(query: str, prev_command: str, feedback: str) -> "str | None":
    """One refine round-trip: hand the model the previous command + a failure
    message or hint, return a fresh command (None on inference failure)."""
    logger.info(f"REFINE: {prev_command!r}  <-  {feedback!r}")
    try:
        return get_shell_command(query, extra_turns=[
            {"role": "assistant", "content": prev_command},
            {"role": "user", "content": feedback},
        ])
    except Exception as e:
        print(f"\n\033[1;31mCould not refine the command: {e}\033[0m")
        return None


def handle_query(query: str) -> None:
    """Translate one request, then propose / guard / (optionally) run it.

    On a non-zero exit or a rejection, offer to hand the failure (or a
    one-line hint) back to the model for a corrected command -- up to
    REFINE_MAX times (SHELLAI_NO_REFINE=1 disables it).
    """
    try:
        command = get_shell_command(query)
    except Exception as e:
        print(f"\n\033[1;31mCould not generate a command: {e}\033[0m")
        return

    print(f"\nProposed Command: \033[1;32m{command}\033[0m")
    ran = command  # what we record to history at the end

    for attempt in range(1 + REFINE_MAX):
        last_attempt = NO_REFINE or attempt == REFINE_MAX

        bad, why = looks_malformed(command)
        if bad:
            print(f"\033[1;31mSkipping malformed command ({why}).\033[0m")
            if any(k in why for k in ("two commands", "joined", "looped", "-exec")):
                print("Looks like several requests at once -- ask one thing per "
                      'line (or wrap one multi-line request in """).')
            break

        # `cd` must change THIS process's directory to persist across turns.
        handled, command = apply_cd(command)
        if handled and not command:
            break
        ran = command

        if not confirm_command(command):
            if last_attempt:
                print("Execution cancelled.")
                break
            note = input(
                "what should it do differently? (Enter to just retry): "
            ).strip()
            nxt = _refine(query, command,
                          f"I don't want to run that."
                          f"{(' ' + note) if note else ''} "
                          "Give a different command for the same request.")
            if nxt is None:
                break
            command = nxt
            print(f"\nProposed Command: \033[1;32m{command}\033[0m")
            continue

        sys.stdout.flush()  # the child writes to the fd directly; don't let
        rc = run_command(command)  # our own buffered prints land after its output
        if rc in (0, 130) or last_attempt:
            break
        ans = input(
            f"\n\033[2m↻ that exited {rc}. Fix it? (y/N, or type a hint)\033[0m "
        ).strip()
        if not ans or ans.lower() in ("n", "no"):
            break
        hint = "" if ans.lower() in ("y", "yes") else ans
        fb = f"That command failed (exit {rc})."
        if _LAST_RUN.get("command") == command and _LAST_RUN.get("output"):
            fb += "\nOutput:\n" + _LAST_RUN["output"]
        if hint:
            fb += f"\nHint: {hint}"
        fb += "\nGive a corrected command for the same request."
        nxt = _refine(query, command, fb)
        if nxt is None:
            break
        command = nxt
        print(f"\nProposed Command: \033[1;32m{command}\033[0m")
        ran = command

    record_turn(query, ran)


def read_request():
    """Read one logical request from the prompt.

    A plain line + Enter still submits immediately. For multi-line input the
    end of the request is marked explicitly, two ways:

      * end a line with a backslash  ->  it continues on the next line (like a
        shell); the request ends at the first line with NO trailing backslash.
      * type  \"\"\"  (or ```) alone on a line  ->  everything up to the next
        matching  \"\"\"  line is one request. Handy for pasting a block.

    Returns the assembled request, or None on EOF (Ctrl-D).
    """
    try:
        first = input(f"\n[{_short_cwd()}] AI-Shell> ")
    except EOFError:
        return None
    except KeyboardInterrupt:  # Ctrl-C at the prompt: quit cleanly, no traceback
        return None

    fence = first.strip()
    if fence in ('"""', "'''", "```"):
        block = []
        while True:
            try:
                ln = input("...> ")
            except EOFError:
                break
            except KeyboardInterrupt:  # abandon the block, back to the prompt
                print("^C")
                return ""
            if ln.strip() == fence:  # closing fence ends the request
                break
            block.append(ln)
        return "\n".join(block)

    # Backslash continuation: keep reading while the last line ends with "\".
    lines = [first]
    while lines[-1].rstrip().endswith("\\"):
        lines[-1] = lines[-1].rstrip()[:-1]
        try:
            lines.append(input("...> "))
        except EOFError:
            break
        except KeyboardInterrupt:
            print("^C")
            return ""
    return " ".join(part.strip() for part in lines).strip()


_BANNER_ART = r"""
 █████╗ ██╗    ███████╗██╗  ██╗███████╗██╗     ██╗
██╔══██╗██║    ██╔════╝██║  ██║██╔════╝██║     ██║
███████║██║    ███████╗███████║█████╗  ██║     ██║
██╔══██║██║    ╚════██║██╔══██║██╔══╝  ██║     ██║
██║  ██║██║    ███████║██║  ██║███████╗███████╗███████╗
╚═╝  ╚═╝╚═╝    ╚══════╝╚═╝  ╚═╝╚══════╝╚══════╝╚══════╝
"""


def _print_banner() -> None:
    """A big AI-SHELL wordmark + an info box, Claude-Code style.

    Falls back to a one-liner if the terminal can't encode the box-drawing
    glyphs (legacy Windows code pages) or SHELLAI_NO_BANNER is set.
    """
    if os.environ.get("SHELLAI_NO_BANNER") or (
        (sys.stdout.encoding or "").lower() not in ("utf-8", "utf8", "cp65001")
    ):
        print(f"AI-SHELL  --  local shell copilot ({PROFILE.os_label})")
        return

    use_color = sys.stdout.isatty() and not os.environ.get("NO_COLOR")

    def c(text: str, code: str) -> str:
        return f"\033[{code}m{text}\033[0m" if use_color else text

    for line in _BANNER_ART.strip("\n").splitlines():
        print(c(line, "38;5;44"))  # teal
    print(c("  🐚  local shell copilot", "1") +
          c("  ·  nothing leaves your machine", "2"))

    w = 54  # inner width of the box (ASCII-only so padding is exact everywhere)
    rows = [
        c("platform ", "2") + PROFILE.os_label,
        "",
        c('multi-line: end a line with \\  or wrap a block in """', "2"),
        c('ESC stops a running command  ·  type "exit" to quit', "2"),
    ]

    def pad(s: str) -> str:
        vis = len(re.sub(r"\033\[[0-9;]*m", "", s))
        return s + " " * max(0, w - vis)

    dim = "2"
    print()
    print(c("╭" + "─" * (w + 2) + "╮", dim))
    for r in rows:
        print(c("│ ", dim) + pad(r) + c(" │", dim))
    print(c("╰" + "─" * (w + 2) + "╯", dim))


def main():
    ensure_logging()
    load_history()
    get_local_model()
    _print_banner()
    while True:
        request = read_request()
        if request is None:  # Ctrl-D or Ctrl-C at the prompt
            print("\nbye 👋")
            break
        request = request.strip()
        if not request:
            continue
        if request.lower() in ("exit", "quit"):
            print("bye 👋")
            break
        try:
            handle_query(request)
        except KeyboardInterrupt:
            # Ctrl-C during model generation / a command: drop this request,
            # return to the prompt instead of unwinding the whole program.
            print("\n\033[2m[interrupted -- back to AI-Shell]\033[0m")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
