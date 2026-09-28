"""AI agents that author/realize intent (kept separate from the engine).

planner -> role P: natural language + examples -> SPEC.md draft (reviewed by a human)
coder   -> role C: implements a node within the assembled context bundle
"""

__all__ = ["planner", "coder"]
