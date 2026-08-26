"""Canonical remediation plan hashing tests."""

from changeops_contracts import RemediationPlan, calculate_plan_hash, canonical_json


def test_same_plan_always_produces_same_hash(remediation_plan: RemediationPlan) -> None:
    round_tripped = RemediationPlan.model_validate_json(remediation_plan.model_dump_json())

    assert canonical_json(remediation_plan) == canonical_json(round_tripped)
    assert calculate_plan_hash(remediation_plan) == calculate_plan_hash(round_tripped)
    assert (
        calculate_plan_hash(remediation_plan)
        == "sha256:e3bb064488ef1b3a05e8170e8ecfea2f90f5957d9dce6f47f81b71b3cbbedce3"
    )


def test_material_plan_change_changes_hash(remediation_plan: RemediationPlan) -> None:
    changed_document = remediation_plan.model_dump(mode="python")
    changed_document["summary"] = "A materially different execution plan."
    changed_plan = RemediationPlan.model_validate(changed_document)

    assert calculate_plan_hash(remediation_plan) != calculate_plan_hash(changed_plan)
