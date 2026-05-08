"""mcp-tools-server — MCP server with general-purpose utility tools.

Tools are exposed over the MCP stdio transport for Claude Desktop, the
LangGraph MCP adapter, the OpenAI Agents SDK or any compatible client.

Tool list:
    datetime_info      — current UTC date/time, weekday, ISO week number
    calculate          — math expression evaluator (sandboxed to ``math``)
    text_stats         — word, sentence, character and token estimate
    json_extract       — value lookup via dot-path (``user.address.city``)
    search_knowledge   — vector search stub — wire to your Qdrant/pgvector
    http_get           — HTTP GET against an allowlisted set of domains

Each handler is exported as a plain function so it can be unit-tested
without an MCP runtime.

Usage:
    pip install mcp httpx
    python server.py
"""

from __future__ import annotations

import asyncio
import json
import math
import re
from datetime import UTC, datetime
from typing import Any

try:
    from mcp import types
    from mcp.server import Server
    from mcp.server.stdio import stdio_server

    _MCP_OK = True
except ImportError:
    _MCP_OK = False

# ── Config ────────────────────────────────────────────────────────────────

# Allowlist for http_get. Edit to taste — anything outside this set is
# rejected before the request leaves the process.
HTTP_ALLOWLIST = re.compile(r"^https?://(api\.github\.com|api\.openai\.com|httpbin\.org|wttr\.in)")

# ── Tool handlers (pure, directly testable) ──────────────────────────────


def datetime_info() -> dict[str, Any]:
    """Return the current UTC date/time in several useful formats."""
    now = datetime.now(tz=UTC)
    return {
        "iso": now.isoformat(),
        "unix": int(now.timestamp()),
        "weekday": now.strftime("%A"),
        "week_number": now.isocalendar()[1],
        "date": now.strftime("%Y-%m-%d"),
        "time": now.strftime("%H:%M:%S"),
    }


def calculate(expression: str) -> str:
    """Evaluate a math expression in a namespace restricted to ``math``."""
    expr = (expression or "").strip()
    ns: dict[str, Any] = {k: v for k, v in math.__dict__.items() if not k.startswith("_")}
    ns.update({"abs": abs, "round": round, "min": min, "max": max, "sum": sum})
    try:
        return str(eval(expr, {"__builtins__": {}}, ns))
    except Exception as exc:
        return f"Error: {exc}"


def text_stats(text: str) -> dict[str, int]:
    """Return word, sentence and character counts plus a token estimate."""
    t = text or ""
    words = len(t.split())
    sentences = len([s for s in re.split(r"[.!?]+", t.strip()) if s])
    return {
        "words": words,
        "sentences": sentences,
        "characters": len(t),
        "tokens_estimated": int(words / 0.75) if words else 0,
    }


def json_extract(json_string: str, path: str) -> str:
    """Extract a JSON value via dot-path (``a.b.c``). Returns ``Error: ...`` on failure."""
    try:
        data = json.loads(json_string or "{}")
        keys = (path or "").split(".") if path else []
        val: Any = data
        for k in keys:
            val = val[k]
        return str(val)
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        return f"Error: {exc}"


def search_knowledge(query: str, top_k: int = 3) -> list[dict[str, Any]]:
    """Stub for vector search — replace the body with your real Qdrant/pgvector query."""
    n = max(0, int(top_k))
    return [
        {
            "rank": i + 1,
            "text": f"Stub result {i + 1} for {query!r}",
            "score": round(0.9 - i * 0.1, 2),
        }
        for i in range(n)
    ]


async def http_get(url: str, timeout: float = 10.0) -> str:
    """HTTP GET against an allowlisted domain. Body truncated at 4000 chars."""
    if not HTTP_ALLOWLIST.match(url or ""):
        return f"Error: URL not in allowlist — {url}"
    try:
        import httpx  # type: ignore[import]

        async with httpx.AsyncClient(timeout=float(timeout)) as client:
            resp = await client.get(url)
            return resp.text[:4000]
    except ImportError:
        return "Error: httpx not installed. Run: pip install httpx"
    except Exception as exc:
        return f"Error: {exc}"


# ── MCP Server (stdio transport) ─────────────────────────────────────────

if _MCP_OK:
    server = Server("mcp-tools-server", version="1.0.0")

    @server.list_tools()
    async def list_tools() -> list[types.Tool]:
        return [
            types.Tool(
                name="datetime_info",
                description="Returns current UTC datetime, Unix timestamp, weekday name, and ISO week number.",
                inputSchema={"type": "object", "properties": {}, "required": []},
            ),
            types.Tool(
                name="calculate",
                description=(
                    "Safely evaluates a mathematical expression. "
                    "Supports all Python math functions: sqrt, log, sin, cos, pi, e, etc. "
                    "Examples: 'sqrt(2) * pi', 'log10(1000)', '2**10'"
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "expression": {"type": "string", "description": "Math expression."}
                    },
                    "required": ["expression"],
                },
            ),
            types.Tool(
                name="text_stats",
                description="Returns word count, sentence count, character count, and estimated token count for a text.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "text": {"type": "string", "description": "Input text to analyze."}
                    },
                    "required": ["text"],
                },
            ),
            types.Tool(
                name="json_extract",
                description=(
                    "Extracts a value from a JSON string using a dot-path. "
                    "Example: json='{\"user\":{\"name\":\"Renan\"}}', path='user.name' → 'Renan'"
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "json_string": {"type": "string", "description": "Raw JSON string."},
                        "path": {"type": "string", "description": "Dot-separated key path."},
                    },
                    "required": ["json_string", "path"],
                },
            ),
            types.Tool(
                name="search_knowledge",
                description=(
                    "Searches a knowledge base for relevant documents. "
                    "Replace the stub implementation with your Qdrant/pgvector query."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "top_k": {"type": "integer", "default": 3},
                    },
                    "required": ["query"],
                },
            ),
            types.Tool(
                name="http_get",
                description=(
                    "Performs an HTTP GET request to an allowlisted URL. "
                    f"Allowed domains: {HTTP_ALLOWLIST.pattern}"
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "url": {"type": "string", "description": "URL to fetch."},
                        "timeout": {
                            "type": "number",
                            "description": "Timeout in seconds (default 10).",
                            "default": 10,
                        },
                    },
                    "required": ["url"],
                },
            ),
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:

        def text(s: str) -> list[types.TextContent]:
            return [types.TextContent(type="text", text=s)]

        if name == "datetime_info":
            return text(json.dumps(datetime_info()))

        if name == "calculate":
            return text(calculate(arguments.get("expression", "")))

        if name == "text_stats":
            return text(json.dumps(text_stats(arguments.get("text", ""))))

        if name == "json_extract":
            return text(
                json_extract(
                    arguments.get("json_string", "{}"),
                    arguments.get("path", ""),
                )
            )

        if name == "search_knowledge":
            results = search_knowledge(
                arguments.get("query", ""),
                int(arguments.get("top_k", 3)),
            )
            return text(json.dumps(results, indent=2))

        if name == "http_get":
            return text(
                await http_get(
                    arguments.get("url", ""),
                    float(arguments.get("timeout", 10)),
                )
            )

        raise ValueError(f"Unknown tool: {name!r}")

    async def _main() -> None:
        async with stdio_server() as (read_stream, write_stream):
            await server.run(read_stream, write_stream, server.create_initialization_options())

    if __name__ == "__main__":
        asyncio.run(_main())

else:
    if __name__ == "__main__":
        print("MCP SDK not installed. Run: pip install mcp")
