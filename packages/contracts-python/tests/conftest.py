"""Contract test fixtures."""

from pathlib import Path

import pytest
from changeops_contracts import RemediationPlan

GOLDEN_PLAN_PATH = (
    Path(__file__).resolve().parents[2] / "contracts-fixtures" / "remediation-plan.json"
)


@pytest.fixture
def remediation_plan() -> RemediationPlan:
    return RemediationPlan.model_validate_json(GOLDEN_PLAN_PATH.read_text(encoding="utf-8"))
