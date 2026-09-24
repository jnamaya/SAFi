---
title: How a RunSAFi Engagement Works
slug: how-it-works
tags: ["runsafi", "engagement", "deployment", "operations"]
summary: How RunSAFi engagements work: deployment, setup and configuration, SSO integration, MCP server configuration, custom agent development, backups and disaster recovery, training and handoff. Plus what the customer does: define policies, bring their own keys, provision infrastructure, design approval workflows, control RunSAFi's access, and manage internal communications.
version: 1.0
---

# How a RunSAFi Engagement Works

RunSAFi deploys and configures the governed agents for the customer's use case. Once live, RunSAFi handles all ongoing maintenance and updates so the agents stay secure and current without adding to the customer team's workload.

## What we do

- **Deployment.** Install a published, integrity-verified SAFi release onto a Linux machine directly in the customer's environment.
- **Setup & Configuration.** Secure the deployment at the customer's own domain over HTTPS and perform the initial configuration with default agents.
- **SSO Integration.** Work with the customer's IT team or MSP to integrate their identity provider, restrict access to valid company directories, and enforce MFA.
- **MCP Server Configuration.** Install and configure MCP servers to securely grant the agents access to specific internal tools.
- **Custom Agent Development.** Build specialized, strictly governed agents tailored to the customer's specific business use cases and workflows.
- **Backups & Disaster Recovery.** Manage routine backups, execute tested restores, and provide DR/BCP documentation aligned with the customer's organizational policies.
- **Training & Handoff.** Train the customer's IT team on the system architecture so they can confidently take over the operator role whenever they are ready.

## What you do

- **Define the Policies.** The customer provides the charter and business-unit policies that govern the agents' behavior.
- **Bring Your Own Keys.** The customer secures the API keys directly from their chosen AI provider, ensuring their enterprise agreement guarantees their data will not be used for model training.
- **Provision the Infrastructure.** The customer provides the environment (a Linux VM, bare metal server, or cloud instance) sized to our hardware specifications.
- **Design Approval Workflows.** The customer determines the internal chain of command for approving new policies, editing tool access, and authorizing agent capabilities.
- **Control Our Access.** The customer issues, audits, and restricts the administrative access RunSAFi needs to maintain the system, which can be revoked at any time.
- **Manage Internal Communications.** The customer's internal team handles organizational rollouts, training announcements, and user adoption.

## Corporate policy and compliance posture

SAFi enforces the customer's corporate policies in real time, preventing unauthorized actions before they happen, and backs every decision with an immutable audit trail. Compliance depends on the deployment, configuration, contracts, and operating procedures.