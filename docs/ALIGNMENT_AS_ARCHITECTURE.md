# Alignment as architecture

Hi everyone, I hope you are enjoying the weekend.

More than a year ago, I published a conceptual framework in this subreddit called the Self-Alignment Framework (SAF) that I was working on at the time. While that framework remains the theoretical blueprint guiding my work, today I want to share my progress on implementing the concepts from the framework into machines.

First, let's start by defining: what is "alignment"?

In the context of this framework, Alignment is defined simply: the continuous harmony of a system's actions with its declared values.

I have written extensively on how humans attempt to achieve this state of alignment, drawing heavily from classical philosophy, specifically the cognitive psychology of Saint Thomas Aquinas, combined with modern systems architecture.

If you're interested in the core theory, I have a dedicated website at selfalignmentframework.com and a comprehensive philosophy file in the GitHub repository.

## Moving from Philosophy to Systems Engineering

While humans can deliberate on an action indefinitely, a machine requires a concrete, sequential process.

We do not want an autonomous system spending hours computing the abstract meaning of "honesty," for example; we require deterministic, auditable boundaries.

To bridge this gap, I created the Self-Alignment Framework Interface (SAFi). If SAF is the philosophical framework, SAFi is the concrete engineering implementation.

To achieve this, I mapped the fluid concepts of human faculty psychology into a discrete, sequential loop:

- Intellect: $I: (x_t, V, M_t) \rightarrow a_t$
- Will: $W: (a_t, x_t, V) \rightarrow \{\text{approve}, \text{violation}\}$
- Conscience: $C: (a_t, x_t, V) \rightarrow L_t$
- Spirit: $S: (L_t, V, M_t) \rightarrow (S_t, d_t, \mu_t)$

(Where $x_t$ is the input context, $V$ is the set of declared values with weights, and $M_t$ is the historical memory state).

Notice that I haven't mentioned LLMs or AI yet. That is because SAFi is an implementation-agnostic cognitive architecture, not an AI model. Its individual functions could be performed by an LLM, a rules engine, a gateway, or even a human reviewer.

## The Architecture Breakdown

### 1. The Intellect

The Intellect is strictly responsible for generating and proposing drafts ($a_t$) to the system. It has no decision-making power and is entirely air-gapped from execution. In our reference implementation, this faculty is powered by an LLM, any powerful model capable of deeply understanding the baseline task context.

### 2. The Will

The Will is entirely deterministic (written in pure Python). It doesn't deliberate or negotiate; it runs strict structural passes (checking syntax, required exclusions, and user invariants). If a check passes, it hands the payload to the Conscience.

### 3. The Conscience

The Conscience acts as the compliance auditor, and the function in the current implementation is also performed by an LLM. It evaluates the structurally valid draft against the policy's weighted Value Set ($V$) using rubrics for each value definition, and generates a score for each value on a continuous scale:

- -1.0 = Absolute Violation / Misaligned
- 0.0 = Neutral / Not Applicable
- 1.0 = Perfect Alignment

### 4. The Spirit

The Spirit faculty acts as the integrator and is pure Python using NumPy. It ingests the Conscience ledger ($L_t$), rescales the continuous scores into a consolidated metric from 1 to 10 ($S_t$), and updates the system's moving average ($\mu_t$) to track behavioral drift ($d_t$).

## The Closed-Loop Feedback & Correction

The architecture maintains alignment through a strict execution circuit:

The Will distinguishes between two kinds of failure here. If the Conscience flags a critical violation (any single value scored at -1.0), the Will catches it and triggers a Reflexion Loop, forcing the Intellect to rewrite the response using targeted coaching notes. If instead the aggregate Spirit score simply falls below the user-defined threshold (e.g., < 5) without any critical violation, the Will does not attempt a rewrite; it routes directly to a governed redirect.

To prevent infinite loops, if a rewritten output fails a second time, the Will halts the thread entirely and routes to a governed redirect.

If the output passes all gates, the data coordinates are saved to the history database, and the clean response is released for Safe Execution.

Every single step of this loop is audited and logged, giving users an immutable trail showing exactly why a machine determined an action was compliant.

You can test the system by going to safi.selfalignmentframework.com. I have intentionally set the Intellect with a very small AI model so the governance system in SAFi can be heavily stress-tested.

I'd love to hear your thoughts on this architecture, specifically on treating AI alignment as an external, closed-loop control system rather than an internal prompt instruction.
