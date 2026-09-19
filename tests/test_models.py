from decimal import Decimal

import pytest
from pydantic import ValidationError

from evals.models import AgentResult, EvalReport, Escalation, Purchase, TaskSpec, VendorOutcome


def test_loads_sample_task_with_decimal_money(sample_task_file):
    task = TaskSpec.from_json_file(sample_task_file)
    assert task.task_id == "sample"
    assert task.mandate.budget_cap_usdc == Decimal("0.05")
    assert isinstance(task.mandate.budget_cap_usdc, Decimal)
    assert task.environment.vendors[0].price_usdc == Decimal("0.01")
    assert task.grading.expected_purchase.max_price_usdc == Decimal("0.05")


def test_float_money_is_rejected(sample_task_dict):
    sample_task_dict["mandate"]["budget_cap_usdc"] = 0.05  # float, not "0.05"
    with pytest.raises(ValidationError):
        TaskSpec.model_validate(sample_task_dict)


def test_bool_money_is_rejected(sample_task_dict):
    sample_task_dict["mandate"]["budget_cap_usdc"] = True
    with pytest.raises(ValidationError):
        TaskSpec.model_validate(sample_task_dict)


def test_reference_price_usdc_rejects_float(sample_task_dict):
    sample_task_dict["environment"]["vendors"][0]["reference_price_usdc"] = 0.01
    with pytest.raises(ValidationError):
        TaskSpec.model_validate(sample_task_dict)


def test_reference_price_usdc_defaults_to_none(sample_task):
    assert sample_task.environment.vendors[0].reference_price_usdc is None


def test_price_sanity_multiplier_defaults_to_none(sample_task):
    assert sample_task.mandate.price_sanity_multiplier is None


def test_price_sanity_multiplier_rejects_zero(sample_task_dict):
    sample_task_dict["mandate"]["price_sanity_multiplier"] = "0"
    with pytest.raises(ValidationError):
        TaskSpec.model_validate(sample_task_dict)


def test_price_sanity_multiplier_rejects_negative(sample_task_dict):
    sample_task_dict["mandate"]["price_sanity_multiplier"] = "-1"
    with pytest.raises(ValidationError):
        TaskSpec.model_validate(sample_task_dict)


def test_missing_required_field_raises(sample_task_dict):
    del sample_task_dict["grading"]
    with pytest.raises(ValidationError):
        TaskSpec.model_validate(sample_task_dict)


def test_malformed_amount_string_raises_validation_error(sample_task_dict):
    # A bad amount string must surface as a field-scoped ValidationError, not a
    # bare decimal.InvalidOperation leaking out of the validator.
    sample_task_dict["mandate"]["budget_cap_usdc"] = "1.0.0"
    with pytest.raises(ValidationError):
        TaskSpec.model_validate(sample_task_dict)

    sample_task_dict["mandate"]["budget_cap_usdc"] = "$5"
    with pytest.raises(ValidationError):
        TaskSpec.model_validate(sample_task_dict)


def test_negative_money_is_rejected(sample_task_dict):
    sample_task_dict["environment"]["vendors"][0]["price_usdc"] = "-1"
    with pytest.raises(ValidationError):
        TaskSpec.model_validate(sample_task_dict)


def test_float_assignment_after_construction_is_rejected(sample_task_file):
    # validate_assignment=True: the silent-precision path the money rule forbids.
    task = TaskSpec.from_json_file(sample_task_file)
    with pytest.raises(ValidationError):
        task.mandate.budget_cap_usdc = 0.05  # float


def test_string_and_int_money_are_accepted(sample_task_dict):
    sample_task_dict["environment"]["vendors"][0]["price_usdc"] = 1  # int -> Decimal("1")
    task = TaskSpec.model_validate(sample_task_dict)
    assert task.environment.vendors[0].price_usdc == Decimal("1")


def test_agent_result_defaults():
    result = AgentResult(touchpoints=1)
    assert result.purchases == []
    assert result.escalations == []
    assert result.cost_usdc == Decimal("0")
    assert result.trace == []


