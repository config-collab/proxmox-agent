"""
LLM provider abstraction — Claude, OpenAI, or Ollama (local).
Set LLM_PROVIDER in .env to switch backends. All providers expose the same
chat() interface and handle tool_use / function_calling internally.
"""
import json
import os
import config   # triggers .env load

_PROVIDER = os.environ.get("LLM_PROVIDER", "claude").lower()
_MODEL    = os.environ.get("LLM_MODEL", "")


# ── Provider implementations ───────────────────────────────────────────────────

def _strip(messages: list[dict]) -> list[dict]:
    """Remove internal _-prefixed keys before sending to any LLM API."""
    return [{k: v for k, v in m.items() if not k.startswith("_")} for m in messages]


def _chat_claude(
    messages: list[dict],
    tools: list[dict],
    thinking_budget: int = 0,
) -> tuple[str | None, list[dict]]:
    """
    Returns (text_response, tool_calls).
    tool_calls: [{"name": str, "id": str, "input": dict}]
    When thinking_budget > 0, uses extended thinking (claude-sonnet-4-6+ only).
    """
    import anthropic

    # Extended thinking requires a model that supports it; upgrade from haiku if needed
    if thinking_budget > 0:
        model = _MODEL or "claude-sonnet-4-6"
    else:
        model = _MODEL or "claude-haiku-4-5-20251001"

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    kwargs: dict = {
        "model":      model,
        "max_tokens": max(4096, thinking_budget + 2048) if thinking_budget else 4096,
        "messages":   _strip(messages),
    }
    if tools:
        kwargs["tools"] = tools
    if thinking_budget > 0:
        kwargs["thinking"] = {"type": "enabled", "budget_tokens": thinking_budget}

    resp = client.messages.create(**kwargs)

    # Extended thinking returns thinking + text blocks; extract only text
    text_blocks = [b.text for b in resp.content if b.type == "text"]
    text = "\n".join(text_blocks) if text_blocks else None

    tool_calls = [
        {"name": b.name, "id": b.id, "input": b.input}
        for b in resp.content
        if b.type == "tool_use"
    ]
    return text, tool_calls


def _chat_openai(messages: list[dict], tools: list[dict]) -> tuple[str | None, list[dict]]:
    """OpenAI / Ollama (OpenAI-compatible) backend."""
    from openai import OpenAI

    base_url = os.environ.get("OPENAI_BASE_URL", None)  # set for Ollama
    api_key  = os.environ.get("OPENAI_API_KEY", "ollama")
    model    = _MODEL or ("gpt-4o-mini" if _PROVIDER == "openai" else "llama3")

    client = OpenAI(api_key=api_key, base_url=base_url)

    kwargs: dict = {"model": model, "messages": _strip(messages)}
    if tools:
        # Convert from Anthropic schema to OpenAI schema if needed
        kwargs["tools"] = [_to_openai_tool(t) for t in tools]
        kwargs["tool_choice"] = "auto"

    resp = client.chat.completions.create(**kwargs)
    msg  = resp.choices[0].message

    text = msg.content  # may be None if tool_calls present

    tool_calls = []
    if msg.tool_calls:
        for tc in msg.tool_calls:
            tool_calls.append({
                "name":  tc.function.name,
                "id":    tc.id,
                "input": json.loads(tc.function.arguments),
            })
    return text, tool_calls


def _to_openai_tool(t: dict) -> dict:
    """Convert Anthropic-style tool schema to OpenAI function_calling schema."""
    return {
        "type": "function",
        "function": {
            "name":        t["name"],
            "description": t.get("description", ""),
            "parameters":  t.get("input_schema", {"type": "object", "properties": {}}),
        },
    }


# ── Public interface ────────────────────────────────────────────────────────────

def chat(
    messages: list[dict],
    tools: list[dict] | None = None,
    thinking_budget: int = 0,
) -> tuple[str | None, list[dict]]:
    """
    Send messages to the configured LLM.

    tools           — tool defs in Anthropic schema format
    thinking_budget — token budget for extended reasoning (Claude only, 0 = disabled)

    Returns: (text | None, tool_calls list)
    """
    tools = tools or []
    if _PROVIDER == "claude":
        return _chat_claude(messages, tools, thinking_budget=thinking_budget)
    elif _PROVIDER in ("openai", "ollama"):
        return _chat_openai(messages, tools)   # thinking not available on OpenAI/Ollama
    else:
        raise ValueError(f"Unknown LLM_PROVIDER={_PROVIDER!r} — use claude, openai, or ollama")


def tool_result_message(tool_id: str, result: str) -> dict:
    """
    Build the message that sends a tool result back to the LLM.
    Handles format differences between Anthropic and OpenAI.
    """
    if _PROVIDER == "claude":
        return {
            "role": "user",
            "content": [{"type": "tool_result", "tool_use_id": tool_id, "content": result}],
        }
    else:
        return {"role": "tool", "tool_call_id": tool_id, "content": result}


def assistant_tool_call_message(text: str | None, tool_calls: list[dict]) -> dict | None:
    """
    Build the assistant message that records tool calls (needed for multi-turn).
    Returns None if there are no tool calls.
    """
    if not tool_calls:
        return None
    if _PROVIDER == "claude":
        content = []
        if text:
            content.append({"type": "text", "text": text})
        for tc in tool_calls:
            content.append({"type": "tool_use", "id": tc["id"], "name": tc["name"], "input": tc["input"]})
        return {"role": "assistant", "content": content}
    else:
        return {
            "role": "assistant",
            "content": text,
            "tool_calls": [
                {
                    "id":       tc["id"],
                    "type":     "function",
                    "function": {"name": tc["name"], "arguments": json.dumps(tc["input"])},
                }
                for tc in tool_calls
            ],
        }
