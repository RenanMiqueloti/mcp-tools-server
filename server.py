"""mcp-tools-server — MCP server with general-purpose utility tools.

Tools are exposed over the MCP stdio transport for Claude Desktop, the
LangGraph MCP adapter, the OpenAI Agents SDK or any compatible client.

Tool list:
    datetime_info      — current UTC date/time, weekday, ISO week number
    calculate          — math expression evaluator (AST whitelist, no eval)
    text_stats         — word, sentence, character and token estimate
    json_extract       — value lookup via dot-path (``user.address.city``)
    search_knowledge   — vector search stub — wire to your Qdrant/pgvector
    http_get           — HTTP GET against an allowlisted set of hosts

Each handler is exported as a plain function so it can be unit-tested
without an MCP runtime. The MCP layer is driven by a single ``TOOLS``
registry, so ``list_tools`` and ``call_tool`` can never drift apart.

Usage:
    pip install mcp httpx
    python server.py
"""

from __future__ import annotations

import ast
import asyncio
import json
import math
import operator
import re
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any, NamedTuple
from urllib.parse import urlparse

try:
    from mcp import types
    from mcp.server import Server
    from mcp.server.stdio import stdio_server

    _MCP_OK = True
except ImportError:
    _MCP_OK = False

__version__ = "0.2.0"

# ── Config ────────────────────────────────────────────────────────────────

# Exact-host allowlist for http_get. A host must match one of these entries
# in full — no prefix/suffix matching — so look-alikes like
# ``api.github.com.evil.com`` and userinfo tricks like
# ``api.github.com@evil.com`` are rejected.
ALLOWED_HOSTS = frozenset(
    {
        "api.github.com",
        "api.openai.com",
        "httpbin.org",
        "wttr.in",
    }
)

# ── calculate: AST-based evaluator (no eval) ──────────────────────────────

# ``eval`` with an empty ``__builtins__`` is NOT a sandbox: attribute access
# on literals (``().__class__.__bases__...``) reaches arbitrary objects. We
# parse the expression and walk a strict whitelist of node types instead.

_BIN_OPS: dict[type[ast.operator], Callable[[Any, Any], Any]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY_OPS: dict[type[ast.unaryop], Callable[[Any], Any]] = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}

_MATH_NS = {k: v for k, v in math.__dict__.items() if not k.startswith("_")}
_CALC_FUNCS: dict[str, Callable[..., Any]] = {
    "abs": abs,
    "round": round,
    "min": min,
    "max": max,
    **{k: v for k, v in _MATH_NS.items() if callable(v)},
}
_CALC_CONSTS = {k: v for k, v in _MATH_NS.items() if not callable(v)}

# Cap exponents so ``9**9**9`` can't lock the process on a giant int.
_MAX_EXPONENT = 1000


def _eval_node(node: ast.AST) -> Any:
    if isinstance(node, ast.Expression):
        return _eval_node(node.body)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            raise ValueError(f"disallowed constant: {node.value!r}")
        return node.value
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPS:
        return _UNARY_OPS[type(node.op)](_eval_node(node.operand))
    if isinstance(node, ast.BinOp) and type(node.op) in _BIN_OPS:
        left = _eval_node(node.left)
        right = _eval_node(node.right)
        if (
            isinstance(node.op, ast.Pow)
            and isinstance(right, (int, float))
            and right > _MAX_EXPONENT
        ):
            raise ValueError("exponent too large")
        return _BIN_OPS[type(node.op)](left, right)
    if isinstance(node, ast.Name):
        if node.id in _CALC_CONSTS:
            return _CALC_CONSTS[node.id]
        raise ValueError(f"unknown name: {node.id}")
    if isinstance(node, ast.Call):
        if node.keywords or not isinstance(node.func, ast.Name) or node.func.id not in _CALC_FUNCS:
            raise ValueError("disallowed call")
        return _CALC_FUNCS[node.func.id](*[_eval_node(a) for a in node.args])
    raise ValueError(f"disallowed expression: {type(node).__name__}")


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
    """Evaluate a math expression via an AST whitelist (math funcs + consts)."""
    expr = (expression or "").strip()
    if not expr:
        return "Error: empty expression"
    try:
        return str(_eval_node(ast.parse(expr, mode="eval")))
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
    """Extract a JSON value via dot-path (``a.b.0.c``). Returns ``Error: ...`` on failure.

    Supports list indices (numeric segments). Non-string results are
    re-serialised as JSON; strings are returned verbatim.
    """
    try:
        data = json.loads(json_string or "{}")
        keys = [k for k in (path or "").split(".") if k]
        val: Any = data
        for k in keys:
            val = val[int(k)] if isinstance(val, list) else val[k]
        return val if isinstance(val, str) else json.dumps(val, ensure_ascii=False)
    except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
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


def _host_allowed(url: str) -> bool:
    """True only if ``url`` is http(s) and its host is exactly in ALLOWED_HOSTS."""
    try:
        parsed = urlparse(url or "")
    except ValueError:
        return False
    return parsed.scheme in {"http", "https"} and parsed.hostname in ALLOWED_HOSTS


