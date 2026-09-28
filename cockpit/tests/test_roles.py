"""One model per role (agent/llm.py), and the commands through which the intent
author I reaches the planner P and the coder C (cli.py draft / revise / code).
P, H' and C are stubs here -- the suite never reaches a model or an agent CLI.
graph_root: app > api > api.hello (depends_on util), util."""
import json

import pytest

import app
import appconfig
import cli
from agent import coder, llm, planner, reviewer
from engine import parser


def _log(root):
    return [json.loads(line) for line in
            (root / ".sge" / "autonomy.jsonl").read_text(encoding="utf-8").splitlines()]


# ---- the settings --------------------------------------------------------------

def test_each_role_reads_its_own_setting(monkeypatch):
    monkeypatch.setenv("SGE_PLANNER_MODEL", "p-model")
    monkeypatch.setenv("SGE_REVIEWER_MODEL", "h-model")
    assert (llm.planner_model(), llm.reviewer_model()) == ("p-model", "h-model")


def test_the_reviewer_defaults_to_the_planners_model(monkeypatch):
    monkeypatch.setenv("SGE_PLANNER_MODEL", "p-model")
    monkeypatch.delenv("SGE_REVIEWER_MODEL", raising=False)
    assert llm.reviewer_model() == "p-model"


def test_settings_are_read_when_called_not_when_imported(monkeypatch):
    """A .env loaded after the import must still count (cli.py loads it late)."""
    monkeypatch.setenv("SGE_PLANNER_MODEL", "late")
    assert llm.planner_model() == "late"


def _client_recording(models):
    class Client:
        class chat:
            class completions:
                @staticmethod
                def create(**kw):
                    models.append(kw["model"])
                    raise RuntimeError("stop after recording")
    return Client


def test_h_prime_asks_the_reviewer_model_not_the_planners(monkeypatch):
    monkeypatch.setenv("SGE_PLANNER_MODEL", "p-model")
    monkeypatch.setenv("SGE_REVIEWER_MODEL", "h-model")
    models = []
    monkeypatch.setattr(reviewer, "_client", lambda *_: _client_recording(models))
    for call in (lambda: reviewer.review_draft("intent", "spec"),
                 lambda: reviewer.brief_hard_change("report", "old", "new")):
        with pytest.raises(RuntimeError):
            call()
    assert models == ["h-model", "h-model"]


def test_the_cockpit_persists_a_reviewer_model(monkeypatch):
    monkeypatch.delenv("SGE_REVIEWER_MODEL", raising=False)
    import importlib
    cfg = importlib.reload(appconfig)._DEFAULTS
    assert cfg["reviewer_model"] == ""   # empty: the planner's model


class _Cfg:
    _reviewer_model = app.Cockpit._reviewer_model
    _independence_note = app.Cockpit._independence_note

    def __init__(self, **cfg):
        self.config_data = {"planner_model": "p-model", **cfg}


def test_the_cockpit_says_when_the_review_is_not_independent():
    assert "not an independent review" in _Cfg()._independence_note()
    assert "not an independent review" in _Cfg(reviewer_model="p-model")._independence_note()
    assert _Cfg(reviewer_model="h-model")._independence_note() == ""
    assert _Cfg(reviewer_model="h-model")._reviewer_model() == "h-model"


# ---- P through the CLI: draft and revise ----------------------------------------

_DRAFT = ("---\nid: api.store\nparent: api\nkind: component\n"
          "contract:\n  provides: [\"keep(item)\"]\ncode: []\nstatus: specd\n---\n\n# Store\n")


def test_draft_puts_ps_spec_where_the_layout_rule_says(graph_root, monkeypatch, capsys):
    monkeypatch.setenv("SGE_PLANNER_MODEL", "p-model")
    asked, spines = [], []
    monkeypatch.setattr(planner, "draft_spec",
                        lambda intent, nid, parent, kind, spine, **_k:
                        asked.append((intent, nid, parent, kind))
                        or spines.append(spine) or _DRAFT)
    assert cli.main(["draft", str(graph_root), "api.store", "--parent", "api",
                     "--intent", "keep items"]) == 0
    assert asked == [("keep items", "api.store", "api", "component")]
    # P sees the ancestors' contracts -- where the container's code layout is
    assert set(spines[0]) == {"app", "api"} and spines[0]["api"]["provides"] == ["http"]
    assert (graph_root / "api" / "store" / "SPEC.md").is_file()
    out = capsys.readouterr().out
    assert "drafted api.store" in out and "(by P: p-model)" in out
    assert "change set api.store" in out
    entry = _log(graph_root)[-1]
    assert (entry["actor"], entry["by"], entry["action"]) == ("P", "p-model", "drafted")


