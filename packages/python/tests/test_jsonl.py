from tokenomics import JsonlSink, TokenomicsEvent, iter_jsonl


def test_jsonl_append_and_tolerant_read(tmp_path):
    p = tmp_path / "events.jsonl"
    sink = JsonlSink(p)
    a = TokenomicsEvent(kind="tool", name="read")
    b = TokenomicsEvent(kind="llm", name="root")
    sink.emit(a)
    p.write_text(p.read_text() + "not-json\n")
    sink.emit(b)
    got = list(iter_jsonl(p))
    assert [x.event_id for x in got] == [a.event_id, b.event_id]
