from decimal import Decimal

import pytest

from evals.agents.claude_planner import (
    _Decision,
    _ask_claude,
    _build_prompt,
    _token_cost_usdc,
    run_task,
)
from evals.executor import ExecutedPurchase
from evals.guardrail import VendorNotOffered
from evals.models import Mandate, Purchase, TaskSpec, Vendor


# ---- run_task: pre-filter short-circuit (no LLM call) ---------------------

def test_no_in_policy_vendor_escalates_without_calling_llm(sample_task_dict, monkeypatch):
    # Cap set below every vendor's price -- in_policy_candidates is empty, so
    # run_task must escalate WITHOUT ever calling _ask_claude.
    sample_task_dict["mandate"]["budget_cap_usdc"] = "0.001"
    task = TaskSpec.model_validate(sample_task_dict)

    def _boom(*args, **kwargs):
        raise AssertionError("_ask_claude must not be called with no in-policy candidates")

    monkeypatch.setattr("evals.agents.claude_planner._ask_claude", _boom)

    result = run_task(task, 0, executor=None)
    assert result.purchases == []
    assert result.touchpoints == 2
    assert [e.reason for e in result.escalations] == ["no_in_policy_vendor"]
    assert result.cost_usdc == Decimal("0")


# ---- run_task: LLM decision branching --------------------------------------

class _FakeExecutor:
    def __init__(self, price):
        self._price = price

    def pay(self, target, *, max_amount):
        return ExecutedPurchase(
            vendor_id=target, url=None, amount_paid=self._price,
            pay_to=None, tx_hash=None, verified=True, resource=None)


def test_llm_picks_a_vendor_and_buys_it(sample_task, monkeypatch):
    usage = {"input_tokens": 100, "output_tokens": 20, "total_tokens": 120}

    def _fake_ask(description, mandate, candidates):
        assert description == sample_task.description
        assert [c.vendor_id for c in candidates] == ["v1"]
        return _Decision(vendor_id="v1", escalate=False, reason=None), usage

    monkeypatch.setattr("evals.agents.claude_planner._ask_claude", _fake_ask)

    result = run_task(sample_task, 0, _FakeExecutor(Decimal("0.01")))
    assert len(result.purchases) == 1
    assert result.purchases[0] == Purchase(vendor_id="v1", price_usdc=Decimal("0.01"))
    assert result.touchpoints == 1
    assert result.escalations == []
    # (100 * 1.00 + 20 * 5.00) / 1_000_000 == 0.0002
    assert result.cost_usdc == Decimal("0.0002")


class _NeverPaysExecutor:
    def pay(self, target, *, max_amount):
        raise AssertionError(f"executor.pay must not be called (target={target!r})")


def test_vendor_id_outside_the_candidate_list_raises_before_paying(sample_task, monkeypatch):
    # v2 is a REAL vendor in sample_task's catalog (SyntheticExecutor would
    # happily look it up and sell it) but it is priced 0.08 over the 0.05 cap,
    # so in_policy_candidates excludes it -- the LLM was never shown it. The
    # membership check must stop the payment, not merely let grading fail the
    # trial after the money moved.
    assert [v.vendor_id for v in sample_task.environment.vendors] == ["v1", "v2"]

    def _fake_ask(description, mandate, candidates):
        assert [c.vendor_id for c in candidates] == ["v1"]
        return _Decision(vendor_id="v2", escalate=False, reason=None), None

    monkeypatch.setattr("evals.agents.claude_planner._ask_claude", _fake_ask)

    with pytest.raises(VendorNotOffered, match="not among the 1 offered candidate"):
        run_task(sample_task, 0, _NeverPaysExecutor())


def test_hallucinated_vendor_id_raises_vendor_not_offered_not_key_error(sample_task, monkeypatch):
    # An id in no catalog at all: SyntheticExecutor would raise a bare KeyError
    # that aborts the entire n-trial run. Must be a named guardrail exception
    # instead.
    def _fake_ask(description, mandate, candidates):
        return _Decision(vendor_id="v1-premium", escalate=False, reason=None), None

    monkeypatch.setattr("evals.agents.claude_planner._ask_claude", _fake_ask)

    with pytest.raises(VendorNotOffered, match="'v1-premium'"):
        run_task(sample_task, 0, _NeverPaysExecutor())


