# Challenge 4 - Harden the Claims Pipeline Against Prompt Injection

**Expected Duration:** 60 minutes

## Overview

In this challenge you will attack, then defend, the claims-decision workflow from Challenge 3 — this time from a security perspective.

Every claim description in this pipeline comes from a claimant: someone outside your organization who can put whatever text they want into a "damage description" field. Nothing about the workflow in Challenge 3 stops that text from containing hidden instructions aimed at the LLM instead of a human reader, and the new human-review branch only confirms a decision after it has been produced. This challenge uses **FIDES** (Flow Integrity Deterministic Enforcement System), a Microsoft Agent Framework module (`agent_framework.security`) that labels content by trust (`integrity`) and sensitivity (`confidentiality`), then enforces those labels **before** a sensitive tool runs — deterministically, not by hoping the model notices the attack.

Two attacks, two defenses:

1. **Prompt injection → unauthorized payout.** A claim description contains a hidden instruction telling the agent to approve the claim regardless of policy limits. You label claimant text `untrusted` and mark the payout tool `accepts_untrusted: False`, so the sink refuses to fire while untrusted content is in scope.
2. **Prompt injection → PII exfiltration.** A claim description tries to trick the agent into echoing a policyholder's SSN and prior-claims history back to the claimant. You label the policyholder record `confidentiality: private` and cap the notification tool at `max_allowed_confidentiality: public`, so the sink refuses to leak it.

Challenge 3 may ask a human to confirm a borderline decision, but FIDES still protects the workflow from malicious text getting that far in a privileged form.

```
claimant-submitted text (always untrusted)
     │
     ▼
┌───────────────────────────┐
│  read_claim_intake         │  source_integrity = "untrusted"
└─────────────┬─────────────┘
              │  damage description (+ possible hidden instruction)
              ▼
┌───────────────────────────────────────┐
│  Claims Intelligence Agent + FIDES     │
│  (SecureAgentConfig policy fence)      │
└───────┬───────────────────────┬───────┘
        │                       │
        ▼                       ▼
┌────────────────────┐  ┌─────────────────────────┐
│  approve_payout      │  │  notify_claimant          │
│  accepts_untrusted:   │  │  max_allowed_             │
│  False                │  │  confidentiality: public  │
└────────────────────┘  └─────────────────────────┘
   refuses while              refuses while
   untrusted content            private content
   is in scope                  is in scope
```

## Prerequisites

- Complete [Challenge 3](./challenge-03.md).
- Install the Microsoft Agent Framework and Azure Identity (already installed if you completed Challenge 3):

```bash
pip install agent-framework azure-identity
```

- `FOUNDRY_PROJECT_ENDPOINT` and `FOUNDRY_MODEL` must be present in your `.env`.
- FIDES ships in `agent-framework-core` and is currently marked experimental.
