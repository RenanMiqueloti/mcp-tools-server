"""mcp-tools-server — Servidor MCP de propósito geral para agentes de IA.

Expõe ferramentas utilitárias prontas para consumo por qualquer cliente MCP:
Claude Desktop, LangGraph MCP adapter, OpenAI Agents SDK, etc.

Ferramentas:
    datetime_info      — data, hora, timezone, dia da semana
    calculate          — expressões matemáticas seguras (math completo)
    text_stats         — contagem de palavras, sentenças, tokens estimados
    json_extract       — extrai valores de JSON via dot-path
    search_knowledge   — stub para busca vetorial (conecte ao seu Qdrant aqui)
    http_get           — GET HTTP simples (URLs permitidas via allowlist)

Transporte: stdio (padrão MCP)

Uso:
    pip install mcp httpx
    python server.py

Configuração (Claude Desktop):
    {
      "mcpServers": {
        "mcp-tools": {
          "command": "python",
          "args": ["/path/to/server.py"]
        }
      }
    }

Configuração (LangGraph MCP adapter):
    from langchain_mcp_adapters.client import MultiServerMCPClient
    client = MultiServerMCPClient({
        "mcp-tools": {"command": "python", "args": ["server.py"], "transport": "stdio"}
    })
"""

from __future__ import annotations

import asyncio
import json
import math
import re
from datetime import UTC, datetime

try:
    from mcp import types
    from mcp.server import Server
    from mcp.server.stdio import stdio_server

    _MCP_OK = True
except ImportError:
    _MCP_OK = False

# ── Config ────────────────────────────────────────────────────────────────

# Domínios permitidos para http_get (segurança — edite conforme necessário)
HTTP_ALLOWLIST = re.compile(r"^https?://(api\.github\.com|api\.openai\.com|httpbin\.org|wttr\.in)")

# ── Server ────────────────────────────────────────────────────────────────

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

        # ── datetime_info ─────────────────────────────────────────────────
        if name == "datetime_info":
            now = datetime.now(tz=UTC)
            return text(
                json.dumps(
                    {
                        "iso": now.isoformat(),
                        "unix": int(now.timestamp()),
                        "weekday": now.strftime("%A"),
                        "week_number": now.isocalendar()[1],
                        "date": now.strftime("%Y-%m-%d"),
                        "time": now.strftime("%H:%M:%S"),
                    }
                )
            )

        # ── calculate ─────────────────────────────────────────────────────
        if name == "calculate":
            expr = arguments.get("expression", "").strip()
            ns = {k: v for k, v in math.__dict__.items() if not k.startswith("_")}
            ns.update({"abs": abs, "round": round, "min": min, "max": max, "sum": sum})
            try:
                result = eval(expr, {"__builtins__": {}}, ns)
                return text(str(result))
            except Exception as exc:
                return text(f"Error: {exc}")

        # ── text_stats ────────────────────────────────────────────────────
        if name == "text_stats":
            t = arguments.get("text", "")
            words = len(t.split())
            sentences = len(re.split(r"[.!?]+", t.strip()))
            chars = len(t)
            tokens_est = int(words / 0.75)
            return text(
                json.dumps(
                    {
                        "words": words,
                        "sentences": sentences,
                        "characters": chars,
                        "tokens_estimated": tokens_est,
                    }
                )
            )

        # ── json_extract ──────────────────────────────────────────────────
        if name == "json_extract":
            try:
                data = json.loads(arguments.get("json_string", "{}"))
                keys = arguments.get("path", "").split(".")
                val = data
                for k in keys:
                    val = val[k]
                return text(str(val))
            except (KeyError, TypeError, json.JSONDecodeError) as exc:
                return text(f"Error: {exc}")

        # ── search_knowledge ──────────────────────────────────────────────
        if name == "search_knowledge":
            query = arguments.get("query", "")
            top_k = int(arguments.get("top_k", 3))
            # TODO: Replace with actual Qdrant integration:
            # from qdrant_client import QdrantClient
            # client = QdrantClient(url=os.getenv("QDRANT_URL"))
            # hits = client.search("knowledge", query_vector=embed(query), limit=top_k)
            stub = [
                {
                    "rank": i + 1,
                    "text": f"Stub result {i + 1} for '{query}'",
                    "score": round(0.9 - i * 0.1, 2),
                }
                for i in range(top_k)
            ]
            return text(json.dumps(stub, indent=2))

        # ── http_get ──────────────────────────────────────────────────────
        if name == "http_get":
            url = arguments.get("url", "")
            if not HTTP_ALLOWLIST.match(url):
                return text(f"Error: URL not in allowlist — {url}")
            timeout = float(arguments.get("timeout", 10))
            try:
                import httpx  # type: ignore[import]

                async with httpx.AsyncClient(timeout=timeout) as client:
                    resp = await client.get(url)
                    return text(resp.text[:4000])
            except ImportError:
                return text("Error: httpx not installed. Run: pip install httpx")
            except Exception as exc:
                return text(f"Error: {exc}")

        raise ValueError(f"Unknown tool: {name!r}")

    async def _main() -> None:
        async with stdio_server() as (read_stream, write_stream):
            await server.run(read_stream, write_stream, server.create_initialization_options())

    if __name__ == "__main__":
        asyncio.run(_main())

else:
    if __name__ == "__main__":
        print("⚠️  MCP SDK não encontrado. Instale com: pip install mcp")
