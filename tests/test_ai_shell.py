"""Smoke tests for the pure (no-model) parts of ai_shell.app."""

import ai_shell.app as app


def test_extract_command_strips_fence_and_prose():
    assert app.extract_command("Here you go:\n```\nls -la\n```") == "ls -la"
    assert app.extract_command("```bash\ncd /tmp && \\\nls\n```") == "cd /tmp && \\\nls"
    assert app.extract_command("Sure! the command is:\nls -la") == "ls -la"


def test_classify_command_flags_destructive():
    assert app.classify_command("ls -la")[0] == "ok"
    assert app.classify_command("rm -rf ~")[0] == "danger"
    assert app.classify_command("sudo reboot")[0] == "danger"
    assert app.classify_command('find . -exec sh -c "rm {}" \\;')[0] == "danger"


def test_is_trivial_allows_reads_only():
    assert app.is_trivial("pwd") is True
    assert app.is_trivial("ls -la") is True
    assert app.is_trivial('find . -name "*.py"') is True
    assert app.is_trivial("rm -rf ~") is False
    assert app.is_trivial("ls | sh") is False
    assert app.is_trivial("date 12312359") is False  # would set the clock


def test_looks_malformed_catches_concatenation():
    assert app.looks_malformed("ls -la")[0] is False
    bad, why = app.looks_malformed(
        'find . -name "*.py" -exec wc -l {} \\; | sort | head -n 5 find . -name x'
    )
    assert bad is True


def test_apply_cd_is_in_process(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "sub").mkdir()
    handled, rest = app.apply_cd("cd sub")
    assert handled and rest == ""
    assert app.os.path.basename(app.os.getcwd()) == "sub"
    handled, rest = app.apply_cd("cd .. && ls")
    assert handled and rest == "ls"


def test_platform_profile_selected():
    assert app.PROFILE.name in (
        "macos", "linux", "windows-powershell", "windows-cmd"
    )
    assert app.SYSTEM_PROMPT.startswith("You are a precise shell-command translator")


def _with_profile(name):
    """Context-manager-ish helper: activate `name`, yield, restore the default."""
    import contextlib

    @contextlib.contextmanager
    def _cm():
        saved = app.PROFILE
        app._activate(app.PROFILES[name])
        try:
            yield app
        finally:
            app._activate(saved)
    return _cm()


def test_windows_powershell_profile():
    with _with_profile("windows-powershell"):
        assert "PowerShell" in app.SYSTEM_PROMPT
        assert app.compat_fix("ls") == "Get-ChildItem"
        assert app.compat_fix("cat notes.txt") == "Get-Content notes.txt"
        assert app.is_trivial("Get-ChildItem") is True
        # a read-only Get-* pipeline auto-runs; a mutating stage does not
        assert app.is_trivial(
            "Get-ChildItem C:\\ -Recurse -File | Where-Object Length -gt 3GB "
            "| Select-Object FullName, Length"
        ) is True
        # `;` / `|` inside a calculated property or filter block is not a chain
        assert app.is_trivial(
            "Get-ChildItem C:\\ -Recurse -File -ErrorAction SilentlyContinue "
            "| Where-Object Length -gt 1GB | Select-Object FullName, "
            "@{n='GB';e={[math]::Round($_.Length/1GB,2)}}"
        ) is True
        assert app.is_trivial(
            'Get-ChildItem | Where-Object { $_.Extension -eq ".log" } '
            "| Select-Object Name"
        ) is True
        assert app.is_trivial("Get-ChildItem; Get-Date") is False  # real chain
        assert app.is_trivial("Get-ChildItem | Remove-Item") is False
        assert app.is_trivial("Get-ChildItem | ForEach-Object { Remove-Item $_ }") is False
        assert app.is_trivial("Get-ChildItem | Out-File list.txt") is False
        assert app.classify_command("Remove-Item -Recurse -Force C:\\tmp")[0] == "danger"
        assert app.classify_command("Get-ChildItem C:\\")[0] == "ok"
        target, use_shell = app._exec_spec("Get-ChildItem")
        assert use_shell is False and target[-2] == "-Command"
        # wrapped so non-terminating errors don't force exit 1
        assert "try { Get-ChildItem }" in target[-1] and target[-1].endswith("exit 0")


