from decimal import Decimal

import pytest
from pydantic import ValidationError

from evals.models import AgentResult, Escalation, Purchase, TaskSpec


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
    from evals.models import EvalReport
    fields = EvalReport.model_fields
    assert "unverified_claims" in fields and "settled_tx_hashes" in fields
