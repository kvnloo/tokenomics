from tokenomics import Economics, Outcome, TokenUsage, TokenomicsEvent, summarize_trace, tokens_per_verified_task


def ev(trace, role, inp, out, *, aggregate=False, gold=False, cost=0):
    return TokenomicsEvent(
        kind="llm" if role != "verifier" else "verification",
        name=role,
        trace_id=trace,
        role=role,
        status="ok",
        usage=TokenUsage(input_tokens=inp, output_tokens=out, attribution="aggregate" if aggregate else "incremental", source="provider"),
        economics=Economics(cost_usd=cost),
        outcome=Outcome(verified_success=True, verification_source="tests") if gold else None,
    )


def test_trace_sums_root_worker_without_double_counting_aggregate():
    trace = "0" * 31 + "1"
    rows = [
        ev(trace, "root", 100, 10, cost=.01),
        ev(trace, "rlm_worker", 20, 5, cost=.002),
        ev(trace, "root", 135, 0, aggregate=True),
        ev(trace, "verifier", 0, 0, gold=True),
    ]
    s = summarize_trace(rows)
    assert s.total_tokens == 135
    assert s.root_tokens == 110
    assert s.worker_tokens == 25
    assert s.aggregate_reported_tokens == 135
    assert s.reconciliation_delta == 0
    assert s.verified


def test_tokens_per_verified_task_is_trace_level():
    a = "a" * 32
    b = "b" * 32
    rows = [ev(a, "root", 10, 1, gold=True), ev(a, "rlm_worker", 5, 1), ev(b, "root", 50, 5)]
    stats = tokens_per_verified_task(rows)
    assert stats["n_verified"] == 1
    assert stats["tokens_per_verified_task"] == 17
