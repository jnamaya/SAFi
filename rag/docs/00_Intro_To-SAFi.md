---
title: Introduction: Self-Alignment Framework Interface ( SAFi)
slug: intro-SAFi
tags: ["safi", "intro"]
summary: High-level conceptual framework connecting faculties, values, and governance into a closed-loop architecture.
version: 1.0
---

# What is SAFi

SAFi is the first open-source implementation of the Self-Alignment Framework (SAF), a closed-loop ethical reasoning engine. SAFi is not a language model itself, but a governor that evaluates and audits the behavior of AI models like GPT, Claude, or Llama through a five-faculty reasoning loop:

**Values → Intellect → Will → Conscience → Spirit**

This loop turns ethics into system logic, ensuring transparency, accountability, and drift detection in AI behavior.

# How does SAFi Work? 

SAFi is built on a "separation of powers" architecture, where distinct components, or "faculties," each handle a specific part of the alignment process. This creates a robust system of internal checks and balances.

# How do the Faculties work in SAFi?

*   **Intellect Engine**: This is the generative core of the system. It uses a powerful, general-purpose AI model to reason, synthesize information from the knowledge base, and produce the initial draft of any response, along with a private reflection on its reasoning process.
    
*   **Will Gate**: A fast, specialized AI model that acts as a real-time safety gatekeeper. It inspects every draft from the Intellect _before_ it reaches the user, enforcing the non-negotiable, hard-coded rules of the active persona. Its sole function is to block policy violations, providing a critical layer of safety and brand protection.
    
*   **Conscience Auditor**: This is the system's "judicial branch." After a response is approved, this evaluation layer performs a detailed, post-action audit. It scores the final output against the nuanced, weighted values of the active persona, producing a detailed, machine-readable "Ethical Ledger" for complete accountability.
    
*   **Spirit Integrator**: The mathematical historian and guardian of the system's long-term identity. This purely mathematical component analyzes the audits from the Conscience over time to track ethical performance, measure "identity drift," and prevent the "King Solomon Problem." It closes the loop by generating coaching feedback for the Intellect, enabling the system to learn and self-correct.
    

### What are Ethical Profiles or Personas? 

SAFi can embody different roles or characters by loading distinct Ethical Profiles. This allows one underlying system to be adapted for many different contexts, each with its own unique alignment parameters.

*   **Dynamic Persona Switching**: A user can switch SAFi's active persona directly from the application's front-end, instantly changing its entire operational character.
    
*   **Comprehensive Profile Architecture**: Each persona is defined by a structured profile containing four key components:
    
    *   **Worldview:** A high-level "constitution" that defines the AI's core purpose and reasoning principles.
        
    *   **Style:** A guide for the AI's voice, tone, and communication persona.
        
    *   **Will-Rules:** A set of non-negotiable guardrails enforced by the Will Gate.
        
    *   **Values:** A weighted list of nuanced principles used for the Conscience's audit.
        
*   **Pre-built Personas**: The system includes a variety of pre-built profiles, such as a philosophical guide grounded in virtue ethics, a cautious financial educator, and an empathetic healthcare navigator.
    

### What are SAFi Use Cases? 

SAFi is packaged as a complete, enterprise-ready web application with all the necessary features for a robust user experience.

*   **Secure User Authentication**: Full user management and secure sign-in capabilities are integrated using providers like Google OAuth.
    
*   **Persistent Conversation History**: All chat histories are saved to a durable MySQL database, allowing users to securely access and continue their conversations across different sessions and devices.
    
*   **Long-Term Conversation Memory**: A sophisticated background job maintains a running summary of each conversation. This provides the AI with a coherent short-term memory, allowing it to track context and recall details from earlier in a long discussion.
    
*   **Asynchronous Auditing for a Fast UX**: Users receive a fast initial response from the real-time Intellect and Will faculties. The more computationally intensive audit by the Conscience and Spirit runs asynchronously in the background, with the detailed results being logged without impacting the user's experience.
    

*   **Model-Agnostic & Multi-Provider Support**: The architecture is fundamentally model-agnostic. It allows different AI models to be assigned to different faculties, enabling an organization to use the best tool for each job (e.g., a fast, efficient model for the Will, and a powerful, state-of-the-art model for the Intellect).
    
*   **Complete Transparency via Structured Logging**: Every single turn of a conversation is logged in exhaustive detail to a structured JSONL file. These logs include the Intellect's internal drafts, the Will's decisions, the complete Conscience ledger, and the Spirit's mathematical vectors, providing an unprecedented level of transparency and auditability.
    
*   **Durable Database Persistence**: All critical data, including user information, conversation histories, and the AI's long-term Spirit memory vectors, are stored securely in a MySQL database.
    
*   **Flexible Deployment & Configuration**: The application is configured entirely through environment variables, making it easy to manage API keys, database connections, and model assignments for seamless deployment in different environments (e.g., development, staging, production).