def test_draft_does_not_touch_the_parent(graph_root, monkeypatch):
    """The parent may be a given file the intent author may not edit."""
    before = (graph_root / "api" / "SPEC.md").read_text(encoding="utf-8")
    monkeypatch.setattr(planner, "draft_spec", lambda *_a, **_k: _DRAFT)
    cli.main(["draft", str(graph_root), "api.store", "--parent", "api", "--intent", "x"])
    assert (graph_root / "api" / "SPEC.md").read_text(encoding="utf-8") == before


@pytest.mark.parametrize("nid,parent,why", [
    ("util", "app", "exists"),
    ("api.store", "nowhere", "no parent"),
    ("store", "api", "has the id 'api.store'"),
])
def test_draft_refuses_what_does_not_fit(graph_root, monkeypatch, capsys, nid, parent, why):
    monkeypatch.setattr(planner, "draft_spec",
                        lambda *_a, **_k: pytest.fail("P must not be asked"))
    assert cli.main(["draft", str(graph_root), nid, "--parent", parent,
                     "--intent", "x"]) == 2
    assert why in capsys.readouterr().err


def test_revise_hands_p_the_current_spec(graph_root, monkeypatch, capsys):
    seen = []

    def revise(current, change, **_k):
        seen.append((current, change))
        return current.replace("log()", "log()\n  - flush()")
    monkeypatch.setattr(planner, "revise_spec", revise)
    assert cli.main(["revise", str(graph_root), "util", "--change", "add flush"]) == 0
    assert "log()" in seen[0][0] and seen[0][1] == "add flush"
    assert "flush()" in (graph_root / "util" / "SPEC.md").read_text(encoding="utf-8")
    assert "change set util: SOFT" in capsys.readouterr().out
    assert _log(graph_root)[-1]["action"] == "revised"


def test_p_unavailable_is_said_not_raised(graph_root, monkeypatch, capsys):
    def down(*_a, **_k):
        raise RuntimeError("the provider refused: 401")
    monkeypatch.setattr(planner, "revise_spec", down)
    assert cli.main(["revise", str(graph_root), "util", "--change", "x"]) == 2
    assert "P unavailable: the provider refused: 401" in capsys.readouterr().err


# ---- C through the CLI: code ----------------------------------------------------

class _Proc:
    def __init__(self, lines, code=0):
        self.stdout, self._code = iter(lines), code

    def wait(self):
        return self._code


@pytest.fixture(autouse=True)
def _no_real_env(monkeypatch):
    """cli.py loads cockpit/.env; the tests must not pick up its real roles."""
    monkeypatch.setattr(cli, "_load_env", lambda: None)
    for role in ("PLANNER", "REVIEWER", "INTENT", "CODER"):
        for field in ("BASE_URL", "API_KEY", "MODEL", "KEYCHAIN"):
            monkeypatch.delenv(f"SGE_{role}_{field}", raising=False)
    monkeypatch.delenv("SGE_CODER_CMD", raising=False)


def test_code_runs_c_with_the_coder_command_and_keeps_its_output(graph_root, monkeypatch,
                                                                  capsys):
    monkeypatch.setenv("SGE_CODER_CMD", "my-coder --flag")
    started = []
    monkeypatch.setattr(coder, "implement",
                        lambda bundle, nid, node, root, command, env=None: started.append(
                            (nid, command, bundle)) or _Proc(["wrote greet.py\n"]))
    assert cli.main(["code", str(graph_root), "api.hello",
                     "--instruction", "keep it small"]) == 0
    nid, command, bundle = started[0]
    assert (nid, command) == ("api.hello", "my-coder --flag")
    assert "keep it small" in bundle and "api.hello" in bundle
    assert "wrote greet.py" in capsys.readouterr().out
    [log] = list((graph_root / ".sge" / "code").glob("api.hello-*.log"))
    assert "wrote greet.py" in log.read_text(encoding="utf-8")
    entry = _log(graph_root)[-1]
    assert (entry["actor"], entry["by"], entry["action"], entry["exit"]) == \
        ("C", "my-coder --flag", "coded", 0)


