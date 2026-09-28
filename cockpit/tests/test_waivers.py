"""The waiver model (engine/waivers.py, GOVERNANCE.md §8).

Dates are injected rather than read from the clock: a test that passes today and
fails in three weeks is worse than no test.
"""
import datetime as dt

import pytest

from engine import waivers, index, parser, validate

TODAY = dt.date(2026, 6, 1)


def _node(**over):
    exc = {"state": "granted", "kind": "known-gap", "owner": "hartwig",
           "expires": dt.date(2026, 12, 31), "reason": "waiting on vendor"}
    exc.update(over.pop("waiver", {}))
    node = {"id": "n", "parent": None, "kind": "component", "status": "implemented",
            "code": [], "contract": {"purpose": "x"}, "waiver": exc}
    node.update(over)
    return {"n": node}


def _hard(nodes):
    return [m for sev, m in waivers.issues(nodes, TODAY) if sev == "HARD"]


def _warn(nodes):
    return [m for sev, m in waivers.issues(nodes, TODAY) if sev == "WARN"]


# ---- typed / owned / time-boxed ---------------------------------------------

def test_a_well_formed_open_waiver_is_accepted():
    assert waivers.issues(_node(), TODAY) == []


@pytest.mark.parametrize("kind", waivers.TYPES)
def test_all_four_documented_types_are_accepted(kind):
    status = "specd" if kind == "frontier-stub" else "implemented"
    assert _hard(_node(status=status, waiver={"kind": kind})) == []


def test_an_unknown_type_is_hard():
    assert "unknown kind" in _hard(_node(waiver={"kind": "temporary"}))[0]


def test_a_waiver_without_an_owner_is_hard():
    assert "no owner" in _hard(_node(waiver={"owner": None}))[0]


def test_a_waiver_without_an_expiry_is_hard():
    assert "no expiry" in _hard(_node(waiver={"expires": None}))[0]


def test_an_unparseable_expiry_is_hard_not_silently_ignored():
    """The dangerous shape: 'soon' must not read as 'not expired'."""
    msgs = _hard(_node(waiver={"expires": "soon"}))
    assert "unparseable expiry" in msgs[0]
    assert not waivers.is_expired({"expires": "soon"}, TODAY)  # malformed != expired


def test_an_iso_string_expiry_works_like_a_yaml_date():
    """PyYAML turns an unquoted date into a date object, a quoted one stays a
    string. Both are written by humans; both must behave the same."""
    assert waivers.expiry({"expires": "2026-12-31"}) == dt.date(2026, 12, 31)
    assert waivers.expiry({"expires": dt.date(2026, 12, 31)}) == dt.date(2026, 12, 31)


# ---- the guard against rot ---------------------------------------------------

def test_an_expired_waiver_is_hard_and_says_how_long():
    msg = _hard(_node(waiver={"expires": dt.date(2020, 1, 1)}))[0]
    assert "EXPIRED 2020-01-01" in msg and "2343 days ago" in msg


def test_a_waiver_expiring_soon_warns_before_it_blocks():
    assert "expires 2026-06-10" in _warn(_node(waiver={"expires": dt.date(2026, 6, 10)}))[0]
    assert _hard(_node(waiver={"expires": dt.date(2026, 6, 10)})) == []


def test_a_waiver_far_out_is_quiet():
    assert waivers.issues(_node(waiver={"expires": dt.date(2027, 1, 1)}), TODAY) == []


# ---- never masquerading as done ---------------------------------------------

def test_verified_with_an_open_waiver_is_hard():
    assert any("at most 'implemented'" in m for m in _hard(_node(status="verified")))


def test_a_frontier_stub_may_not_claim_to_be_built():
    for status in ("implemented", "verified"):
        msgs = _hard(_node(status=status, waiver={"kind": "frontier-stub"}))
        assert any("may not present" in m for m in msgs), status
    assert _hard(_node(status="specd", waiver={"kind": "frontier-stub"})) == []


def test_an_excepted_node_does_not_count_as_done():
    nodes = _node(status="verified")
    assert waivers.not_done(nodes, TODAY) == {"n"}
    # an EXPIRED waiver is no longer open -- it is a blocking error instead
    expired = _node(status="verified", waiver={"expires": dt.date(2020, 1, 1)})
    assert waivers.not_done(expired, TODAY) == set()


def test_a_malformed_waiver_block_is_reported_not_ignored():
    nodes = _node()
    nodes["n"]["waiver"] = "known-gap"     # a bare string, not a mapping
    assert "malformed waiver" in _hard(nodes)[0]


# ---- surfaced on every run ---------------------------------------------------

