---
title: SAFi Explained: The Intellect
slug: safi-intellect
tags: ["safi", "faculties"]
summary: If Values are what SAFi is faithful to, the Intellect is where the work starts. It is the generative faculty — the one that reads the situation and proposes what to say or do.
version: 1.0
---

# SAFi Explained: The Intellect

If Values are what SAFi is faithful to, the Intellect is where the work starts. It is the generative faculty — the one that reads the situation and proposes what to say or do.

It is also the only faculty in SAFi permitted to be creative, and the only one given no power to act on it. That combination is deliberate, and it is most of what this article is about.

## A role, not a model

In the current system the Intellect is a language model. Which model is a configuration value, not a fact about the framework.

That matters more than it sounds. The Intellect is defined by its *position* in the loop — it receives an assembled brief, it returns a proposal, it never executes. Anything that can fill that contract can fill the role. A different provider, a smaller local model, a future model that does not exist yet, or in principle a human being writing the draft by hand. Naming a model in the architecture would trade a durable design for a temporary one.

So the description below never says which model is answering. That is the point.

## Nothing reaches the model raw

When a prompt arrives, the Intellect does not see the user's words in isolation. SAFi assembles a brief first, in a fixed order: the agent's worldview, who it is talking to, what it learned in earlier conversations, a summary of this one, the last few turns verbatim, coaching from the Spirit, the tools it may ask for, and how the answer should be shaped. Each part appears only when it has something to say. The diagram above sets them out in order.

Two parts of that brief deserve more than a line.

**Coaching from the Spirit** is the only path by which the loop's own judgment re-enters the drafting step. Everything else in the brief describes the situation; this describes how the agent has been doing. Without it, each turn would be independent and the system could drift indefinitely without ever noticing.

**Retrieval**, for an agent that has a knowledge base, is folded into the worldview rather than handed over as a section of its own — what was found for this question becomes part of the principles the agent reasons from. It is also optional, and stays that way. Most agents have no knowledge base at all, so the machinery for searching one is loaded only when a knowledge base is configured — a deployment that does not need vector search should not pay for it. If the retrieval extras are missing, the agent answers without them rather than failing to start. And when a search returns nothing, the Intellect is told so explicitly instead of being left to guess from silence.

## What the Intellect is deliberately not given

The agent's values never enter this brief. Neither do their weights, nor their scoring rubrics.

This is easy to misread as an oversight, so it is worth being plain: the Intellect is directed by the worldview and the style. The values are the **Conscience's** instrument, applied to the draft after the draft exists.

The reason is the ordinary reason for separating anything. A drafter that knew exactly which rubric it would be scored against, and by what weights, would be tempted to write for the rubric rather than for the person asking. Worse, its self-assessment would then be worthless as an independent check, because it would be grading its own paper. Keeping the standard out of the drafting step is what makes the later score mean something.

## The Air Gap of Intent

Here is the property that matters most, and the one most easily lost in an ordinary agent framework.

A modern language model can ask to call a tool. In a typical agent stack, that request *is* the action: the framework receives it and executes it, and governance — if any — happens afterwards, in a log.

SAFi intercepts it. When the model asks for a tool, the request is captured as data and returned as a proposal. The Intellect holds zero execution rights. It cannot read a file, send a message, or write to a system, because the code that would do those things is on the other side of a boundary it has no way to cross.

What comes back from the Intellect is therefore a **typed intent** — a description of what it wants to happen, never the happening itself. It is either a draft answer with a short reflection on the reasoning behind it, or a named tool with the arguments it would like passed to that tool, or nothing at all, when the model could not be reached. That last case is worth doing properly: SAFi reports the actual cause — a bad key, a rate limit, a model that does not exist — rather than an opaque failure, because "the Intellect failed" is not a thing anyone can act on.

Only the **Will** can turn a tool-call intent into a tool call, and it checks both whether the agent may use that tool and whether these particular arguments are acceptable. When a tool does run, its result comes back for the Intellect to continue from — so a multi-step task is a sequence of proposals, each authorised on its own merits, rather than one grant of trust at the beginning.

This is what makes the difference between an agent that is *observed* and an agent that is *governed*. A log tells you what happened. An air gap decides whether it happens.

## Where the Intellect sits

The full sequence around a single turn:

The Will appears five times — step 3 only when a tool is actually proposed. In the framework as originally conceived, the sequence was strictly linear: understand, then decide, then judge. Building a system that can *act* forced a revision, because authorisation has to happen before an action, not only after a result. So the Intellect is bracketed by judgment on both sides, and the creative step is the only one in the loop that is never trusted on its own.

Worth noting what step 8 implies: the Spirit computes the alignment figure but does not act on it. Every approve and every block belongs to the Will, which is what lets the audit trail answer "who decided this?" with one name.

That is the trade SAFi makes. The Intellect is free to think anything. It is free to do nothing.
