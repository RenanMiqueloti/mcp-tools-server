"""Direct tests for the six tool handlers.

The handlers are pure functions extracted from the MCP-decorated dispatcher,
so they run without an MCP runtime.
"""

from __future__ import annotations

import asyncio
import json

import pytest

import server

# ── datetime_info ─────────────────────────────────────────────────────────


def test_datetime_info_shape() -> None:
    out = server.datetime_info()
    for key in ("iso", "unix", "weekday", "week_number", "date", "time"):
        assert key in out
    assert isinstance(out["unix"], int)
    assert 1 <= out["week_number"] <= 53


# ── calculate ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "expr, expected",
    [
        ("2 + 2", "4"),
        ("2**10", "1024"),
        ("sqrt(16)", "4.0"),
        ("min(1, 2, 3)", "1"),
        ("abs(-7)", "7"),
    ],
)
def test_calculate_valid(expr: str, expected: str) -> None:
    assert server.calculate(expr) == expected


def test_calculate_uses_math_constants() -> None:
    out = server.calculate("pi")
    assert out.startswith("3.14")


def test_calculate_blocks_builtins() -> None:
    # __import__, open, etc. must not be reachable through eval's builtins.
    out = server.calculate("__import__('os')")
    assert out.startswith("Error:")


def test_calculate_handles_syntax_error() -> None:
    out = server.calculate("2 +")
    assert out.startswith("Error:")


# ── text_stats ────────────────────────────────────────────────────────────


def test_text_stats_basic() -> None:
    out = server.text_stats("Hello world. How are you?")
    assert out["words"] == 5
    assert out["sentences"] == 2
    assert out["characters"] == len("Hello world. How are you?")
    assert out["tokens_estimated"] > 0


def test_text_stats_empty() -> None:
    out = server.text_stats("")
    assert out == {"words": 0, "sentences": 0, "characters": 0, "tokens_estimated": 0}


# ── json_extract ──────────────────────────────────────────────────────────


def test_json_extract_simple_path() -> None:
    out = server.json_extract('{"user": {"name": "Renan"}}', "user.name")
    assert out == "Renan"


def test_json_extract_root_value() -> None:
    out = server.json_extract('{"answer": 42}', "answer")
    assert out == "42"


def test_json_extract_missing_key() -> None:
    out = server.json_extract('{"a": 1}', "a.b.c")
    assert out.startswith("Error:")


def test_json_extract_invalid_json() -> None:
    out = server.json_extract("not json", "x")
    assert out.startswith("Error:")


# ── search_knowledge (stub) ───────────────────────────────────────────────


def test_search_knowledge_returns_top_k() -> None:
    out = server.search_knowledge("anything", top_k=3)
    assert len(out) == 3
    assert out[0]["rank"] == 1
    assert out[0]["score"] >= out[-1]["score"]


def test_search_knowledge_zero_top_k() -> None:
    assert server.search_knowledge("x", top_k=0) == []


def test_search_knowledge_negative_top_k_returns_empty() -> None:
    assert server.search_knowledge("x", top_k=-5) == []


# ── http_get (allowlist) ──────────────────────────────────────────────────


def test_http_get_blocks_disallowed_domain() -> None:
    out = asyncio.run(server.http_get("https://example.com/something", timeout=1))
    assert "not in allowlist" in out


def test_http_get_blocks_empty_url() -> None:
    out = asyncio.run(server.http_get("", timeout=1))
    assert "not in allowlist" in out


# ── allowlist regex ───────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "url, allowed",
    [
        ("https://api.github.com/users/RenanMiqueloti", True),
        ("https://httpbin.org/get", True),
        ("https://wttr.in/Joinville", True),
        ("http://api.openai.com/v1/models", True),
        ("https://example.com", False),
        ("ftp://api.github.com", False),
        ("", False),
    ],
)
def test_allowlist_pattern(url: str, allowed: bool) -> None:
    assert bool(server.HTTP_ALLOWLIST.match(url)) is allowed


# ── JSON serialisation roundtrip on the dispatcher payloads ──────────────


def test_datetime_info_json_serialisable() -> None:
    json.dumps(server.datetime_info())


def test_text_stats_json_serialisable() -> None:
    json.dumps(server.text_stats("test"))


def test_search_knowledge_json_serialisable() -> None:
    json.dumps(server.search_knowledge("test", top_k=2))