def test_the_validate_header_always_shows_open_waivers(tmp_path):
    (tmp_path / "SPEC.md").write_text(
        "---\nid: n\nparent: null\nkind: component\nstatus: implemented\ncode: []\n"
        "contract: {purpose: x}\n"
        "waiver:\n  state: granted\n  kind: known-gap\n  owner: hartwig\n  expires: 2099-01-01\n"
        "---\n\n# n\n", encoding="utf-8")
    out = validate.run(parser.load_nodes(tmp_path), str(tmp_path))
    assert "waivers: 1 open (n), next expiry 2099-01-01" in out
    assert "gate: pass" in out          # open and healthy does not block


def test_a_graph_without_waivers_says_none(tmp_path):
    (tmp_path / "SPEC.md").write_text(
        "---\nid: n\nparent: null\nkind: system\nstatus: specd\ncode: []\n---\n\n# n\n",
        encoding="utf-8")
    assert "waivers: none" in validate.run(parser.load_nodes(tmp_path), str(tmp_path))


def test_the_index_separates_done_from_excepted(tmp_path):
    (tmp_path / "SPEC.md").write_text(
        "---\nid: a\nparent: null\nkind: system\nstatus: verified\ncode: []\n"
        "contract: {purpose: x}\n---\n\n# a\n", encoding="utf-8")
    (tmp_path / "b").mkdir()
    (tmp_path / "b" / "SPEC.md").write_text(
        "---\nid: a.b\nparent: a\nkind: component\nstatus: verified\ncode: []\n"
        "contract: {purpose: y}\n"
        "waiver:\n  state: granted\n  kind: deferred-test\n  owner: h\n  expires: 2099-01-01\n"
        "---\n\n# b\n", encoding="utf-8")
    idx = index.build_index(parser.load_nodes(tmp_path), str(tmp_path))
    assert idx["progress"]["verified"] == ["a"]
    assert idx["progress"]["open_waivers"] == ["a.b"]
    assert idx["progress"]["done"] == 1 and idx["progress"]["of"] == 2
    assert idx["nodes"]["a.b"]["waiver"]["kind"] == "deferred-test"


# ---- requested vs granted ---------------------------------------------------
#
# Run 02: an agent had to deviate from a global invariant (svc.gui.choose does
# not raise), was not allowed to write a waiver, and so described the
# deviation in prose -- no owner, no expiry, invisible to the gate. The rule had
# prevented the RECORD, not the deviation. Requesting and granting are now
# separate acts.

def _request(**over):
    exc = {"state": "requested", "kind": "known-gap",
           "reason": "choose() reports errors in the interface instead of raising"}
    exc.update(over)
    return _node(waiver=exc)


def test_a_missing_state_is_hard_rather_than_read_as_granted():
    """No default: the permissive value must not be what you get by saying nothing."""
    nodes = _node()
    del nodes["n"]["waiver"]["state"]
    assert any("no valid state" in m for m in _hard(nodes))
    assert waivers.open_waivers(nodes, TODAY) == {}


def test_an_unknown_state_is_hard():
    nodes = _node(waiver={"state": "approved-by-me"})
    assert any("no valid state" in m for m in _hard(nodes))


def test_a_request_needs_no_owner_and_no_expiry():
    """Those are the grant. An agent cannot own a deviation."""
    nodes = _request()
    del nodes["n"]["waiver"]["owner"], nodes["n"]["waiver"]["expires"]
    assert _hard(nodes) == []


def test_a_request_must_say_why():
    nodes = _request(reason="")
    assert any("gives no reason" in m for m in _hard(nodes))


def test_a_request_is_visible_on_every_run():
    warns = _warn(_request())
    assert any("REQUESTED on n (known-gap), awaiting a decision by H" in m
               and "instead of raising" in m for m in warns)


def test_a_request_grants_nothing():
    nodes = _request()
    assert waivers.open_waivers(nodes, TODAY) == {}      # not in force
    assert waivers.requested_waivers(nodes) == {"n": nodes["n"]["waiver"]}
    assert waivers.not_done(nodes, TODAY) == {"n"}           # but not done either


def test_a_request_does_not_expire():
    nodes = _request()
    nodes["n"]["waiver"]["expires"] = dt.date(2020, 1, 1)
    assert not any("EXPIRED" in m for m in _hard(nodes))


def test_a_proposed_expiry_must_be_a_date():
    assert any("unparseable proposed_expiry" in m for m in _hard(_request(proposed_expiry="soon")))
    assert _hard(_request(proposed_expiry="2026-12-31")) == []


