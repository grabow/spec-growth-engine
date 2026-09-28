"""One readable line per event of a run's stream (orchestrate.py).

Two readers render the same stream, and a person comparing them should see the
same words: the cockpit's Run window (app.py), and the run's own log in the
project (<root>/.sge/runs/NN.log, written by orchestrate.Record -- follow it with
`tail -f`, or run `cli.py run`, which prints the same lines). So the rendering
lives here, once.

`lines(event)` returns the lines that event is worth -- often none, since a
stream is mostly deltas -- or None when the event is not part of a run's stream
at all (it is then recorded as it came).

The events are codex's own (thread / turn / item) plus the run's own `sge.round`,
`sge.run` and `sge.after`, which engine/iteration.py decides and orchestrate.py
emits.
"""
from __future__ import annotations


def first(text: str, n: int = 100) -> str:
    """One line of it, at most n characters -- a log line stays a line."""
    return (text or "").strip().replace("\n", " ")[:n]


def _rounds(ev: dict) -> list[str] | None:
    """The run's own events: what a round found, and how the run ended."""
    kind = ev.get("type", "")
    if kind == "sge.round":
        closed = ev.get("closed") or []
        step = " ".join(filter(None, (ev.get("next"), ev.get("outcome"))))
        out = [f"ROUND {ev.get('round')}   claim={ev.get('claim') or '-'}"
               f"  floor={ev.get('floor') or '-'}  gaps={len(ev.get('gaps') or [])}"
               f"{'  closed=' + str(len(closed)) if closed else ''}"
               f"  -> {step}: {first(ev.get('why', ''))}"]
        out += [f"missing   {first(line)}"
                for line in (ev.get("failures") or []) + (ev.get("gaps") or [])]
        out += [f"asks H    {first(line)}" for line in ev.get("requests") or []]
        out += [f"waits H   {first(line)}" for line in ev.get("waiting") or []]
        out += [f"H' {a.get('decision', '?'):<11}"
                f"{first(a.get('node', '') + ' -> ' + a.get('target', '') + ': ' + a.get('proposal', ''))}"
                for a in ev.get("decided") or []]
        out += [f"H' accepted {first(nid)} (delegation)" for nid in ev.get("delegated") or []]
        return out
    if kind == "sge.after":
        return [f"after     {first(line, 120)}" for line in ev.get("lines") or []]
    if kind == "sge.run":
        mode = "  (unsupervised)" if ev.get("mode") == "unsupervised" else ""
        return ([f"RUN       {str(ev.get('outcome')).upper()} after "
                 f"{ev.get('rounds')} round(s){mode}: {first(ev.get('why', ''))}"]
                + [f"review H  {first(line)}" for line in ev.get("review") or []])
    return None


def _codex(ev: dict) -> list[str] | None:
    """One codex event: what the agent ran, said or changed."""
    kind = ev.get("type", "")
    item = ev.get("item") or {}
    it = item.get("type")
    if kind == "thread.started":
        return [f"START     thread {ev.get('thread_id', '')}"]
    if kind == "item.started" and it == "command_execution":
        return [f"$         {first(item.get('command', ''))}"]
    if kind == "item.completed" and it == "command_execution":
        code = item.get("exit_code")
        flag = "ERR " if code not in (0, None) else "    "
        return [f"{flag}  -> {first(item.get('aggregated_output', ''))}"
                + (f"  (exit {code})" if code not in (0, None) else "")]
    if kind == "item.completed" and it == "agent_message":
        return [f"say       {first(item.get('text', ''))}"]
    if kind == "item.completed" and it == "file_change":
        paths = [c.get("path", "") for c in item.get("changes") or []]
        short = [x.split("/workspace/")[-1] if "/workspace/" in x else x.split("/")[-1]
                 for x in paths]
        return [f"edit      {', '.join(short)[:100]}"]
    if kind == "item.completed" and it == "error":
        return [f"ERR       {first(item.get('message', ''))}"]
    if kind == "turn.completed":
        u = ev.get("usage") or {}
        return [f"TURN      in={u.get('input_tokens')}  out={u.get('output_tokens')}"
                f"  reasoning={u.get('reasoning_output_tokens')}"]
    if kind in ("turn.failed", "error"):
        err = ev.get("error") or {}
        return [f"FAILED    {first(err.get('message', '') or ev.get('message', ''))}"]
    # a stream event of a kind worth no line of its own -- part of the format
    return [] if kind.startswith(("thread.", "turn.", "item.")) else None


def lines(ev: dict) -> list[str] | None:
    """The lines this event is worth; [] for one that says nothing; None when it
    is not a run event (another format's, or not an event at all)."""
    if not isinstance(ev, dict):
        return None
    out = _rounds(ev)
    return _codex(ev) if out is None else out


def outcome(ev: dict) -> str | None:
    """How the run ended, from its last event -- None for every other event."""
    return ev.get("outcome") if ev.get("type") == "sge.run" else None