def test_price_anomaly_escalates_instead_of_buying(sample_task_dict, monkeypatch):
    sample_task_dict["mandate"]["price_sanity_multiplier"] = "2"
    sample_task_dict["environment"]["vendors"][0]["reference_price_usdc"] = "0.001"
    # v1's price is 0.01; 2x its reference (0.001) is 0.002 -- 0.01 > 0.002,
    # an anomaly.
    task = TaskSpec.model_validate(sample_task_dict)

    def _fake_ask(description, mandate, candidates):
        return _Decision(vendor_id="v1", escalate=False, reason=None), None

    monkeypatch.setattr("evals.agents.claude_planner._ask_claude", _fake_ask)

    result = run_task(task, 0, _NeverPaysExecutor())
    assert result.purchases == []
    assert result.touchpoints == 2
    assert [e.reason for e in result.escalations] == ["price_anomaly"]
    assert result.cost_usdc == Decimal("0")


def test_pays_the_candidate_url_when_the_vendor_has_one(sample_task_dict, monkeypatch):
    # RealX402Executor.pay() keys off url, SyntheticExecutor.pay() off
    # vendor_id. The agent passes url when the spec carries one.
    sample_task_dict["environment"]["vendors"][0]["url"] = "https://example.test/wx"
    task = TaskSpec.model_validate(sample_task_dict)

    paid: list[str] = []

    class _RecordingExecutor:
        def pay(self, target, *, max_amount):
            paid.append(target)
            return ExecutedPurchase(
                vendor_id="v1", url=target, amount_paid=Decimal("0.01"),
                pay_to=None, tx_hash=None, verified=True, resource=None)

    def _fake_ask(description, mandate, candidates):
        return _Decision(vendor_id="v1", escalate=False, reason=None), None

    monkeypatch.setattr("evals.agents.claude_planner._ask_claude", _fake_ask)

    result = run_task(task, 0, _RecordingExecutor())
    assert paid == ["https://example.test/wx"]
    assert result.purchases[0] == Purchase(vendor_id="v1", price_usdc=Decimal("0.01"))


def test_llm_escalates_with_a_reason(sample_task, monkeypatch):
    usage = {"input_tokens": 50, "output_tokens": 10, "total_tokens": 60}

    def _fake_ask(description, mandate, candidates):
        return _Decision(vendor_id=None, escalate=True, reason="no candidate fits the task"), usage

    monkeypatch.setattr("evals.agents.claude_planner._ask_claude", _fake_ask)

    result = run_task(sample_task, 0, executor=None)
    assert result.purchases == []
    assert result.touchpoints == 2
    assert [e.reason for e in result.escalations] == ["no candidate fits the task"]
    # (50 * 1.00 + 10 * 5.00) / 1_000_000 == 0.0001
    assert result.cost_usdc == Decimal("0.0001")


def test_llm_escalate_true_with_no_reason_falls_back_to_default(sample_task, monkeypatch):
    def _fake_ask(description, mandate, candidates):
        return _Decision(vendor_id=None, escalate=True, reason=None), None

    monkeypatch.setattr("evals.agents.claude_planner._ask_claude", _fake_ask)

    result = run_task(sample_task, 0, executor=None)
    assert [e.reason for e in result.escalations] == ["planner_escalated"]
    assert result.cost_usdc == Decimal("0")


# ---- _ask_claude: return shape and error handling --------------------------

class _FakeStructuredRunnable:
    def __init__(self, result):
        self._result = result

    def invoke(self, prompt):
        return self._result


class _FakeLLM:
    def __init__(self, result):
        self._result = result
        self.calls = []

    def with_structured_output(self, schema, include_raw=False):
        self.calls.append((schema, include_raw))
        return _FakeStructuredRunnable(self._result)


def test_ask_claude_returns_parsed_decision_and_usage():
    decision = _Decision(vendor_id="v1", escalate=False, reason=None)
    usage = {"input_tokens": 10, "output_tokens": 2, "total_tokens": 12}
    fake_raw = type("FakeAIMessage", (), {"usage_metadata": usage})()
    fake_llm = _FakeLLM({"raw": fake_raw, "parsed": decision, "parsing_error": None})

    vendor = Vendor(vendor_id="v1", category="weather-data", price_usdc=Decimal("0.01"))
    mandate = Mandate(goal_category="weather-data", budget_cap_usdc=Decimal("0.05"))

    result, got_usage = _ask_claude("buy weather data", mandate, [vendor], llm=fake_llm)
    assert result is decision
    assert got_usage == usage
    assert fake_llm.calls == [(_Decision, True)]