def test_verified_is_blocked_by_a_request_too():
    """An unresolved deviation is not done, approved or not."""
    nodes = _request()
    assert not any("requested waiver" in m for m in _hard(nodes))   # implemented: fine
    nodes["n"]["status"] = "verified"
    assert any("with a requested waiver on n" in m for m in _hard(nodes))


def test_a_frontier_stub_is_a_fake_whether_or_not_it_is_approved():
    nodes = _request(kind="frontier-stub")
    nodes["n"]["status"] = "implemented"
    assert any("may not present" in m for m in _hard(nodes))


def test_the_header_shows_requests_next_to_grants():
    nodes = {**_node(), **{"m": _request()["n"] | {"id": "m"}}}
    assert waivers.summary(nodes, TODAY) == \
        "1 open (n), next expiry 2026-12-31; 1 requested (m)"


def test_an_expired_grant_drops_out_of_not_done_because_it_blocks_instead():
    nodes = _node(waiver={"expires": dt.date(2020, 1, 1)})
    assert waivers.not_done(nodes, TODAY) == set()
    assert any("EXPIRED" in m for m in _hard(nodes))


# ---- the planner may request, never grant -----------------------------------

def test_the_planner_downgrades_a_drafted_grant_to_a_request():
    from agent import planner
    data = {"waiver": {"state": "granted", "kind": "known-gap", "owner": "the model",
                          "expires": "2099-01-01", "reason": "needed"}}
    planner._clean_waiver(data)
    assert data["waiver"] == {"state": "requested", "kind": "known-gap",
                                 "reason": "needed", "proposed_expiry": "2099-01-01"}


def test_the_planner_drops_a_malformed_waiver():
    from agent import planner
    data = {"waiver": "please"}
    planner._clean_waiver(data)
    assert "waiver" not in data


def test_revise_keeps_a_granted_waiver_and_excluded_verbatim(monkeypatch):
    """Found while building this: revise rebuilt the frontmatter from a fixed field
    list and silently erased both -- H's decisions, undone by the planner."""
    import frontmatter
    from agent import planner
    from tests.test_planner import _fake_client
    current = ("---\nid: svc.gui\nparent: svc\nkind: component\n"
               "contract: {purpose: x}\ncode: ['svc/src/svc/gui/**']\n"
               "excluded: ['svc/src/svc/gui/generated.py']\n"
               "waiver: {state: granted, kind: known-gap, owner: hartwig,"
               " expires: '2026-12-31', reason: r}\n"
               "status: implemented\n---\n# gui\n")
    monkeypatch.setattr(planner, "_client", lambda: _fake_client({
        "contract": {"purpose": "reworded"}, "code": ["svc/src/svc/gui/**"],
        "waiver": {"state": "granted", "kind": "deferred-test", "owner": "model",
                      "expires": "2099-01-01", "reason": "sneaky"}}))
    meta = frontmatter.loads(planner.revise_spec(current, "reword")).metadata
    assert meta["waiver"]["owner"] == "hartwig"          # H's grant, untouched
    assert meta["waiver"]["kind"] == "known-gap"
    assert meta["excluded"] == ["svc/src/svc/gui/generated.py"]


def test_revise_turns_a_new_proposal_into_a_request(monkeypatch):
    import frontmatter
    from agent import planner
    from tests.test_planner import _fake_client
    current = ("---\nid: svc.gui\nparent: svc\nkind: component\n"
               "contract: {purpose: x}\ncode: []\nstatus: specd\n---\n# gui\n")
    monkeypatch.setattr(planner, "_client", lambda: _fake_client({
        "contract": {"purpose": "x"},
        "waiver": {"state": "granted", "kind": "known-gap", "reason": "needed"}}))
    meta = frontmatter.loads(planner.revise_spec(current, "x")).metadata
    assert meta["waiver"]["state"] == "requested"


# ---- the rename must not create a silent pass --------------------------------

def test_the_old_field_name_is_reported_not_silently_ignored():
    """Before this check, a grant under `exception:` that expired in 2020 read as
    `waivers: none` and passed the gate -- nothing reads the old key."""
    nodes = {"a": {"id": "a", "parent": None, "kind": "system", "status": "implemented",
                   "exception": {"state": "granted", "kind": "known-gap", "owner": "h",
                                 "expires": dt.date(2020, 1, 1)}}}
    hard = [m for s, m in waivers.issues(nodes, TODAY) if s == "HARD"]
    assert any("still uses the field `exception:`" in m and "renamed to `waiver:`" in m
               for m in hard), hard


def test_the_name_is_explained_where_the_concept_is_defined():
    """So nobody renames it back for the same reason it was renamed."""
    assert "collides with programming" in waivers.__doc__
