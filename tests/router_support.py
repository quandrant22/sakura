"""Test helper: real registry selection followed by production VPS arg parsing."""
from sakura_core.bridge import _load_capabilities
from sakura_core.router import Router
from capabilities.vps_arguments import arguments


def route_info(text, context=None):
    _load_capabilities()
    decision = Router().route(text, context)
    if not decision.action:
        return None
    action, arg = arguments(decision.action, text, decision.param or "")
    return {"action": action, "arg": arg}