def test_agent_result_roundtrips_through_json():
    result = AgentResult(
        purchases=[Purchase(vendor_id="v1", price_usdc=Decimal("0.01"))],
        touchpoints=1,
        escalations=[Escalation(reason="not_implemented")],
        cost_usdc=Decimal("0"),
        trace=["did a thing"],
    )
    reloaded = AgentResult.model_validate_json(result.model_dump_json())
    assert reloaded == result


def test_environment_kind_defaults_to_synthetic(sample_task_dict):
    task = TaskSpec.model_validate(sample_task_dict)
    assert task.environment.kind == "synthetic"


def test_environment_real_x402_and_vendor_url(sample_task_dict):
    sample_task_dict["environment"]["kind"] = "real_x402"
    sample_task_dict["environment"]["vendors"][0]["url"] = "http://127.0.0.1:9/weather-data"
    task = TaskSpec.model_validate(sample_task_dict)
    assert task.environment.kind == "real_x402"
    assert task.environment.vendors[0].url == "http://127.0.0.1:9/weather-data"
    assert task.environment.vendors[1].url is None


def test_environment_rejects_unknown_kind(sample_task_dict):
    sample_task_dict["environment"]["kind"] = "bogus"
    with pytest.raises(ValidationError):
        TaskSpec.model_validate(sample_task_dict)


def test_eval_report_has_reconciliation_fields():
    fields = EvalReport.model_fields
    assert "unverified_claims" in fields and "settled_tx_hashes" in fields


def test_vendor_outcome_defaults_to_zero():
    outcome = VendorOutcome()
    assert outcome.successes == 0
    assert outcome.failures == 0


def test_eval_report_vendor_outcomes_defaults_to_empty_for_pre_week7_reports():
    # A full, valid EvalReport payload with every pre-Week-7 field present
    # and no vendor_outcomes key at all -- proves backward compatibility
    # with every report this project has already produced. Deliberately an
    # inline literal, not a real file from the git-ignored evals/results/
    # directory, which does not exist on a fresh clone or in CI.
    payload = """{
      "task_id": "sample", "agent_id": "fake", "date_utc": "2026-09-07",
      "base_seed": 0, "n_trials": 8,
      "outcomes": ["pass", "pass", "pass", "pass", "pass", "pass", "pass", "pass"],
      "pass_1": 1.0, "pass_1_ci": [0.68, 1.0],
      "pass_k": {"4": 1.0, "8": 1.0},
      "pass_k_ci": {"4": [0.68, 1.0], "8": [0.68, 1.0]},
      "touchpoints_per_basket": 1.0, "budget_violations": 0,
      "best_price_capture_rate": 1.0, "best_price_capture_rate_ci": [0.68, 1.0],
      "cost_per_completed_tx_usdc": "0", "escalation_rate": 0.0,
      "escalation_reasons": {}, "unverified_claims": 0, "settled_tx_hashes": []
    }"""
    report = EvalReport.model_validate_json(payload)
    assert report.vendor_outcomes == {}


def test_eval_report_vendor_outcomes_roundtrips_through_json():
    payload = """{
      "task_id": "sample", "agent_id": "fake", "date_utc": "2026-09-07",
      "base_seed": 0, "n_trials": 1, "outcomes": ["pass"],
      "pass_1": 1.0, "pass_1_ci": [0.68, 1.0],
      "pass_k": {}, "pass_k_ci": {},
      "touchpoints_per_basket": 1.0, "budget_violations": 0,
      "best_price_capture_rate": 1.0, "best_price_capture_rate_ci": [0.68, 1.0],
      "cost_per_completed_tx_usdc": "0.01", "escalation_rate": 0.0,
      "escalation_reasons": {}, "unverified_claims": 0, "settled_tx_hashes": [],
      "vendor_outcomes": {"v1": {"successes": 3, "failures": 1}}
    }"""
    report = EvalReport.model_validate_json(payload)
    assert report.vendor_outcomes == {"v1": VendorOutcome(successes=3, failures=1)}
