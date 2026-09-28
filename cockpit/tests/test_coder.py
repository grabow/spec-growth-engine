import pytest

from agent import coder

MANIFESTS = [
    "pom.xml", "build.gradle.kts", "settings.gradle",
    "pyproject.toml", "Cargo.toml", "pubspec.yaml", "package.json",
]


@pytest.mark.parametrize("manifest", MANIFESTS)
def test_find_build_root_from_deep_node(tmp_path, manifest):
    (tmp_path / manifest).write_text("x", encoding="utf-8")
    deep = tmp_path / "a" / "b" / "c"
    deep.mkdir(parents=True)
    assert coder.find_build_root(deep, tmp_path) == tmp_path.resolve()


def test_loose_scripts_fall_back_to_node_dir(tmp_path):
    node = tmp_path / "scripts" / "tool"
    node.mkdir(parents=True)
    # no manifest anywhere -> run in the node's own directory
    assert coder.find_build_root(node, tmp_path) == node.resolve()


def test_nearest_manifest_wins(tmp_path):
    (tmp_path / "package.json").write_text("{}", encoding="utf-8")
    inner = tmp_path / "sub"
    inner.mkdir()
    (inner / "pyproject.toml").write_text("x", encoding="utf-8")
    leaf = inner / "pkg"
    leaf.mkdir()
    assert coder.find_build_root(leaf, tmp_path) == inner.resolve()


def test_followup_prompt_replays_context_and_message():
    p = coder.followup_prompt("BUNDLE-CTX", "cli.x", "PRIOR-OUTPUT", "why this design?")
    assert "BUNDLE-CTX" in p                       # original context replayed
    assert "PRIOR-OUTPUT" in p                     # prior output replayed
    assert "why this design?" in p                 # the new message
    assert "cli.x" in p
    assert "# FOLLOW-UP" in p                       # the follow-up framing


def test_followup_prompt_handles_empty_prior_output():
    p = coder.followup_prompt("CTX", "n", "", "go")
    assert "(none yet)" in p                        # graceful when nothing streamed yet
