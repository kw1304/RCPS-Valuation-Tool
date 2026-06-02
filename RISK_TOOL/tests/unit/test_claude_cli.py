from risk.infrastructure.llm import claude_cli


def test_resolve_claude_returns_str_or_none_no_raise():
    # 실행 환경에 따라 경로(str) 또는 None — 절대 raise하지 않아야 함
    r = claude_cli.resolve_claude()
    assert r is None or isinstance(r, str)


def test_unavailable_when_which_none(monkeypatch):
    monkeypatch.setattr(claude_cli.shutil, "which", lambda _: None)
    monkeypatch.delenv("WAT_CLAUDE_PATH", raising=False)
    assert claude_cli.resolve_claude() is None
    assert claude_cli.claude_available() is False


def test_complete_returns_none_without_subprocess(monkeypatch):
    # claude 미설치 시 subprocess 호출 없이 즉시 None (degrade)
    monkeypatch.setattr(claude_cli.shutil, "which", lambda _: None)
    monkeypatch.delenv("WAT_CLAUDE_PATH", raising=False)

    def _boom(*a, **k):  # subprocess가 호출되면 테스트 실패
        raise AssertionError("subprocess must not be invoked when claude absent")

    monkeypatch.setattr(claude_cli.subprocess, "Popen", _boom)
    assert claude_cli.claude_complete("x") is None


def test_override_path_used(monkeypatch, tmp_path):
    fake = tmp_path / "claude.exe"
    fake.write_text("")
    monkeypatch.setenv("WAT_CLAUDE_PATH", str(fake))
    assert claude_cli.resolve_claude() == str(fake)
    assert claude_cli.claude_available() is True
