# mcp-tools-server

Servidor **MCP** (Model Context Protocol) de propósito geral com ferramentas utilitárias prontas para consumo por qualquer agente compatível.

> Demonstra implementação *server-side* do MCP — a maioria dos projetos apenas consome servidores. Este projeto implementa um.

---

## Ferramentas expostas

| Ferramenta | O que faz |
|---|---|
| `datetime_info` | Data, hora UTC, timestamp Unix, dia da semana, semana ISO |
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
python server.py
```

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
agent = create_react_agent(ChatAnthropic(model="claude-opus-4-6"), tools)
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
├── server.py         # Servidor MCP completo (stdio transport)
├── requirements.txt
├── .env.example
└── LICENSE
```
