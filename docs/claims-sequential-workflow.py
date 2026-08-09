#!/usr/bin/env python3
"""
Challenge 3: Sequential Claims Processing Workflow
Using Microsoft Agent Framework Functional Workflow API.

Step 1 — Claims Intake Agent      : Extract and structure claim details
Step 2 — Claims Intelligence Agent: Policy match and coverage decision

Install:
    pip install agent-framework azure-identity
"""

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv


def _find_repo_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / ".env").exists():
            return parent
    return Path(__file__).resolve().parents[2]


load_dotenv(_find_repo_root() / ".env")

FOUNDRY_PROJECT_ENDPOINT = os.environ.get("FOUNDRY_PROJECT_ENDPOINT", "")
FOUNDRY_MODEL = os.environ.get(
    "FOUNDRY_MODEL", os.environ.get("MODEL_DEPLOYMENT_NAME", "gpt-5.4")
)
HUMAN_REVIEW_CONFIDENCE_THRESHOLD = float(
    os.environ.get("HUMAN_REVIEW_CONFIDENCE_THRESHOLD", "0.9")
)

INTAKE_INSTRUCTIONS = (
    "You are the Claims Intake Agent for ClaimSight Insurance. "
    "When given claim details (policy number, claim amount, damage description, "
    "vehicle information, and incident date), structure them into a clean intake report.\n\n"
    "Return a JSON object with:\n"
    "- claim_id\n"
    "- policy_number\n"
    "- incident_date\n"
    "- claim_type (inferred from damage: collision, comprehensive, or liability)\n"
    "- claim_amount\n"
    "- damage_description\n"
    "- vehicle_info\n"
    "- extraction_confidence (float 0.0–1.0)\n"
    "- status: 'intake_complete'\n\n"
    "Return only the JSON object with no additional commentary."
)

INTELLIGENCE_INSTRUCTIONS = (
    "You are the Claims Intelligence Agent for ClaimSight Insurance. "
    "You receive a structured intake report and perform coverage validation.\n\n"
    "Policy rules:\n\n"
    "LIAB-AUTO-001 — Liability Only\n"
    "  Covers: third_party_liability ($100,000 limit, $500 deductible)\n"
    "  Excludes: own_vehicle_damage, collision, comprehensive\n\n"
    "COMM-AUTO-001 — Commercial Auto\n"
    "  Covers: collision ($50,000 / $1,000 deductible), "
    "comprehensive ($25,000 / $500), liability ($150,000 / $250)\n\n"
    "COMP-AUTO-001 — Comprehensive Auto\n"
    "  Covers: collision ($35,000 / $750 deductible), "
    "comprehensive ($15,000 / $250), liability ($100,000 / $100)\n\n"
    "Return a JSON object with: is_covered, coverage_percentage, applicable_deductible, "
    "approved_amount, exclusions_matched, reasoning, risk_flags, confidence_score, "
    "requires_escalation, escalation_reason, and status (APPROVED / DENIED / ESCALATED).\n\n"
    "Return only the JSON object with no additional commentary."
)


def _parse_json_object(value: str) -> dict:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Claims Intelligence Agent returned invalid JSON.") from exc

    if not isinstance(parsed, dict):
        raise RuntimeError("Claims Intelligence Agent returned a non-object JSON payload.")

    return parsed


def _requires_human_review(decision: dict) -> bool:
    confidence_score = float(decision.get("confidence_score", 1.0) or 0.0)
    return bool(decision.get("requires_escalation")) or confidence_score < HUMAN_REVIEW_CONFIDENCE_THRESHOLD