def test_windows_cmd_profile():
    with _with_profile("windows-cmd"):
        assert "cmd.exe" in app.SYSTEM_PROMPT
        # size filtering must go through forfiles/@fsize, never findstr
        assert "forfiles" in app.SYSTEM_PROMPT and "@fsize" in app.SYSTEM_PROMPT
        assert app.compat_fix("cat x.txt") == "type x.txt"
        # a mangled forfiles /C payload is normalised to the known-good form
        bad = ('forfiles /P C:\\ /S /M * /C '
               '"cmd /c if @fsize GEQ 1073741824 echo @fsize /@fsize" 2>nul')
        fixed = app.compat_fix(bad)
        assert fixed.count("@path") == 1
        assert "@fsize GEQ 1073741824 echo @path (@fsize bytes)" in fixed
        assert app.compat_fix("ls") == "dir"
        assert app.is_trivial("dir") is True
        assert app.classify_command("del /q C:\\*")[0] == "danger"
        assert app.classify_command("rd /s /q C:\\build")[0] == "danger"
        assert app._exec_spec("dir") == ("dir", True)


def test_run_blocking_swallows_ctrl_c(monkeypatch):
    def boom(*a, **k):
        raise KeyboardInterrupt
    monkeypatch.setattr(app.subprocess, "run", boom)
    # Ctrl-C during a command must return 130, not propagate a traceback.
    assert app._run_blocking("sleep 100", 5) == 130


def test_fix_find_exec_terminator():
    f = app.fix_find_exec_terminator
    assert f(r"find / -type f -size +50M -exec ls -lh {} \ 2>/dev/null") == \
        r"find / -type f -size +50M -exec ls -lh {} \; 2>/dev/null"
    assert f(r"find . -type f -exec ls -lh {} ;") == r"find . -type f -exec ls -lh {} \;"
    assert f(r"find /var -type f -exec stat {} 2>/dev/null") == \
        r"find /var -type f -exec stat {} \; 2>/dev/null"
    # already valid -- untouched
    assert f(r'find . -name "*.py" -exec wc -l {} \;') == r'find . -name "*.py" -exec wc -l {} \;'
    assert f(r"find . -exec grep foo {} +") == r"find . -exec grep foo {} +"
    assert f(r'find . -name "*.log"') == r'find . -name "*.log"'


def test_quote_spaced_path(tmp_path, monkeypatch):
    d = tmp_path / "Application Support" / "CloudDocs"
    d.mkdir(parents=True)
    f = d / "note.txt"
    f.write_text("hi")
    monkeypatch.chdir(tmp_path)

    assert app.quote_spaced_path(
        "cat ./Application Support/CloudDocs/note.txt"
    ) == 'cat "./Application Support/CloudDocs/note.txt"'
    # a real multi-arg command (paths don't join into something on disk) is left alone
    assert app.quote_spaced_path("cat a.txt b.txt") == "cat a.txt b.txt"
    # flags / already-quoted / pipes are left alone
    assert app.quote_spaced_path("head -n 5 x y") == "head -n 5 x y"
    assert app.quote_spaced_path('cat "a b.txt"') == 'cat "a b.txt"'
    assert app.quote_spaced_path("ls | wc -l") == "ls | wc -l"


def test_find_with_suppressed_errors_exit1_is_success(monkeypatch):
    monkeypatch.setattr(app, "_run_blocking", lambda c, t: 1)
    monkeypatch.setattr(app, "_run_capture", lambda c, t: (1, ""))
    # find exits 1 just for skipping unreadable dirs -> treated as success
    assert app.run_command('find . -type f -name "*.xls" 2>/dev/null') == 0
    # a non-find command that exits 1 is still a failure
    assert app.run_command("grep -q needle 2>/dev/null haystack.txt") == 1


def test_confirm_command_gate(monkeypatch):
    assert app.confirm_command("ls -la") is True            # trivial -> auto
    monkeypatch.setattr("builtins.input", lambda *_: "yes")
    assert app.confirm_command("rm -rf /tmp/x") is True     # danger + typed "yes"
    monkeypatch.setattr("builtins.input", lambda *_: "y")
    assert app.confirm_command("rm -rf /tmp/x") is False    # bare "y" is not enough
    assert app.confirm_command("cp a b") is True            # non-trivial + "y"