def test_code_passes_cs_exit_code_on(graph_root, monkeypatch):
    monkeypatch.setattr(coder, "implement", lambda *a, **k: _Proc([], code=3))
    assert cli.main(["code", str(graph_root), "util"]) == 3


# ---- one endpoint per role: URL, key, model -------------------------------------

def test_the_planner_falls_back_to_openrouter(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")
    ep = llm.endpoint("planner")
    assert (ep["base_url"], ep["api_key"], ep["model"]) == \
        (llm.OPENROUTER_BASE, "or-key", llm.DEFAULT_MODEL)
    assert ep["key_from"] == "OPENROUTER_API_KEY"


def test_each_role_can_have_its_own_url_key_and_model(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")
    monkeypatch.setenv("SGE_CODER_BASE_URL", "https://api.deepseek.com")
    monkeypatch.setenv("SGE_CODER_API_KEY", "ds-key")
    monkeypatch.setenv("SGE_CODER_MODEL", "deepseek-chat")
    monkeypatch.setenv("SGE_INTENT_MODEL", "gpt-5.5")
    coder_ep, intent_ep = llm.endpoint("coder"), llm.endpoint("intent")
    assert (coder_ep["base_url"], coder_ep["api_key"], coder_ep["model"]) == \
        ("https://api.deepseek.com", "ds-key", "deepseek-chat")
    # intent sets only a model: URL and key are the planner's
    assert (intent_ep["base_url"], intent_ep["api_key"], intent_ep["model"]) == \
        (llm.OPENROUTER_BASE, "or-key", "gpt-5.5")


def test_an_agent_role_gets_no_default_model(monkeypatch):
    """A coder silently running on the planner's model is the confusion this removes."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")
    assert llm.endpoint("coder")["model"] == ""
    from agent import codex_cli
    with pytest.raises(RuntimeError, match="no model for the coder"):
        codex_cli.command("coder")


def test_a_key_can_come_from_the_keychain(monkeypatch):
    import subprocess
    calls = []

    def security(argv, **_k):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, stdout="kc-key\n", stderr="")
    monkeypatch.setattr(llm.subprocess, "run", security)
    monkeypatch.setenv("SGE_CODER_KEYCHAIN", "deepseek-api-key")
    assert llm.endpoint("coder")["api_key"] == "kc-key"
    assert llm.endpoint("coder")["key_from"] == "keychain: deepseek-api-key"
    monkeypatch.setenv("SGE_CODER_API_KEY", "file-key")          # the file wins
    assert llm.endpoint("coder")["key_from"] == "SGE_CODER_API_KEY"
    assert calls[0][:2] == ["security", "find-generic-password"] and "deepseek-api-key" in calls[0]


def test_describe_never_contains_the_key(monkeypatch):
    monkeypatch.setenv("SGE_CODER_API_KEY", "sk-SECRET-123")
    monkeypatch.setenv("SGE_CODER_MODEL", "m")
    assert "SECRET" not in llm.describe("coder")
    assert "SECRET" not in llm.endpoint("coder")["key_from"]


# ---- I and C as codex agents ------------------------------------------------------

def test_the_codex_command_names_the_key_variable_never_the_key(monkeypatch):
    from agent import codex_cli
    monkeypatch.setenv("SGE_CODER_BASE_URL", "https://api.example/v1")
    monkeypatch.setenv("SGE_CODER_API_KEY", "sk-SECRET-123")
    monkeypatch.setenv("SGE_CODER_MODEL", "some-model")
    argv, env = codex_cli.command("coder", json_events=True)
    assert "sk-SECRET-123" not in " ".join(argv)
    assert env[codex_cli.key_variable("coder")] == "sk-SECRET-123"
    assert argv[:2] == ["codex", "exec"] and "--json" in argv
    assert "--dangerously-bypass-approvals-and-sandbox" in argv
    assert 'model_providers.sge_coder.base_url="https://api.example/v1"' in argv
    assert f'model_providers.sge_coder.env_key="{codex_cli.key_variable("coder")}"' in argv
    assert argv[argv.index("-m") + 1] == "some-model"


def test_c_never_gets_an_open_stdin(monkeypatch):
    """codex exec waits on an open stdin: the first smoke test hung until killed."""
    import subprocess
    seen = {}
    monkeypatch.setattr(coder.subprocess, "Popen",
                        lambda argv, **kw: seen.update(argv=argv, **kw) or "proc")
    coder.run_prompt("do it", cwd="/tmp", command=["codex", "exec"], env={"A": "1"})
    assert seen["stdin"] is subprocess.DEVNULL
    assert seen["argv"] == ["codex", "exec", "do it"] and seen["env"] == {"A": "1"}


def test_code_runs_c_as_codex_when_the_coder_has_an_endpoint(graph_root, monkeypatch, capsys):
    monkeypatch.setenv("SGE_CODER_MODEL", "deepseek-chat")
    monkeypatch.setenv("SGE_CODER_API_KEY", "sk-SECRET-123")
    started = []
    monkeypatch.setattr(coder, "implement",
                        lambda bundle, nid, node, root, command, env=None:
                        started.append((command, env)) or _Proc(["done\n"]))
    assert cli.main(["code", str(graph_root), "util"]) == 0
    command, env = started[0]
    assert command[:2] == ["codex", "exec"] and env is not None
    entry = _log(graph_root)[-1]
    assert entry["by"].startswith("codex exec: deepseek-chat @ ")
    assert "SECRET" not in json.dumps(entry)


def test_role_agent_describes_and_execs(monkeypatch, capsys):
    import os
    import role_agent
    monkeypatch.setattr(role_agent, "_load_env", lambda: None)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-SECRET-123")
    monkeypatch.setenv("SGE_INTENT_MODEL", "gpt-5.5")
    assert role_agent.main(["--describe"]) == 0
    out = capsys.readouterr().out
    assert "intent" in out and "gpt-5.5" in out and "SECRET" not in out
    execs, dups = [], []
    monkeypatch.setattr(os, "execvpe", lambda file, argv, env: execs.append((argv, env)))
    monkeypatch.setattr(os, "dup2", lambda a, b: dups.append(b))
    role_agent.main(["intent", "--json", "the prompt"])
    argv, env = execs[0]
    assert argv[-1] == "the prompt" and "--json" in argv and dups == [0]
    assert "sk-SECRET-123" not in " ".join(argv) and "sk-SECRET-123" in env.values()


# ---- a provider that refuses a FORCED tool call (DeepSeek V4) ---------------------

def _thinking_provider(answers: list, requests: list):
    """DeepSeek V4 reasons by default and answers a forced tool_choice with 400.
    Only the forced call is refused; the same request without it is served."""
    import httpx
    import openai

    class Client:
        class chat:
            class completions:
                @staticmethod
                def create(**kw):
                    requests.append(kw)
                    if "tool_choice" in kw:
                        raise openai.BadRequestError(
                            "Error code: 400 - Thinking mode does not support this "
                            "tool_choice", response=httpx.Response(
                                400, request=httpx.Request("POST", "https://x.invalid")),
                            body=None)
                    return answers.pop(0)
    return Client


def test_a_forced_tool_call_the_provider_refuses_is_offered_instead(monkeypatch):
    """Run 07's blocker: every role died on 'Thinking mode does not support this
    tool_choice'. Offering the tool without forcing it is the same request minus
    the guarantee -- the guide already ends with 'Call <tool>'."""
    from tests.test_assist import _Resp
    requests = []
    answer = json.dumps({"verdict": "approve", "confidence": 0.9, "findings": []})
    monkeypatch.setattr(reviewer, "_client", lambda *_: _thinking_provider(
        [_Resp(answer, "tool_calls")], requests))
    assert reviewer.review_draft("intent", "spec")["verdict"] == "approve"
    assert [("tool_choice" in kw) for kw in requests] == [True, False]   # forced, then not


def test_any_other_refusal_is_still_reported_at_once(monkeypatch):
    """The fallback is for that one restriction, not a retry loop over 401s."""
    from tests.test_assist import _refusing
    monkeypatch.setattr(reviewer, "_client", _refusing)
    with pytest.raises(RuntimeError, match="provider refused: .*User not found"):
        reviewer.brief_hard_change("report", "old", "new")
