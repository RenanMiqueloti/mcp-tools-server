"""Smoke tests for mcp-tools-server.

Validates repo layout, README branding and that the module imports without
the MCP SDK installed (the server gracefully degrades to a no-op when
``mcp`` is missing).
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_repo_layout() -> None:
    assert (ROOT / "server.py").is_file()
    assert (ROOT / "requirements.txt").is_file()
    assert (ROOT / ".env.example").is_file()
    assert (ROOT / "LICENSE").is_file()
    assert (ROOT / "pyproject.toml").is_file()


def test_readme_present_and_branded() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "mcp-tools-server" in readme
    assert "MCP" in readme


def test_module_imports_without_mcp() -> None:
    """The module must import even when mcp is absent — handlers stay usable."""
    import server

    assert hasattr(server, "datetime_info")
    assert hasattr(server, "calculate")
    assert hasattr(server, "text_stats")
    assert hasattr(server, "json_extract")
    assert hasattr(server, "search_knowledge")
    assert hasattr(server, "http_get")
