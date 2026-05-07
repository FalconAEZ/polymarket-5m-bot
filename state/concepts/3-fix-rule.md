---
title: The 3-fix rule
tags: [concept, discipline, anti-drift]
---

# The 3-fix rule

> If three iterations don't resolve a bug, stop. Write an incident document. Get sign-off before iteration 4.

## What it is

Anti-vibe rule #3 (and operating rule #19). The single most important guardrail against the LLM-assisted bug-fix spiral.

## What it isn't

- It's not a 3-strike count on the project. It's per-issue.
- It doesn't apply to formatting, docstring, or dependency-bump fixes (those are exempt).
- It applies to anything touching trading logic, signing, money flow, or async control flow.

## What "iteration" means

One iteration = one cycle of (read failure → propose fix → apply → test → fail again). If you've done that three times on the same bug — even if each time you fix a different *symptom* — you've hit the rule.

## The carve-out

The user explicitly accepted a carve-out at session-design time:

> Applies to anything touching trading logic, signing, money flow, or async control flow. Pure-formatting / docstring / dependency-bump fixes are exempt.

So: re-running the linter after a tiny edit doesn't count. Trying three different patches to the kill-switch logic does.

## What to do when you hit it

1. **Stop.** Do not propose iteration #4.
2. **Write `runbooks/incidents/<UTC-date>-<slug>.md`** containing:
   - What you observed (failure messages, line numbers).
   - What you tried in iterations 1, 2, 3 — verbatim.
   - Your root-cause hypothesis (now, with three datapoints, you should have one).
   - What you would do for iteration 4 if signed off.
3. **Surface to the operator.** Don't proceed without their explicit go.

## Why three and not five or two

Two is too few — you might have just had bad luck on the first try. Five is enough that you've already spent an hour on a bug that probably needs a different approach entirely. Three is the empirical sweet spot from people who've spent careers debugging.

After three iterations, the failure mode is almost always:
- You're solving the wrong problem.
- Your mental model of the system is wrong.
- The bug is in a different layer than you think.

Writing the incident document forces you to articulate the failure. That alone usually surfaces the right root cause.

## How it relates to the broader operating discipline

- [[anti-vibe-rules]] frames it as anti-drift trigger #19.
- [[gate-discipline]] is the macro version (phase gates); the 3-fix rule is the micro version (per-bug gates).
- The point of both is the same: catch the loops before they consume the day.

## Real applicability in this project

We **didn't** hit the 3-fix rule in this session — but we got close in Phase A when the data API's 3500-cap surprised us. The right move (taken) was to acknowledge the data limitation, document the finding, and ask the operator before designing further. The user's pushback ("why not 7 days") then triggered the proper second pass via the per-market enumeration recipe — which worked first try.

## See also

- [[anti-vibe-rules]] — the broader rule set
- [[gate-discipline]] — the phase-level analog
- [[../postmortems/README]] — where post-recovery write-ups go