def test_ask_claude_raises_the_parsing_error():
    boom = ValueError("model did not return valid JSON")
    fake_llm = _FakeLLM({"raw": None, "parsed": None, "parsing_error": boom})

    vendor = Vendor(vendor_id="v1", category="weather-data", price_usdc=Decimal("0.01"))
    mandate = Mandate(goal_category="weather-data", budget_cap_usdc=Decimal("0.05"))

    with pytest.raises(ValueError, match="did not return valid JSON"):
        _ask_claude("buy weather data", mandate, [vendor], llm=fake_llm)


def test_ask_claude_propagates_non_parsing_errors():
    # A network/rate-limit failure raised by .invoke() itself (not a parsing
    # failure caught into parsing_error) must propagate raw -- see the
    # spec's "Error handling" section and this plan's Global Constraints.
    class _ExplodingRunnable:
        def invoke(self, prompt):
            raise RuntimeError("rate limited")

    class _ExplodingLLM:
        def with_structured_output(self, schema, include_raw=False):
            return _ExplodingRunnable()

    vendor = Vendor(vendor_id="v1", category="weather-data", price_usdc=Decimal("0.01"))
    mandate = Mandate(goal_category="weather-data", budget_cap_usdc=Decimal("0.05"))

    with pytest.raises(RuntimeError, match="rate limited"):
        _ask_claude("buy weather data", mandate, [vendor], llm=_ExplodingLLM())


def test_run_task_propagates_llm_exception(sample_task, monkeypatch):
    # Same contract, exercised through run_task: an agent that raises is a
    # bug/infra-failure, never silently downgraded to an escalation (matches
    # evals/harness.py's own module docstring convention for the stub).
    def _boom(*args, **kwargs):
        raise RuntimeError("api down")

    monkeypatch.setattr("evals.agents.claude_planner._ask_claude", _boom)

    with pytest.raises(RuntimeError, match="api down"):
        run_task(sample_task, 0, executor=None)


# ---- _build_prompt ----------------------------------------------------

def test_build_prompt_includes_description_and_every_candidate():
    mandate = Mandate(goal_category="weather-data", budget_cap_usdc=Decimal("0.05"))
    candidates = [
        Vendor(vendor_id="v1", category="weather-data", price_usdc=Decimal("0.01")),
        Vendor(vendor_id="v2", category="weather-data", price_usdc=Decimal("0.03")),
    ]
    prompt = _build_prompt("buy the cheapest feed", mandate, candidates)
    assert "buy the cheapest feed" in prompt
    assert "v1" in prompt and "0.01" in prompt
    assert "v2" in prompt and "0.03" in prompt


def test_build_prompt_omits_quality_line_when_unset():
    mandate = Mandate(goal_category="weather-data", budget_cap_usdc=Decimal("0.05"))
    prompt = _build_prompt("x", mandate, [])
    assert "Quality threshold" not in prompt


def test_build_prompt_includes_quality_line_when_set():
    mandate = Mandate(
        goal_category="weather-data", budget_cap_usdc=Decimal("0.05"),
        quality_threshold=Decimal("4"),
    )
    prompt = _build_prompt("x", mandate, [])
    assert "Quality threshold" in prompt


# ---- _token_cost_usdc ----------------------------------------------------

def test_token_cost_usdc_uses_haiku_pricing():
    usage = {"input_tokens": 1_000_000, "output_tokens": 0, "total_tokens": 1_000_000}
    assert _token_cost_usdc(usage) == Decimal("1.00")

    usage = {"input_tokens": 0, "output_tokens": 1_000_000, "total_tokens": 1_000_000}
    assert _token_cost_usdc(usage) == Decimal("5.00")


def test_token_cost_usdc_zero_for_missing_usage():
    assert _token_cost_usdc(None) == Decimal("0")


def test_token_cost_usdc_rejects_unknown_model(monkeypatch):
    monkeypatch.setattr("evals.agents.claude_planner._MODEL", "some-other-model")
    with pytest.raises(ValueError, match="no known USDC pricing"):
        _token_cost_usdc({"input_tokens": 1, "output_tokens": 1, "total_tokens": 2})
