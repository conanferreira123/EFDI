"""Centralized system clock service for EFDI Global Chatbot.

Provides trusted UTC temporal grounding, quarter definitions, and calendar-year boundaries.
All date resolutions derive strictly from trusted server time, preventing client/LLM tampering.
"""
from datetime import date, datetime, timezone
from typing import Any, Dict, Optional


def get_current_utc_datetime() -> datetime:
    """Return current timezone-aware UTC datetime."""
    return datetime.now(timezone.utc)


def get_temporal_context(as_of: Optional[datetime] = None) -> Dict[str, Any]:
    """Calculate temporal context and fiscal quarter boundaries based on standard calendar year.

    Fiscal Calendar Definition:
      Q1: January 1 – March 31
      Q2: April 1 – June 30
      Q3: July 1 – September 30
      Q4: October 1 – December 31
    """
    dt = as_of or get_current_utc_datetime()
    current_date = dt.date()
    year = current_date.year
    month = current_date.month

    if month in (1, 2, 3):
        quarter_num = 1
        q_start = date(year, 1, 1)
        q_end = date(year, 3, 31)
    elif month in (4, 5, 6):
        quarter_num = 2
        q_start = date(year, 4, 1)
        q_end = date(year, 6, 30)
    elif month in (7, 8, 9):
        quarter_num = 3
        q_start = date(year, 7, 1)
        q_end = date(year, 9, 30)
    else:
        quarter_num = 4
        q_start = date(year, 10, 1)
        q_end = date(year, 12, 31)

    return {
        "current_utc_date": current_date.isoformat(),
        "current_year": year,
        "current_quarter": f"Q{quarter_num}",
        "current_quarter_label": f"Q{quarter_num} {year}",
        "quarter_start_date": q_start.isoformat(),
        "quarter_end_date": q_end.isoformat(),
        "year_start_date": date(year, 1, 1).isoformat(),
        "year_end_date": date(year, 12, 31).isoformat(),
    }


def get_temporal_prompt_block(as_of: Optional[datetime] = None) -> str:
    """Generate standardized prompt block for LLM temporal awareness."""
    ctx = get_temporal_context(as_of)
    return (
        f"TEMPORAL CONTEXT (Derived from Trusted Server System Clock):\n"
        f"- Current UTC Date: {ctx['current_utc_date']}\n"
        f"- Current Year: {ctx['current_year']}\n"
        f"- Current Calendar / Fiscal Quarter: {ctx['current_quarter_label']} "
        f"({ctx['quarter_start_date']} to {ctx['quarter_end_date']})\n"
        f"- Fiscal Calendar Standard: Calendar Year (Q1: Jan-Mar, Q2: Apr-Jun, Q3: Jul-Sep, Q4: Oct-Dec)\n"
        f"When interpreting temporal expressions (e.g. 'current fiscal quarter', 'last 30 days', 'this year'), "
        f"you MUST anchor your calculations to the Current UTC Date ({ctx['current_utc_date']}) and Current Year ({ctx['current_year']})."
    )
