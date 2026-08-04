---
title: RAG Retrieves Evidence. SAFi Governs What the Agent Does With It.
slug: safi-with-rag-providing-current-knowledge-to-the-llms
tags: ["safi", "retrieval"]
summary: Retrieval-Augmented Generation, or RAG, gives an AI system access to information that was not present in its training data. That may include recent research, current policies, internal procedures, or an organization's private documents.
version: 1.0
---

# RAG Retrieves Evidence. SAFi Governs What the Agent Does With It.

Retrieval-Augmented Generation, or RAG, gives an AI system access to information that was not present in its training data. That may include recent research, current policies, internal procedures, or an organization's private documents.

But retrieval is not the same as grounding.

An agent can receive relevant passages and still produce a claim that those passages do not support. Standard RAG can show that a search returned documents. It does not necessarily show whether the generated answer used those documents faithfully.

SAFi adds a runtime governance layer around that step. Retrieved passages become part of the audit record. The Conscience evaluates the draft against those passages, rather than treating its own background knowledge as evidence. The Will can then enforce grounding as a policy decision before the response is returned.

The result is not a promise that an agent will never be wrong. It is a record showing what the agent was given, what it produced, how the response was evaluated, and whether policy allowed it to continue.

## The problem, concretely

The Self-Alignment Framework is specialized and recent. A general-purpose language model is unlikely to have reliable training knowledge about it.

Ask a chatbot, "What is the Self-Alignment Framework?" and it may produce a confident answer assembled from the wording of the question, related concepts, or general patterns in its training data. The answer may sound plausible without being supported by the framework's actual documentation.

The same problem appears in organizations.

An internal policy written last week, a private operating procedure, or a recently changed compliance requirement may never have appeared in a model's training data. Without access to those sources, the model cannot reliably answer from them.

RAG is the standard response: retrieve relevant passages at question time and include them in the model's context.

That solves an access problem. It does not, by itself, solve a verification problem.

## How SAFi's retrieval works

The SAFi Steward on the Self-Alignment Framework website answers from a knowledge base containing documentation about the framework. The current repository includes the RAG implementation, its knowledge-base assets, and the indexing code under the `rag/` directory.

The retrieval process is deliberately explicit.

Documents are divided into chunks so that the search system can compare a user's question with manageable sections of source material. The implementation handles Markdown headings and paragraphs rather than cutting text at arbitrary character boundaries. This preserves more of the surrounding meaning when a passage is retrieved.

That detail matters. A chunk that begins in the middle of an argument may be difficult to interpret if the heading or introductory explanation was left behind in another chunk. A heading without its supporting prose creates the opposite problem: it can look highly relevant to a search while providing no answer.

The system also avoids indexing document metadata as if it were substantive content. A title or frontmatter field can be useful for organizing a document, but it should not be mistaken for evidence supporting a response.

SAFi uses embedding-based retrieval rather than relying only on exact keyword matches. A question and a document passage can therefore be related even when they use different wording.

For example, a user might ask about "the part of the framework that evaluates a decision," while the source document uses different terminology. Semantic similarity can help identify the relevant passage even when the wording is not identical.

That does not mean semantic retrieval is infallible. It means the retrieval mechanism is designed to find related material beyond exact word matches. The retrieved passages still need to be evaluated.

## Handling follow-up questions

Short follow-up questions create a special retrieval problem.

A user may ask:

> "What about verse 4?"

That question is understandable in the context of a conversation, but it carries little meaning by itself. An embedding model may not know what "verse 4" refers to without the preceding exchange.

For short, non-citation follow-ups, SAFi can combine the recent conversation with the latest question before creating the retrieval query. The text used to find relevant passages is therefore not always identical to the text displayed as the user's question.

This improves the retrieval query without requiring an additional model call. It changes the information used for search, not the number of language-model requests.

Citation-style questions require a different approach. A request such as "John 3:16" is a lookup, not a general semantic question. The Bible Scholar path can use citation-aware lookup before falling back to semantic search. This is an example of a broader engineering principle: retrieval should match the structure of the question.

## Retrieval context must remain bounded

Retrieved information has to be bounded before it is sent to the model and the auditor.

A citation query can match many passages. Sending all of them into every prompt increases cost, consumes context, and makes the evidence harder to review. It also affects the audit because the Conscience evaluates the answer against the material supplied to it.

SAFi therefore limits the amount of retrieved context and preserves whole passages when assembling the context block. When material is omitted because of the limit, the context records that omission instead of silently presenting an incomplete evidence set.

That distinction is important.

An auditor should be able to tell the difference between:

A missing or truncated context should not look like a complete evidentiary record.

## What ordinary RAG does not establish

