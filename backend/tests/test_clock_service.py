"""Unit tests for ClockService utility."""
from datetime import datetime, timezone
from app.utils.clock import get_temporal_context, get_temporal_prompt_block


def test_clock_q1():
    dt = datetime(2026, 2, 15, 10, 0, 0, tzinfo=timezone.utc)
    ctx = get_temporal_context(dt)
    assert ctx["current_quarter"] == "Q1"
    assert ctx["quarter_start_date"] == "2026-01-01"
    assert ctx["quarter_end_date"] == "2026-03-31"


def test_clock_q2():
    dt = datetime(2026, 5, 20, 10, 0, 0, tzinfo=timezone.utc)
    ctx = get_temporal_context(dt)
    assert ctx["current_quarter"] == "Q2"
    assert ctx["quarter_start_date"] == "2026-04-01"
    assert ctx["quarter_end_date"] == "2026-06-30"


def test_clock_q3():
    dt = datetime(2026, 9, 29, 10, 0, 0, tzinfo=timezone.utc)
    ctx = get_temporal_context(dt)
    assert ctx["current_quarter"] == "Q3"
    assert ctx["quarter_start_date"] == "2026-07-01"
    assert ctx["quarter_end_date"] == "2026-09-30"


def test_clock_q4():
    dt = datetime(2026, 11, 10, 10, 0, 0, tzinfo=timezone.utc)
    ctx = get_temporal_context(dt)
    assert ctx["current_quarter"] == "Q4"
    assert ctx["quarter_start_date"] == "2026-10-01"
    assert ctx["quarter_end_date"] == "2026-12-31"


def test_clock_prompt_block():
    dt = datetime(2026, 9, 29, 10, 0, 0, tzinfo=timezone.utc)
    block = get_temporal_prompt_block(dt)
    assert "2026-09-29" in block
    assert "Q3 2026" in block
    assert "Calendar Year" in block
