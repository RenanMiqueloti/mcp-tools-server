# mcp-tools-server

![CI](https://github.com/RenanMiqueloti/mcp-tools-server/actions/workflows/ci.yml/badge.svg)
![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)
![Python](https://img.shields.io/badge/python-3.11%E2%80%933.14-blue.svg)

Servidor **MCP** (Model Context Protocol) com seis ferramentas utilitárias para qualquer cliente compatível — Claude Desktop, LangGraph MCP adapter, OpenAI Agents SDK.

Implementação *server-side* do MCP (em vez de consumir um servidor existente), com handlers extraídos como funções puras pra serem testáveis sem o runtime MCP.

---

## Ferramentas expostas

| Ferramenta | O que faz |
|---|---|
| `datetime_info` | Data, hora (UTC ou timezone IANA), timestamp Unix, dia da semana, semana ISO |
| `calculate` | Avalia expressões matemáticas com segurança (math completo) |
| `text_stats` | Palavras, sentenças, caracteres e tokens estimados de um texto |
| `json_extract` | Extrai valores de JSON via dot-path (`user.address.city`) |
| `search_knowledge` | Busca no knowledge base — stub pronto para conectar ao Qdrant |
| `http_get` | GET HTTP com allowlist de domínios |

---

## Quick start

```bash
git clone https://github.com/RenanMiqueloti/mcp-tools-server.git
cd mcp-tools-server
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python server.py                                # stdio (Claude Desktop etc.)
python server.py --transport streamable-http    # HTTP em http://127.0.0.1:8000/mcp
```

O transporte **Streamable HTTP** expõe o servidor para clients remotos (o stdio
só funciona com processos locais). `--host` e `--port` ajustam o bind; o modo é
stateless, então dá pra escalar horizontal sem event store.

---

## Conectar ao Claude Desktop

Adicione em `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS) ou `%APPDATA%\Claude\claude_desktop_config.json` (Windows):

```json
{
  "mcpServers": {
    "mcp-tools": {
      "command": "python",
      "args": ["/caminho/absoluto/para/server.py"]
    }
  }
}
```

Reinicie o Claude Desktop. As ferramentas ficam disponíveis automaticamente.

---

## Conectar a um agente LangGraph

```python
from langchain_mcp_adapters.client import MultiServerMCPClient
from langgraph.prebuilt import create_react_agent
from langchain_anthropic import ChatAnthropic

client = MultiServerMCPClient({
    "mcp-tools": {
        "command": "python",
        "args": ["server.py"],
        "transport": "stdio",
    }
})

tools = await client.get_tools()
agent = create_react_agent(ChatAnthropic(model="claude-opus-4-7"), tools)
result = await agent.ainvoke({"messages": [("human", "What day of the week is it?")]})
```

---

## Adicionar o search_knowledge real (Qdrant)

Em `server.py`, substitua o stub no handler `search_knowledge`:

```python
from qdrant_client import QdrantClient
from langchain_openai import OpenAIEmbeddings

client_q = QdrantClient(url=os.getenv("QDRANT_URL"))
embeddings = OpenAIEmbeddings()

query_vec = embeddings.embed_query(query)
hits = client_q.search("knowledge", query_vector=query_vec, limit=top_k)
results = [{"rank": i+1, "text": h.payload["text"], "score": h.score} for i, h in enumerate(hits)]
```

---

## Estrutura

```
mcp-tools-server/
├── server.py                   # Servidor MCP (stdio transport) + handlers
├── tests/                      # pytest — handlers + allowlist
├── pyproject.toml              # ruff, pytest, mypy config
├── Dockerfile, .dockerignore   # imagem 3.12-slim, USER non-root
├── .pre-commit-config.yaml     # ruff + ruff-format + checks gerais
├── .github/
│   ├── workflows/ci.yml        # lint (ruff) + mypy + tests (py3.11–3.14)
│   └── dependabot.yml          # pip + github-actions + docker
├── requirements.txt
├── .env.example
└── LICENSE
```

---

## Desenvolvimento

```bash
pip install -r requirements.txt
pip install pytest ruff mypy pre-commit
pre-commit install               # ativa o hook git pre-commit
pytest -v tests/                 # roda os testes dos handlers
ruff check . && ruff format --check .
mypy .                           # type-check
```