Suppose an agent receives five relevant passages. It can still:

The retrieval succeeded. The answer may still be wrong.

This is where SAFi's governance model changes the workflow.

RAG supplies context. SAFi evaluates the agent's use of that context and records the decision.

## What SAFi adds

### 1. Retrieved passages become part of the audit record

When the Conscience evaluates a response, the retrieved context is passed to it alongside the draft answer.

The evidence is not treated as invisible plumbing. It becomes part of the information available for review. A reviewer can compare:

This makes the relationship between source material and output inspectable.

Without that record, a later reviewer may know that retrieval occurred but not know exactly what the agent was given.

### 2. The auditor is instructed not to use its own knowledge as evidence

An evaluator may have general knowledge about a topic. That knowledge is not the same as support from the retrieved documents.

For a groundedness evaluation, the relevant question is not:

> "Does this answer sound correct to me?"

It is:

> "Does the provided source material support this answer?"

That distinction allows the audit to separate different outcomes:

A response that is not covered by the supplied sources should not receive positive grounding simply because the auditor recognizes it as plausible.

### 3. No retrieved documents are represented explicitly

If retrieval returns no documents, SAFi can represent that condition explicitly as:

```
[NO DOCUMENTS FOUND]
```

An empty context can be ambiguous. A model may interpret it as an omission and fill the gap from its general training. An explicit no-results marker communicates a different instruction: the retrieval step did not find supporting material.

That makes the absence of evidence visible both to the agent and to the audit trail.

### 4. Grounding can be enforced as a hard gate

Grounding is not merely another quality score.

An answer can be well-written, relevant, and within the agent's general scope while still making an unsupported claim. In a governed deployment, that may be unacceptable.

SAFi separates grounding failures from other policy failures. A scope violation, for example, is different from an answer that stays within scope but invents information. Different failure types can therefore be evaluated and routed differently.

When an agent policy declares grounding as a hard gate, a grounding failure blocks the response instead of being averaged away by positive scores in other categories.

The current SAFi repository documents the runtime governance architecture, including policy evaluation, hard-gate behavior, audit records, and the separation between the agent's decision process and the governing controls. The exact policy values remain deployment configuration, so claims about a particular live agent should be tied to that agent's current configuration.

## A simplified audit example

A groundedness audit can be represented conceptually like this:

```
Question:
What does the Self-Alignment Framework say about conscience?

Retrieved context:
[chunk-017]
Conscience evaluates whether a proposed action is consistent with the governing values...

Draft answer:
Conscience is the mechanism that guarantees every AI decision is morally correct.

Grounding Fidelity:
FAIL

Reason:
The retrieved passage describes an evaluation function but does not support the
claim that Conscience guarantees moral correctness.

Will decision:
BLOCK
```

The important point is not the exact formatting of this example. The important point is that the source material, draft, evaluation, and policy outcome can be examined together.

A reviewer does not have to infer what the agent might have seen. The evidence used for the decision is part of the record.

## A hard gate is not a guarantee

A hard gate improves control, but it does not turn an LLM-based evaluator into a formal proof system.

The Conscience is itself model-driven and can be:

SAFi makes the evidence and decision path inspectable. It does not guarantee that every audit judgment is correct.

High-assurance deployments still need additional safeguards, including:

This is an important distinction:

That is the value SAFi claims.

## From retrieval to governed retrieval

A basic RAG system can answer:

> "What information was retrieved?"

A governed retrieval system should also help answer:

Those questions matter to platform engineers because they affect observability and operational control.

They matter to IT directors because they affect accountability, incident review, and organizational risk.

They matter to AI governance practitioners because they connect policy requirements to runtime behavior and evidence.

SAFi does not prevent hallucination. Grounding, source quality, retrieval quality, model behavior, and human review still matter.

What SAFi adds is a governance layer that makes the agent's behavior more reviewable. It preserves the relationship between the source material, the generated response, the evaluation, and the final policy decision.

## Try it yourself

The fastest way to evaluate this claim is to run the system and inspect what happens.

Try the live SAFi demo: [SAFi Live Demo](https://safi.selfalignmentframework.com)

Ask the Steward a specific question about the Self-Alignment Framework. Then compare its response with the framework documentation.

For a deeper evaluation, clone the repository:

github.com/jnamaya/SAFi

Read the RAG implementation, the knowledge-base files, the policy configuration, and the audit output. Test questions that should succeed, questions that should return no evidence, short follow-ups, and prompts that invite unsupported conclusions.

The useful question is not whether SAFi ever fails.

The useful question is:

> Can you see what it was given, what it produced, how that result was judged, and what policy did next?

That is the difference between an AI system that can look things up and one whose use of retrieved information can be examined and governed.
