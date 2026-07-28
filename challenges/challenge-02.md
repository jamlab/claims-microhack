# Challenge 2 - Build the Claims Intelligence Agent

**Expected Duration:** 30 minutes

## Overview
In this challenge, you will build the Claims Intelligence Agent — the core decision-making component of the claims processing pipeline.

Like Challenge 1, this agent is built in two steps: first you create the agent with the Azure AI Foundry SDK, then you give it its enterprise need — real policy documents from your Storage account's `policies` container, instead of hardcoded mock data.

## From Mock Policies to Real Policy Documents

Enterprise claims adjudication starts with the model, but it only becomes useful when the model can read the same policy documents your organization uses. In this challenge, the policy-extraction agent is the generic reasoning component, and the Storage account `policies` container is the enterprise grounding layer that turns it into a real Claims Intelligence Agent.

In short: **policy text → policy-extraction agent → cached structured policy info → coverage decision agent**. The policy documents still hold the source-of-truth content; the agent is the layer that turns those documents into a typed policy object the adjudicator can reason over.

The Claims Intelligence Agent combines Policy Matching and Coverage Validation into a single orchestrated flow:

1. Retrieve the policy document that matches the claim's policy number from the Storage account and cache it.
2. Extract structured policy fields (coverage types, limits, deductibles, exclusions) from the raw policy document using a dedicated Foundry agent.
3. Run multi-factor coverage analysis using an LLM-backed adjudicator.
4. Apply the compliance rules engine to identify exclusions and limits.
5. Score how consistent the reported crash details are with the policy on a 1-100 scale, driving the approve/deny/escalate outcome.
6. Escalate edge cases with structured reasoning and severity levels.
7. Emit a detailed coverage decision with confidence scores, a consistency score, and a full audit trail.

## Prerequisites

- Complete [Challenge 1](./challenge-01.md) to produce an intake JSON artifact.
- Ensure `AI_FOUNDRY_PROJECT_ENDPOINT` and `MODEL_DEPLOYMENT_NAME` are set in your `.env`.
- Ensure `AZURE_STORAGE_CONNECTION_STRING` and `AZURE_POLICIES_CONTAINER_NAME` are set in your `.env`, and that `deploy-lab.ps1` has uploaded the files under [`data/policies/`](../data/policies/) to that container.
- The `enterprise_models.py` module must be present alongside the agent script.


## Task 1: Create the policy-extraction agent with the Foundry SDK

Raw policy documents are unstructured markdown — the adjudicator needs structured fields (coverage types, limits, deductibles, exclusions). `docs/claims-intelligence-agent.py` creates a dedicated `policy-extraction-agent` for this using the same SDK pattern as Challenge 1:

```python
def _ensure_policy_extraction_agent(self) -> None:
    try:
        self.client.agents.get(POLICY_EXTRACTION_AGENT_NAME)
    except ResourceNotFoundError:
        definition = PromptAgentDefinition(model=self.model, instructions=POLICY_EXTRACTION_INSTRUCTIONS)
        self.client.agents.create_version(agent_name=POLICY_EXTRACTION_AGENT_NAME, definition=definition)
```

Key points:

- This mirrors Challenge 1's `_ensure_foundry_agent()`: check whether the agent already exists via `client.agents.get(...)`, and only call `create_version(...)` if it doesn't.
- `POLICY_EXTRACTION_INSTRUCTIONS` instructs the model to return strict JSON matching the `PolicyInfo` shape (`policy_type`, `coverage_types`, `limits`, `deductibles`, `exclusions`) from whatever raw policy text it's given.
- This agent has no attached tools — its only job is structured extraction from text it's handed directly, which is what makes Task 3's blob retrieval its enterprise need rather than a built-in capability.

## Task 2: Give the policy-extraction agent its enterprise need — Storage Account policy files

With the extraction agent in place, connect it to your real policy documents instead of hardcoded mock data:

```python
def _load_policy_documents(self) -> dict[str, str]:
    container_client = self._get_policies_container_client()
    documents: dict[str, str] = {}
    for blob in container_client.list_blobs():
        text = container_client.download_blob(blob.name).readall().decode("utf-8")
        match = POLICY_CODE_PATTERN.search(text)
        if match:
            documents[match.group(1)] = text
    return documents
```

Key points:

- `_get_policies_container_client()` connects to the Storage account via `AZURE_STORAGE_CONNECTION_STRING` and opens the `policies` container — the same container `deploy-lab.ps1` uploads [`data/policies/`](../data/policies/) into.
- Each blob is downloaded once and cached in `self.policy_documents_cache`, keyed by the policy's `**Policy Code:**` field (matched via `POLICY_CODE_PATTERN`), so repeated lookups for the same run don't re-download every file.
- `_get_policy(policy_number)` looks up the matching raw text, then calls `_extract_policy_info()` — which runs the `policy-extraction-agent` from Task 2 against that raw text — to build a real `PolicyInfo` object with real limits, deductibles, and exclusions.

This replaces what used to be a hardcoded `MOCK_POLICIES` dictionary: coverage decisions are now grounded in the actual policy documents your organization maintains, not placeholder numbers.

## Task 3: Run the Claims Intelligence Agent

Feed the intake artifact produced by the Claims Intake Agent in [Challenge 1](./challenge-01.md) straight into the Intelligence Agent:

```bash
cd docs
python claims-intelligence-agent.py ../data/claims/crash1/derived/statements/crash1_front.intake.json
```

The intake artifact's `policy_number` is `LIAB-AUTO-001` (Liability Only), so this run exercises the exclusion path: a liability-only policy denying a collision claim, with `own_vehicle_damage` or `collision` listed in `exclusions_matched`.

Optional — override the policy number to test the approval path:

```bash
python claims-intelligence-agent.py ../data/claims/crash1/derived/statements/crash1_front.intake.json --policy-number COMP-AUTO-001
```

Optional — override the claim amount to test the escalation path:

```bash
python claims-intelligence-agent.py ../data/claims/crash1/derived/statements/crash1_front.intake.json --policy-number LIAB-AUTO-001 --claim-amount 95000
```

When the adjudicator returns `"requires_escalation": true`, confirm that `state.errors` contains an `ESCALATION_REQUIRED` entry with severity `WARN`.
