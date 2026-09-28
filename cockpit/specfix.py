"""Auto-repair the one recurring SPEC.md YAML breakage: an unquoted scalar that
contains a 'word: word' colon (colon + space) or starts with a YAML-hostile char
like a backtick. Those come from prose typed into list items / mapping values
(by a human, or by the coding agent editing SPEC.md directly).

Strategy: let PyYAML point at the failing line (its error carries a problem_mark),
quote exactly that scalar, re-parse, repeat (bounded). We never reformat valid
content and never touch the body -- if we cannot make it parse, we change nothing
and let the caller surface the error. The parser/gate stay strict on purpose;
this is an authoring-time convenience, not a silent fix (the caller reports the
quoted lines).
"""
from __future__ import annotations

import re

import yaml

_MAX_PASSES = 25
# "  - some content"  (a sequence item)
_LIST = re.compile(r"^(\s*-\s+)(\S.*?)\s*$")
# "  key: some value"  (a mapping with an inline value; not a block-introducing key)
_MAP = re.compile(r"^(\s*[^:#\s][^:]*:\s+)(\S.*?)\s*$")


def _split_frontmatter(text: str) -> tuple[str, str] | None:
    """Return (frontmatter_text, body_text) or None if there is no '---' block."""
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            return "".join(lines[1:i]), "".join(lines[i + 1:])
    return None


def _quote_scalar_line(line: str) -> str | None:
    """Double-quote the scalar part of a list item or mapping value; None if the
    line is not a shape we can safely quote (e.g. a folded continuation)."""
    m = _LIST.match(line) or _MAP.match(line)
    if not m:
        return None
    prefix, content = m.group(1), m.group(2)
    if len(content) >= 2 and content[0] in "\"'" and content[-1] == content[0]:
        return None  # already quoted
    esc = content.replace("\\", "\\\\").replace('"', '\\"')
    quoted = f'{prefix}"{esc}"'
    return quoted if quoted != line else None


def repair_frontmatter(text: str) -> tuple[str, list[tuple[int, str]]]:
    """Return (possibly_repaired_text, notes). notes = [(line_no, quoted_content)].

    If the frontmatter already parses, or cannot be repaired by quoting, the text
    is returned unchanged (notes empty)."""
    split = _split_frontmatter(text)
    if split is None:
        return text, []
    fm, body = split
    fm_lines = fm.splitlines()
    notes: list[tuple[int, str]] = []

    for _ in range(_MAX_PASSES):
        try:
            yaml.safe_load("\n".join(fm_lines))
            break  # parses now
        except yaml.YAMLError as exc:
            mark = getattr(exc, "problem_mark", None)
            if mark is None or not (0 <= mark.line < len(fm_lines)):
                return text, []  # cannot locate -> change nothing
            fixed = _quote_scalar_line(fm_lines[mark.line])
            if fixed is None:
                return text, []  # cannot safely quote -> change nothing
            notes.append((mark.line + 1, fixed.strip()))
            fm_lines[mark.line] = fixed
    else:
        return text, []  # did not converge -> change nothing

    if not notes:
        return text, []
    return f"---\n{chr(10).join(fm_lines)}\n---\n{body}", notes
