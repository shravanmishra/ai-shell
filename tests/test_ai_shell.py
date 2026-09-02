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
        assert app.is_trivial("Get-ChildItem | Remove-Item") is False
        assert app.classify_command("Remove-Item -Recurse -Force C:\\tmp")[0] == "danger"
        assert app.classify_command("Get-ChildItem C:\\")[0] == "ok"
        target, use_shell = app._exec_spec("Get-ChildItem")
        assert use_shell is False and target[-2:] == ["-Command", "Get-ChildItem"]


def test_windows_cmd_profile():
    with _with_profile("windows-cmd"):
        assert "cmd.exe" in app.SYSTEM_PROMPT
        # size filtering must go through forfiles/@fsize, never findstr
        assert "forfiles" in app.SYSTEM_PROMPT and "@fsize" in app.SYSTEM_PROMPT
        assert app.compat_fix("cat x.txt") == "type x.txt"
        assert app.compat_fix("ls") == "dir"
        assert app.is_trivial("dir") is True
        assert app.classify_command("del /q C:\\*")[0] == "danger"
        assert app.classify_command("rd /s /q C:\\build")[0] == "danger"
        assert app._exec_spec("dir") == ("dir", True)


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
