# SAFi License & Governance Agreement

## GNU Affero General Public License v3.0 (AGPL-3.0) with Special Organization Exception

This document establishes the official licensing, structural boundaries, and future governance roadmap for the Self-Alignment Framework Interface (SAFi). It is designed to protect the deterministic architecture of the core engine from proprietary capture, while granting implementing organizations full sovereignty over their specific configurations, policies, and integrations.

> **Note on the SAF framework license:** The Self-Alignment Framework (SAF), the philosophical and cognitive design vocabulary underlying SAFi, is licensed separately for free use with attribution. This document governs only the SAFi software implementation.

---

## I. Base License Declaration

The core architecture of SAFi is licensed under the GNU Affero General Public License, version 3.0 (AGPL-3.0), copyright (c) 2025 Nelson Amaya.

Under this license, any entity that modifies the core source code and makes it available over a network (e.g., as a cloud-hosted service, API, or SaaS product) must make their modified source code publicly available under the same license.

The full text of the AGPL-3.0 is included in the `LICENSE` file or available at https://www.gnu.org/licenses/agpl-3.0.en.html.

---

## II. The Core Loop (The Invariants)

The strict copyleft provisions of the AGPL-3.0 apply completely and universally to the closed-loop structural files that define the agency architecture. These files are generic invariants designed to function across any installation. They include:

- **The Orchestrator** (`orchestrator.py`): The central nervous system and routing logic that enforces the strict sequence and isolation of the faculties.
- **Phase 0**: System initialization and state preparation.
- **Values (Synderesis)**: The foundational Values and Standard repository.
- **Intellect**: The Proposal and Drafting faculty.
- **Will**: The deterministic Execution and Gate faculty.
- **Conscience**: The Evaluation and Judgment faculty.
- **Spirit**: The Temporal Habitus and Drift Monitoring faculty.
- **The Core Database Schema**: The structural blueprints, migration files, and table architectures that define how data is stored, specifically the hash-chained audit ledgers and the temporal logs. Modifying the structure of how the system records its actions compromises the integrity and auditability of the engine.
- **Role-Based Access Control** (`rbac.py`): The role rules that determine which people may approve, edit, audit, or operate. Role assignment is organization data and remains a Section III variable. The meaning of each role is an invariant, and weakening who may sign off on what is a Core Loop modification.

The Core Loop also includes the enforcement content and mechanisms that feed these components: the shipped threat-signature intelligence that Phase 0 scans against, the faculty prompt templates that define how the Intellect drafts and the Conscience audits, the plugin registry that dispatches organization plugins, and the runtime attestation module that verifies the Core Loop at startup and stamps its fingerprint into every governance record. The registrations an organization adds through the plugin registry are Section III variables. The dispatch mechanism itself is core. Organizations customize on top of this layer through Section III variables such as per-agent blacklists, worldviews, and policies. The shipped floor itself is core.

In security-engineering terms, this section defines SAFi's Trusted Computing Base: the set of components a governance claim depends on. A defect inside the set can violate the policy. A defect outside it cannot. The authoritative file-level enumeration is the integrity manifest (`scripts/core_integrity_manifest.json`), maintained by `scripts/verify_integrity.py` and enforced in CI.

Modifying these files alters the fundamental philosophical and deterministic mechanics of the engine. If an organization modifies these core files for network deployment, those modifications must be open-sourced.

---

## III. The SAFi Organization Exception (The Variables)

To ensure organizations can securely deploy SAFi in highly regulated and private environments, Nelson Amaya, as copyright holder, grants a special exception to the AGPL-3.0 under Section 7 of that license.

As a special exception, you are granted permission to link, integrate, and run the SAFi core engine alongside the following private, organization-specific components without the AGPL-3.0 requiring you to open-source them:

- **Charter and Policy (Configuration Data)**: Organizations may add, modify, and delete internal policies, rules, and value rubrics as they please. This data serves as configuration and belongs 100% to the implementing organization.
- **Tools, Knowledge Bases, and Plugins**: Organizations possess total freedom to add, edit, or remove custom tools, knowledge bases, and plugins. These are organization-dependent, allowing complete customization of the SAFi environment to meet specific needs.
- **Branding and Interface**: Organizations can fully brand their SAFi installation as they see fit, including customizing colors, fonts, logos, and utilizing custom deployment URLs.
- **Authentication Infrastructure**: Any authentication setup, identity management, or network security configurations specific to the organization remain completely private.
- **Help Files**: SAFi includes internal help documentation. Organizations may customize these files for their staff or delete them entirely.
- **Database Content and Infrastructure**: The actual data stored within the database, including runtime logs, audit trails, user data, policy records, and memory, is the strict, private property of the organization. The infrastructure choices (e.g., database engines, hosting environments, and connection configurations) are organization-dependent and exempt from copyleft requirements.

### Formal Additional Permission Statement

The following additional permission is granted under Section 7 of the AGPL-3.0 and may be included in source file headers:

> Additional permission under GNU AGPL version 3, section 7.
>
> If you convey a covered work that includes SAFi by linking or combining it with organization-specific components (including but not limited to: charter and policy configuration data, custom tools, knowledge bases, plugins, branding and interface materials, authentication infrastructure, help documentation, and database content and infrastructure), the copyright holder of SAFi grants you additional permission to convey the resulting work. The source code for the organization-specific components listed above need not be made available under the terms of AGPL-3.0, provided that:
>
> (a) the core loop files identified in Section II of this document are either left unmodified, or, if modified for network deployment, are published under AGPL-3.0 as required; and
>
> (b) the organization-specific components remain clearly separable from the SAFi core engine.

---

## IV. Trademark Policy

This section is governed by trademark law and the SAFi project's trademark policy. It is separate from the copyright license granted under AGPL-3.0 above and does not modify or expand any copyright obligations.

If an organization modifies the Core Loop files (Section II) and wishes to continue using the "SAFi" name or claim they are running an authentic SAFi deployment rather than an independent fork, they must strictly adhere to the following process:

1. The modifying organization must execute the integrity check, `scripts/verify_integrity.py`, which ships with every SAFi release (including inside the container image). It recomputes a SHA-256 hash of every Core Loop file, compares the result against the release manifest (`scripts/core_integrity_manifest.json`), and checks the structural invariants: no deterministic faculty reaches a model, and the staged governance sequence is intact. The check reports a single core-loop fingerprint that deployments may cite as evidence of an unmodified core.
2. If the integrity check reports modifications, the organization must commit and submit those changes publicly for formal review.
3. Changes must be formally accepted by the SAFi project maintainers before the organization can legitimately claim they are using SAFi.

Organizations that modify the Core Loop files without following this process must rebrand their deployment and may not represent it as SAFi.

---

## V. Future Roadmap: The SAF Institute

The Self-Alignment Framework was built to codify the classical philosophical invariants of moral agency into deterministic software. To ensure that the core enforcement architecture never drifts into architectural compromises, the long-term governance of the core loop will transition to The SAF Institute.

**The Role of The SAF Institute:**

The SAF Institute will serve as the official standards body and guardian of the closed-loop architecture. Its mandate includes:

- **Architectural Guardianship**: Evaluating proposed modifications to the core framework, ensuring that the structural separation of faculties (Intellect, Will, Conscience) is never collapsed or bypassed.
- **Integrity Verification**: Maintaining the integrity manifest and `scripts/verify_integrity.py`, and cryptographically verifying that enterprise deployments maintain the core architecture and the deterministic gates on which auditability depends.
- **Philosophical and Technical Alignment**: Acting as the bridge between classical epistemology, operational governance, and modern agentic systems, ensuring that SAFi remains a trusted open standard for verifiable, justified execution in agentic AI.