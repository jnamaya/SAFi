---
title: SAFi Explained: The Will
slug: will
tags: ["safi", "faculties"]
summary: The Intellect proposes. The Will decides.
version: 1.0
---

# SAFi Explained: The Will

The Intellect proposes. The Will decides.

That sentence is the whole faculty, but it hides two things that matter. The Will is not one gate at the end of the line — it acts at five separate points in a single turn. And it does all of it without a language model of any kind.

## The Will is blind, on purpose

The Will has no model. Not a small one, not a cheap one — none. Every decision it makes is ordinary deterministic code: string comparisons, list membership, numeric thresholds.

This is a design commitment, and the classical formula for it is *nihil volitum nisi praecognitum* — nothing is willed unless first known. The Will cannot read semantic meaning and cannot evaluate whether something is good. It has no opinion about your question. What it can do is check structure, and act on judgments handed to it by the faculties whose job *is* judgment.

Three limitations follow, and each is deliberate:

**No moral apprehension.** The Will cannot tell you whether an answer is ethical. It relies entirely on the Conscience's scores to "see" alignment at all. Asked to judge meaning, it would have to guess, and a gatekeeper that guesses is not a gate.

**No body.** It has no drives, appetites or passions — none of what constantly pulls against a human will. It operates in a sterile computational vacuum. There is nothing in it to tempt.

**Duty, not desire.** A human will has a teleological hunger: it wants to flourish, and it reasons toward that. Software has no genuine desire, so pretending otherwise would be theatre. The Will is instead a strictly Kantian engine, enforcing structural invariants out of duty to the rule, without context, nuance, or orientation toward the Good.

That sounds like a list of things the Will is bad at. It is really a list of reasons to trust it. A gate that cannot be persuaded, cannot be flattered, and has no preferences of its own is exactly what you want holding the keys — and it is why the same input produces the same verdict every time, which is what makes a decision auditable at all.

## Five checkpoints in one turn

### 1. Before the Intellect ever runs

The first thing the Will does happens before any model is called. A pre-generation gate examines the raw prompt, so that adversarial content never reaches the drafting step in the first place. It runs four checks: known injection signatures, a per-agent list of blocked phrases, a probe detector, and a heuristic for instructions smuggled inside data.

The probe detector is worth a paragraph, because getting it wrong taught us something. It fires when a prompt names the system's internal governance machinery *and* asks for it to be handed over — a co-occurrence, not a word list. It used to be a flat list of phrases, and the result was that the words became unsayable: a marketing agent refused a request to review SAFi's own published value propositions, because a sentence from our README matched a banned phrase verbatim.

Those nouns are everyday vocabulary for compliance officers, engineers and marketers. Blocking the vocabulary blocks the conversation. Requiring the noun *and* a request to disclose still catches the real attack while letting people talk about the system in ordinary language.

The last check looks for the indirect-injection pattern: a high-entropy blob of apparent gibberish with an instruction block buried inside it, followed by a request to reproduce the text. Notably, the entropy scan slides across the whole prompt. It used to sample only the opening characters, which meant a paragraph of harmless prose in front of the payload defeated it completely.

### 2. Before a tool is allowed to act

When the Intellect proposes a tool call, the Will decides whether it may proceed. Three things happen in order.

First, an allow-list check: if the tool is not among those the agent is permitted, it is refused. An agent offered no tools at all is deny-all, because a tool name arriving from an agent with no tools is either a hallucination or an injection.

Second, read-only tools take a fast path. A calculator or a weather lookup carries no destructive side-effect, so it is approved immediately.

Third, anything that can write gets its **parameters** checked, not just its name. A tool may be permitted while a particular argument is not. And omitting a constrained parameter is a refusal rather than a pass, because falling through to the tool's own server-side default would mean trusting a value nobody vetted.

That distinction is the difference between authorising a capability and authorising an action.

### 3. On the shape of the draft

Once a draft exists, the Will checks its structure — again with no model involved. Is the required disclaimer present? Does it contain a code block the agent is not permitted to emit?

The disclaimer case has a wrinkle worth knowing. If the line is missing, the Will does not discard the draft; it appends the configured text and re-checks, and blocks only when there is nothing to repair with. Models omit the line intermittently, and throwing away an otherwise sound answer served nobody. The repaired draft still faces the full audit that follows.

### 4. After the Conscience has scored

Some values are marked as hard gates. If the Conscience scores one of them as a violation, the Will blocks the response outright, no matter how well everything else scored. A hard gate is not weighed against anything — that is what makes it hard.

The interesting part is what happens when a hard gate has *no* score. If the Conscience omitted it, timed out, or returned something unusable, the Will treats the silence as a violation rather than a pass. Absence of evidence is not evidence of compliance.

### 5. On the final number

The Spirit aggregates the Conscience's scores into a single alignment figure. It does not act on it. The Will compares that figure against a threshold — configurable per agent — and issues the last verdict of the turn.

This division is precise and easy to miss: **the Spirit computes, the Will decides.** Every approve and every block in SAFi belongs to one faculty, which is what makes the audit trail answer "who decided this?" with a single name.

## What a refusal actually looks like

A blocked draft is not replaced with a stack trace or a bare error. The Will routes to a governed redirect, and the reason it recorded determines which redirect fires — a scope breach, a grounding failure and a content-quality problem are different failures and get different responses.

One detail matters for security: when generating that redirect, the system deliberately withholds the user's original prompt. If the prompt contained an injection, feeding it back in while asking for a polite refusal is an excellent way to have the attack reproduced inside the apology.

## Failing closed

A theme runs through all five checkpoints. When the Will cannot obtain the information it needs, it refuses.

An unscored hard gate is a violation. A missing audit is a violation. A constrained parameter left unspecified is a refusal. None of these are error conditions the system tries to work around — each is a decision to stop, because the alternative is shipping something ungoverned and calling it governed.

This is the cost of the Will's blindness, and its point. It cannot use judgment to paper over missing information, because it has no judgment to use. All it can do is notice that something it requires is absent, and decline.

The Intellect is free to think anything. The Will is what decides whether any of it reaches the world.