async def http_get(url: str, timeout: float = 10.0) -> str:
    """HTTP GET against an allowlisted host. Body truncated at 4000 chars."""
    if not _host_allowed(url):
        return f"Error: URL not in allowlist — {url}"
    try:
        import httpx

        async with httpx.AsyncClient(timeout=float(timeout)) as client:
            resp = await client.get(url)
            return resp.text[:4000]
    except ImportError:
        return "Error: httpx not installed. Run: pip install httpx"
    except Exception as exc:
        return f"Error: {exc}"


# ── Tool registry (single source for list_tools + call_tool) ──────────────


class ToolSpec(NamedTuple):
    name: str
    description: str
    input_schema: dict[str, Any]
    handler: Callable[[dict[str, Any]], Awaitable[str]]


async def _run_datetime(_: dict[str, Any]) -> str:
    return json.dumps(datetime_info())


async def _run_calculate(args: dict[str, Any]) -> str:
    return calculate(args.get("expression", ""))


async def _run_text_stats(args: dict[str, Any]) -> str:
    return json.dumps(text_stats(args.get("text", "")))


async def _run_json_extract(args: dict[str, Any]) -> str:
    return json_extract(args.get("json_string", "{}"), args.get("path", ""))


async def _run_search_knowledge(args: dict[str, Any]) -> str:
    return json.dumps(
        search_knowledge(args.get("query", ""), int(args.get("top_k", 3))),
        indent=2,
    )


async def _run_http_get(args: dict[str, Any]) -> str:
    return await http_get(args.get("url", ""), float(args.get("timeout", 10)))


TOOLS: list[ToolSpec] = [
    ToolSpec(
        name="datetime_info",
        description="Returns current UTC datetime, Unix timestamp, weekday name, and ISO week number.",
        input_schema={"type": "object", "properties": {}, "required": []},
        handler=_run_datetime,
    ),
    ToolSpec(
        name="calculate",
        description=(
            "Safely evaluates a mathematical expression. "
            "Supports all Python math functions: sqrt, log, sin, cos, pi, e, etc. "
            "Examples: 'sqrt(2) * pi', 'log10(1000)', '2**10'"
        ),
        input_schema={
            "type": "object",
            "properties": {"expression": {"type": "string", "description": "Math expression."}},
            "required": ["expression"],
        },
        handler=_run_calculate,
    ),
    ToolSpec(
        name="text_stats",
        description="Returns word count, sentence count, character count, and estimated token count for a text.",
        input_schema={
            "type": "object",
            "properties": {"text": {"type": "string", "description": "Input text to analyze."}},
            "required": ["text"],
        },
        handler=_run_text_stats,
    ),
    ToolSpec(
        name="json_extract",
        description=(
            "Extracts a value from a JSON string using a dot-path. List indices are supported. "
            "Example: json='{\"user\":{\"name\":\"Renan\"}}', path='user.name' → 'Renan'"
        ),
        input_schema={
            "type": "object",
            "properties": {
                "json_string": {"type": "string", "description": "Raw JSON string."},
                "path": {"type": "string", "description": "Dot-separated key/index path."},
            },
            "required": ["json_string", "path"],
        },
        handler=_run_json_extract,
    ),
    ToolSpec(
        name="search_knowledge",
        description=(
            "Searches a knowledge base for relevant documents. "
            "Replace the stub implementation with your Qdrant/pgvector query."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "top_k": {"type": "integer", "default": 3},
            },
            "required": ["query"],
        },
        handler=_run_search_knowledge,
    ),
    ToolSpec(
        name="http_get",
        description=(
            "Performs an HTTP GET request to an allowlisted host. "
            f"Allowed hosts: {', '.join(sorted(ALLOWED_HOSTS))}"
        ),
        input_schema={
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
        handler=_run_http_get,
    ),
]

_TOOLS_BY_NAME: dict[str, ToolSpec] = {t.name: t for t in TOOLS}


# ── MCP Server (stdio transport) ─────────────────────────────────────────

if _MCP_OK:
    server = Server("mcp-tools-server", version=__version__)

    @server.list_tools()
    async def list_tools() -> list[types.Tool]:
        return [
            types.Tool(name=t.name, description=t.description, inputSchema=t.input_schema)
            for t in TOOLS
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
        spec = _TOOLS_BY_NAME.get(name)
        if spec is None:
            raise ValueError(f"Unknown tool: {name!r}")
        return [types.TextContent(type="text", text=await spec.handler(arguments or {}))]

    async def _main() -> None:
        try:
            from dotenv import load_dotenv

            load_dotenv()
        except ImportError:
            pass
        async with stdio_server() as (read_stream, write_stream):
            await server.run(read_stream, write_stream, server.create_initialization_options())

    if __name__ == "__main__":
        asyncio.run(_main())

else:
    if __name__ == "__main__":
        print("MCP SDK not installed. Run: pip install mcp")
