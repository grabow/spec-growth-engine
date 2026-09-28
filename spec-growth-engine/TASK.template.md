# TASK.md — template

> Part of the **Spec Growth Engine** method: the GOAL of a run, in prose
> ([SPEC-GROWTH-ENGINE.md §3.12](SPEC-GROWTH-ENGINE.md)). `New Project...` in the
> cockpit, or `cli.py init ROOT ... --does ...`, fills it from your answers and
> writes everything below the marker to `<root>/TASK.md`. H′ checks a run
> against that file, statement by statement.
>
> Placeholders -- each filled with your words, as written, one bullet per line:
>
>   {{PURPOSE}}        what the system is for (may stay empty)
>   {{MUST_DO}}        what it must do: one line per command or behaviour
>   {{ALWAYS}}         what must always be true, whichever command runs
>   {{OUT_OF_SCOPE}}   what you deliberately do NOT want built
>
> A section whose placeholder stays empty is left out -- except "What it must
> do", which is never empty (a TODO stands in). "Done means" is the METHOD's
> standard, not the project's: change it here and every new project gets the
> change; change it in a project's TASK.md and only that project does.

<!-- TASK.md starts here -->
# Task

{{PURPOSE}}

## What it must do

{{MUST_DO}}

## What must always be true

{{ALWAYS}}

## Done means

- Every behaviour above has a test that would fail if the behaviour broke.
- The tests are green, offline, from the build root.
- The gate passes, with no warnings you cannot explain.
- Every component you create is at least `implemented`.

## Deliberately not specified

How this is split into components, what they are named, and which one depends on which. That is the intent author's to decide and to write down in the specs -- with the reason in the prose of each SPEC.md.

## Out of scope

{{OUT_OF_SCOPE}}
