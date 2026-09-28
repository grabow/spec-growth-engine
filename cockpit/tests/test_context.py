from engine import context, parser


def _section(bundle: str, header: str, next_header: str) -> str:
    return bundle.split(header, 1)[1].split(next_header, 1)[0]


def test_bundle_has_all_sections(graph_root):
    nodes = parser.load_nodes(graph_root)
    arch = parser.load_architecture(graph_root)
    b = context.assemble(nodes, arch, "api.hello", str(graph_root))
    for header in [
        "# ARCHITECTURE.md",
        "# Ancestor contracts",
        "# Target node: api.hello (full spec)",
        "# Own code",
        "# Dependency contracts",
    ]:
        assert header in b


def test_ancestors_are_short_form(graph_root):
    nodes = parser.load_nodes(graph_root)
    arch = parser.load_architecture(graph_root)
    b = context.assemble(nodes, arch, "api.hello", str(graph_root))
    ancestors = _section(b, "# Ancestor contracts", "# Target node")
    # short form keeps provides/invariants/purpose but DROPS acceptance_criteria
    assert "APP_PROVIDES" in ancestors
    assert "APP_INVARIANT" in ancestors
    assert "APP_ACCEPT_MARKER" not in ancestors


def test_target_full_and_owncode_and_deps(graph_root):
    nodes = parser.load_nodes(graph_root)
    arch = parser.load_architecture(graph_root)
    b = context.assemble(nodes, arch, "api.hello", str(graph_root))
    target = _section(b, "# Target node: api.hello (full spec)", "# Own code")
    assert "greet prints hallo" in target            # full target keeps acceptance_criteria
    assert 'print("hallo")' in b                       # own code inlined
    deps = b.split("# Dependency contracts", 1)[1]
    assert "util" in deps and "log()" in deps          # one-hop dep contract


def test_the_bundle_skips_build_output_and_survives_bytes_that_are_not_utf8(graph_root):
    """Run 07 died here: `svc/src/svc/textfile/**` caught a __pycache__/*.pyc,
    and the bundle was read as UTF-8, so `cli.py code` ended in a traceback
    before C was ever started."""
    from engine import context, parser
    cache = graph_root / "util" / "__pycache__"
    cache.mkdir()
    (cache / "log.cpython-312.pyc").write_bytes(b"\x00\xc0\xde not text")
    (graph_root / "util" / "fixture.py").write_bytes(b"# caf\xe9 in Latin-1\n")
    nodes = parser.load_nodes(graph_root)
    nodes["util"]["code"] = ["util/**"]
    bundle = context.assemble(nodes, "", "util", str(graph_root))
    assert "log.cpython-312.pyc" not in bundle      # build output is not context
    assert "caf� in Latin-1" in bundle          # the odd byte, not a crash