def _script_gsc(monkeypatch, replies):
    """Replace get_shell_command with a scripted stub; return the call log."""
    calls, it = [], iter(replies)
    def fake(query, extra_turns=None):
        calls.append({"query": query, "extra_turns": extra_turns})
        return next(it)
    monkeypatch.setattr(app, "get_shell_command", fake)
    monkeypatch.setattr(app, "record_turn", lambda *a: None)
    monkeypatch.setattr(app, "REFINE_MAX", 2)
    monkeypatch.setattr(app, "NO_REFINE", False)
    return calls


def test_refine_on_failure(monkeypatch):
    calls = _script_gsc(monkeypatch, ["ls /nope", "ls -la"])
    runs = []
    def fake_run(cmd, *a, **k):
        runs.append(cmd)
        rc = 2 if len(runs) == 1 else 0
        app._LAST_RUN.update(
            command=cmd, exit=rc,
            output="ls: /nope: No such file or directory" if rc else "",
        )
        return rc
    monkeypatch.setattr(app, "run_command", fake_run)
    monkeypatch.setattr(app, "confirm_command", lambda c: True)
    monkeypatch.setattr("builtins.input", lambda *_: "y")   # yes, fix it

    app.handle_query("list files")

    assert runs == ["ls /nope", "ls -la"]
    assert len(calls) == 2
    turns = calls[1]["extra_turns"]
    assert turns[0] == {"role": "assistant", "content": "ls /nope"}
    assert "exit 2" in turns[1]["content"] and "No such file" in turns[1]["content"]


def test_refine_failure_prompt_accepts_a_hint(monkeypatch):
    calls = _script_gsc(monkeypatch, ["ls /nope", "ls ."])
    monkeypatch.setattr(app, "run_command",
                        lambda c, *a, **k: 2 if c == "ls /nope" else 0)
    monkeypatch.setattr(app, "confirm_command", lambda c: True)
    monkeypatch.setattr("builtins.input", lambda *_: "look in the current directory")

    app.handle_query("show that file")

    assert len(calls) == 2   # the free-text answer is treated as "yes, + hint"
    fb = calls[1]["extra_turns"][1]["content"]
    assert "Hint: look in the current directory" in fb


def test_refine_on_rejection(monkeypatch):
    calls = _script_gsc(monkeypatch, ["du -ah .", "find ~/Downloads -type f"])
    monkeypatch.setattr(app, "run_command", lambda c, *a, **k: 0)
    approvals = iter([False, True])
    monkeypatch.setattr(app, "confirm_command", lambda c: next(approvals))
    monkeypatch.setattr("builtins.input", lambda *_: "in ~/Downloads, files only")

    app.handle_query("biggest files")

    assert len(calls) == 2
    fb = calls[1]["extra_turns"][1]["content"]
    assert "don't want to run that" in fb and "in ~/Downloads, files only" in fb


def test_refine_disabled(monkeypatch):
    calls = _script_gsc(monkeypatch, ["ls /nope", "UNUSED"])
    monkeypatch.setattr(app, "NO_REFINE", True)
    monkeypatch.setattr(app, "run_command", lambda c, *a, **k: 2)
    monkeypatch.setattr(app, "confirm_command", lambda c: True)
    seen = []
    monkeypatch.setattr("builtins.input", lambda p="": seen.append(p) or "y")

    app.handle_query("list files")

    assert len(calls) == 1        # no refine round-trip
    assert seen == []             # never prompted "fix it?"


def test_refine_budget(monkeypatch):
    calls = _script_gsc(monkeypatch, ["c0", "c1", "c2", "c3"])
    monkeypatch.setattr(app, "REFINE_MAX", 1)
    monkeypatch.setattr(app, "run_command", lambda c, *a, **k: 1)
    monkeypatch.setattr(app, "confirm_command", lambda c: True)
    monkeypatch.setattr("builtins.input", lambda *_: "y")

    app.handle_query("do a thing")

    assert len(calls) == 2        # initial + exactly one refine, then stop


def test_detect_windows_shell(monkeypatch):
    monkeypatch.setenv("SHELLAI_SHELL", "cmd")
    assert app._detect_windows_shell() == "cmd"
    monkeypatch.setenv("SHELLAI_SHELL", "pwsh")
    assert app._detect_windows_shell() == "powershell"
    monkeypatch.delenv("SHELLAI_SHELL", raising=False)
    monkeypatch.setenv("PROMPT", "$P$G")
    assert app._detect_windows_shell() == "cmd"
    monkeypatch.delenv("PROMPT", raising=False)
    assert app._detect_windows_shell() == "powershell"
