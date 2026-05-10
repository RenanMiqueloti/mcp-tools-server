"""Smoke tests for mcp-tools-server.

Validates repo layout, README branding and that the module imports without
the MCP SDK installed (the server gracefully degrades to a no-op when
``mcp`` is missing). Dispatcher tests using ``call_tool`` are guarded with
``importorskip`` so they only run when the MCP SDK is available.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def test_repo_layout() -> None:
    assert (ROOT / "server.py").is_file()
    assert (ROOT / "requirements.txt").is_file()
    assert (ROOT / ".env.example").is_file()
    assert (ROOT / "LICENSE").is_file()
    assert (ROOT / "pyproject.toml").is_file()
    assert (ROOT / "README.md").is_file()


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


def test_server_module_with_mcp() -> None:
    pytest.importorskip("mcp")
    import server

    assert hasattr(server, "server")
    assert hasattr(server, "_MCP_OK")
    assert server._MCP_OK is True


def test_list_tools_exposes_six_tools() -> None:
    pytest.importorskip("mcp")
    import server

    tools = asyncio.run(server.list_tools())
    names = {t.name for t in tools}
    assert names == {
        "datetime_info",
        "calculate",
        "text_stats",
        "json_extract",
        "search_knowledge",
        "http_get",
    }


def test_call_tool_calculate() -> None:
    pytest.importorskip("mcp")
    import server

    result = asyncio.run(server.call_tool("calculate", {"expression": "sqrt(4) + 1"}))
    assert len(result) == 1
    assert result[0].text == "3.0"


def test_call_tool_calculate_rejects_builtins() -> None:
    pytest.importorskip("mcp")
    import server

    result = asyncio.run(server.call_tool("calculate", {"expression": "__import__('os')"}))
    assert result[0].text.startswith("Error:")


def test_call_tool_text_stats() -> None:
    pytest.importorskip("mcp")
    import server

    result = asyncio.run(server.call_tool("text_stats", {"text": "Hello world. This is a test."}))
    payload = json.loads(result[0].text)
    assert payload["words"] == 6
    assert payload["sentences"] >= 2
    assert payload["characters"] == len("Hello world. This is a test.")


def test_call_tool_json_extract() -> None:
    pytest.importorskip("mcp")
    import server

    result = asyncio.run(
        server.call_tool(
            "json_extract",
            {"json_string": '{"user": {"name": "Renan"}}', "path": "user.name"},
        )
    )
    assert result[0].text == "Renan"


def test_call_tool_http_get_blocks_unlisted_domain() -> None:
    pytest.importorskip("mcp")
    import server

    result = asyncio.run(
        server.call_tool("http_get", {"url": "https://example.com/", "timeout": 1})
    )
    assert "not in allowlist" in result[0].text.lower()


def test_call_tool_unknown_raises() -> None:
    pytest.importorskip("mcp")
    import server

    with pytest.raises(ValueError, match="Unknown tool"):
        asyncio.run(server.call_tool("does_not_exist", {}))
