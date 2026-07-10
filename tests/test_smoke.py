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


# ── Streamable HTTP transport ─────────────────────────────────────────────


def test_streamable_http_end_to_end() -> None:
    """Sobe a app HTTP num uvicorn real (porta efêmera) e faz um call_tool
    completo com o client Streamable HTTP oficial do SDK."""
    pytest.importorskip("mcp")
    uvicorn = pytest.importorskip("uvicorn")

    import threading
    import time

    import server as srv

    config = uvicorn.Config(srv._build_http_app(), host="127.0.0.1", port=0, log_level="error")
    us = uvicorn.Server(config)
    thread = threading.Thread(target=us.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 15
    while not us.started:
        assert time.monotonic() < deadline, "uvicorn não subiu em 15s"
        time.sleep(0.05)
    port = us.servers[0].sockets[0].getsockname()[1]

    async def roundtrip() -> tuple[set[str], str]:
        from mcp import ClientSession

        try:  # mcp >= 1.28 renomeou o client; o alias antigo emite DeprecationWarning
            from mcp.client.streamable_http import streamable_http_client
        except ImportError:
            from mcp.client.streamable_http import (
                streamablehttp_client as streamable_http_client,
            )

        async with (
            streamable_http_client(f"http://127.0.0.1:{port}/mcp") as (read, write, _),
            ClientSession(read, write) as session,
        ):
            await session.initialize()
            tools = await session.list_tools()
            result = await session.call_tool("calculate", {"expression": "2 + 2"})
            return {t.name for t in tools.tools}, result.content[0].text

    try:
        names, answer = asyncio.run(roundtrip())
        assert "calculate" in names and len(names) == 6
        assert answer == "4"
    finally:
        us.should_exit = True
        thread.join(timeout=10)