async def run_claims_pipeline(claim_details: str) -> str:
    """
    Build the sequential @workflow using Microsoft Agent Framework.

    @step ensures run_intake completes before run_intelligence is called,
    and caches each result across HITL resumes and checkpoint restores.
    """
    from agent_framework import step, workflow
    from agent_framework.foundry import FoundryChatClient
    from azure.identity.aio import DefaultAzureCredential

    async with DefaultAzureCredential() as credential:
        client = FoundryChatClient(
            credential=credential,
            project_endpoint=FOUNDRY_PROJECT_ENDPOINT,
            model=FOUNDRY_MODEL,
        )

        intake_agent = client.as_agent(
            name="claims-intake-agent",
            instructions=INTAKE_INSTRUCTIONS,
        )

        intelligence_agent = client.as_agent(
            name="claims-intelligence-agent",
            instructions=INTELLIGENCE_INSTRUCTIONS,
        )

        # ------------------------------------------------------------------
        # Step functions — results are cached by @step on resume/checkpoint
        # ------------------------------------------------------------------

        @step
        async def run_intake(details: str) -> str:
            print("  [Step 1] Claims Intake Agent running...")
            result = await intake_agent.run(details)
            print("  [Step 1] Intake complete.")
            return result.text

        @step
        async def run_intelligence(intake_report: str) -> str:
            print("  [Step 2] Claims Intelligence Agent running...")
            result = await intelligence_agent.run(
                f"Here is the intake report:\n\n{intake_report}\n\n"
                "Validate coverage and return the decision JSON."
            )
            print("  [Step 2] Decision complete.")
            return result.text

        @step
        async def run_human_review(decision_json: str) -> str:
            decision = _parse_json_object(decision_json)
            confidence_score = float(decision.get("confidence_score", 0.0) or 0.0)
            status = decision.get("status", "UNKNOWN")

            print("  [Step 3] Human review requested...")
            print(
                f"    Decision status: {status} | confidence: {confidence_score:.2f} | "
                f"threshold: {HUMAN_REVIEW_CONFIDENCE_THRESHOLD:.2f}"
            )

            if not sys.stdin.isatty():
                raise RuntimeError(
                    "Human review is required, but the workflow is running in a non-interactive terminal."
                )

            prompt = (
                "    Confirm decision? Type 'approve' to accept, 'escalate' to send for manual review, "
                "or 'deny' to override the decision: "
            )
            reviewer_action = (await asyncio.to_thread(input, prompt)).strip().lower()

            if reviewer_action in {"approve", "a", "yes", "y"}:
                human_status = "confirmed"
                human_override = None
            elif reviewer_action in {"escalate", "e", "review", "manual"}:
                human_status = "escalated"
                human_override = "ESCALATED"
            elif reviewer_action in {"deny", "d", "reject", "r"}:
                human_status = "overridden"
                human_override = "DENIED"
            else:
                raise RuntimeError("Human review response must be approve, escalate, or deny.")

            decision["human_review"] = {
                "required": True,
                "status": human_status,
                "reviewer_action": reviewer_action,
                "confidence_threshold": HUMAN_REVIEW_CONFIDENCE_THRESHOLD,
            }

            if human_override is not None:
                decision["status"] = human_override
                decision["requires_escalation"] = human_override == "ESCALATED"
                decision["human_review"]["override_status"] = human_override

            print("  [Step 3] Human review complete.")
            return json.dumps(decision, indent=2)

        # ------------------------------------------------------------------
        # Sequential workflow — plain async Python with @workflow decorator
        # ------------------------------------------------------------------

        @workflow(
            name="claims-sequential-workflow",
            description="Claims Intake, Intelligence, and conditional human review coverage decision",
        )
        async def claims_pipeline(details: str) -> str:
            intake_report = await run_intake(details)              # Step 1
            decision_json = await run_intelligence(intake_report)  # Step 2
            decision = _parse_json_object(decision_json)

            if _requires_human_review(decision):
                decision_json = await run_human_review(decision_json)  # Step 3 (conditional)

            return decision_json

        result = await claims_pipeline.run(claim_details)
        return result.text


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Sequential claims workflow — Microsoft Agent Framework"
    )
    parser.add_argument(
        "--policy", default="COMP-AUTO-001",
        help="Policy number (default: COMP-AUTO-001)",
    )
    parser.add_argument(
        "--claim-id", default="CLM-2026-001",
        help="Claim identifier (default: CLM-2026-001)",
    )
    parser.add_argument(
        "--amount", type=float, default=15000.0,
        help="Claimed amount in USD (default: 15000.0)",
    )
    parser.add_argument(
        "--damage", default="Front-end collision damage. Airbags deployed.",
        help="Damage description",
    )
    parser.add_argument(
        "--vehicle", default="2022 Toyota Camry",
        help="Vehicle information",
    )
    parser.add_argument(
        "--date", default="2026-07-15",
        help="Incident date (YYYY-MM-DD)",
    )
    args = parser.parse_args()

    if not FOUNDRY_PROJECT_ENDPOINT:
        print("FOUNDRY_PROJECT_ENDPOINT is not set. Complete challenge 0 first.")
        sys.exit(1)

    claim_details = (
        "Process this insurance claim. Work from the details below.\n\n"
        f"Claim ID      : {args.claim_id}\n"
        f"Policy number : {args.policy}\n"
        f"Claim amount  : ${args.amount:,.2f}\n"
        f"Damage        : {args.damage}\n"
        f"Vehicle       : {args.vehicle}\n"
        f"Incident date : {args.date}\n"
    )

    print(f"\nClaims Sequential Workflow (Microsoft Agent Framework)")
    print(f"  Endpoint : {FOUNDRY_PROJECT_ENDPOINT}")
    print(f"  Model    : {FOUNDRY_MODEL}")
    print(f"  Policy   : {args.policy}")
    print(f"  Claim ID : {args.claim_id}\n")

    output = asyncio.run(run_claims_pipeline(claim_details))

    print("\n--- Final Decision ---")
    print(output)

    print("\n" + "=" * 60)
    print("CHALLENGE 3 COMPLETE")
    print("=" * 60)
    print("  Step 1 — Claims Intake Agent       ✓")
    print("  Step 2 — Claims Intelligence Agent ✓")
    print("  Step 3 — Human review (conditional) ✓")
    print("  Sequential @workflow               ✓")


if __name__ == "__main__":
    main()