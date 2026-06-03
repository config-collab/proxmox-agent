"""
Tool registry — all agent tools are registered here.
Each tool is a plain Python function decorated with @tool.
The registry auto-builds the Anthropic-format schema list for LLM calls,
and dispatches tool_calls from the LLM back to the right function.
"""
from typing import Callable

_registry: dict[str, dict] = {}  # name -> {fn, schema}


def tool(name: str, description: str, input_schema: dict):
    """Decorator to register a function as an LLM-callable tool."""
    def decorator(fn: Callable):
        _registry[name] = {
            "fn":     fn,
            "schema": {
                "name":         name,
                "description":  description,
                "input_schema": input_schema,
            },
        }
        return fn
    return decorator


def all_schemas() -> list[dict]:
    """Return all tool schemas in Anthropic format — pass directly to llm.chat()."""
    return [v["schema"] for v in _registry.values()]


def dispatch(name: str, inputs: dict) -> str:
    """Call a registered tool by name. Returns a string result for the LLM."""
    if name not in _registry:
        return f"Unknown tool: {name}"
    fn = _registry[name]["fn"]
    try:
        result = fn(**inputs)
        return str(result) if result is not None else "done"
    except Exception as exc:
        return f"error: {exc}"


# Side-effect imports — each module's @tool decorators self-register into _registry
import importlib
for _mod in ["tools.inventory_tool", "tools.patch_tool", "tools.backup_tool",
             "tools.security_tool", "tools.docs_tool", "tools.vm_tool",
             "tools.admin_tool", "tools.guard_tool", "tools.audit_tool"]:
    importlib.import_module(_mod)
