"""The Windows / WSL test scripts (docs/WINDOWS_WSL_TESTING.md) cannot run here, so guard what breaks them silently."""
from pathlib import Path

REMOTE = Path(__file__).resolve().parents[1] / "scripts"


def test_powershell_scripts_are_ascii():
    # Windows PowerShell 5.1 reads a .ps1 without BOM in the ANSI code page: any non-ASCII byte can garble it.
    for f in REMOTE.rglob("*.ps1"):
        data = f.read_bytes()
        assert data.isascii(), f"{f.name}: non-ASCII at byte {next(i for i, b in enumerate(data) if b > 127)}"


def test_shell_scripts_use_lf_line_endings():
    # WSL bash fails on CRLF ("$'\\r': command not found"); .gitattributes keeps *.sh as LF on checkout.
    for f in REMOTE.rglob("*.sh"):
        assert b"\r" not in f.read_bytes(), f.name
    assert "*.sh text eol=lf" in (REMOTE.parent / ".gitattributes").read_text(encoding="utf-8")
