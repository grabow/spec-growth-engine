"""Auto-repair of the recurring SPEC.md YAML breakage (unquoted colon/backtick)."""
import frontmatter

import specfix


def _parses(text: str) -> dict:
    return dict(frontmatter.loads(text).metadata)


def test_repairs_hard_error_colon_in_list_item():
    # two colons in a list item -> "mapping values are not allowed" (a hard parse
    # error, the breakage we actually hit -- not the silently-valid single-colon case)
    broken = (
        "---\nid: x\nkind: component\n"
        "contract:\n  provides:\n  - Output written to: a: b\n"
        "---\n\nbody\n"
    )
    fixed, notes = specfix.repair_frontmatter(broken)
    assert notes, "expected a repair"
    meta = _parses(fixed)  # now parses
    assert meta["contract"]["provides"] == ["Output written to: a: b"]


def test_repairs_backtick_and_colon_real_case():
    # the exact shape that kept breaking: 'word: word' + backticks in a list item
    broken = (
        "---\nid: x\nkind: component\n"
        "contract:\n  provides:\n  - Runnable Java main entry point: `app.M`.\n"
        "---\n\nb\n"
    )
    fixed, notes = specfix.repair_frontmatter(broken)
    assert len(notes) == 1
    assert _parses(fixed)["contract"]["provides"] == ["Runnable Java main entry point: `app.M`."]


def test_repairs_colon_in_mapping_value():
    broken = "---\nid: x\ndesign:\n  approach: do this: then that\n---\n\nb\n"
    fixed, notes = specfix.repair_frontmatter(broken)
    assert notes
    assert _parses(fixed)["design"]["approach"] == "do this: then that"


def test_valid_yaml_is_untouched():
    ok = "---\nid: x\nkind: component\ncontract:\n  provides:\n  - foo()\n---\n\nbody\n"
    fixed, notes = specfix.repair_frontmatter(ok)
    assert notes == []
    assert fixed == ok


def test_already_quoted_scalar_is_untouched():
    ok = '---\nid: x\ndesign:\n  approach: "do this: then that"\n---\n\nb\n'
    fixed, notes = specfix.repair_frontmatter(ok)
    assert notes == []
    assert fixed == ok


def test_body_is_preserved():
    broken = "---\nid: x\nk: a: b\n---\n\n# Title\nprose: with colon\nmore\n"
    fixed, _ = specfix.repair_frontmatter(broken)
    assert "# Title\nprose: with colon\nmore" in fixed  # body kept verbatim


def test_no_frontmatter_returns_unchanged():
    text = "just some text: with a colon\n"
    fixed, notes = specfix.repair_frontmatter(text)
    assert (fixed, notes) == (text, [])


def test_heal_on_load_brings_a_dropped_node_back(tmp_path):
    # a SPEC.md whose YAML breaks (colon in a list item) -> the parser drops the
    # node; repairing the file in place (what the cockpit does on load) restores it.
    from engine import parser
    (tmp_path / "n").mkdir()
    (tmp_path / "n" / "SPEC.md").write_text(
        "---\nid: n\nparent: app\nkind: component\n"
        "contract:\n  provides:\n  - writes to dir: out: file\n"  # two colons -> hard YAML error
        "---\n\nbody\n", encoding="utf-8")
    assert "n" not in parser.load_nodes(tmp_path)          # dropped: invalid YAML
    assert parser.invalid_specs(tmp_path)                  # and reported as invalid

    # heal (same call the cockpit makes on load) and write back
    path = tmp_path / "n" / "SPEC.md"
    fixed, fixes = specfix.repair_frontmatter(path.read_text())
    assert fixes
    path.write_text(fixed, encoding="utf-8")

    assert "n" in parser.load_nodes(tmp_path)              # node is back
    assert parser.invalid_specs(tmp_path) == []            # nothing invalid anymore
