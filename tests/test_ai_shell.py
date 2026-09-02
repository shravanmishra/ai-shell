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
    assert app.PROFILE.name in ("macos", "linux")
    assert app.SYSTEM_PROMPT.startswith("You are a precise shell-command translator")
