# SAFi Product Roadmap

Planned enhancements for upcoming SAFi releases.

---

## Planned Features

### 1. Productivity Hub (Control Panel)
**Goal:** Complement the **Audit Hub** (built for Legal, Compliance, and Risk) with an executive/IT ROI view showing concrete output and agent performance for IT Directors, Managing Partners, and CFOs.

**Placement:** Top-level tab in **Control Panel**, alongside **Audit Hub**.

**Core Metrics (derived from existing `governance_records`, `llm_usage`, and `conversations` tables — zero extra runtime overhead):**
- **Work Completed by Agent:** Tasks/sessions completed and governed tool actions executed (`bash`, `edit`, `write`, `sys-exec`) broken down across SysAdmin, Security Engineer, Software Engineer, and custom org agents.
- **Agent Performance:** First-pass approval rate, average Spirit alignment score, drift stability, tool execution success rate, and average response/Conscience audit latency per agent.
- **Estimated Hours Saved & ROI:** Transparent, configurable estimate (with org-editable IT hourly rate) summarizing time saved per week/month, exportable as a 1-page PDF/CSV executive summary.
- **Cloud Cost Avoided:** Total local tokens processed on the SAFi Appliance compared against equivalent cloud LLM API / cloud Copilot SCU spend.

**Scope & Isolation:**
- Strictly scoped per `org_id` (same RBAC observer roles as Audit Hub: `admin`, `editor`, `auditor`).
- Supports the same date-range filters (`7d`, `30d`, custom inclusive `from`/`to`) and per-agent/per-user filtering.
