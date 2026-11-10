"""Work-from-home resolution: which employees are WFH on a given day.

Rule: Thursday, Friday and Saturday (`default_shift.wfh_weekdays` in
`config/shift_rules.yaml`) are WFH days for anyone whose shift covers them.
WFH = the employee's shift ∩ {Thu, Fri, Sat}; those days outside the shift
are simply their weekend:

    Sun–Thu → Thu             Sat–Wed → Sat
    Mon–Fri → Thu, Fri        Fri–Tue → Fri, Sat
    Tue–Sat → Thu, Fri, Sat   Wed–Sun → Thu, Fri, Sat

A shift that needs different WFH days can be pinned in the optional
`wfh_by_shift` override table.

The roster resolves the policy into a per-day emp_code set
(`RosterProvider.wfh_emp_codes_for`), and domain code asks `is_wfh` per
employee. A `None` set means "no schedule info" (phase-1 punch-derived
roster); `is_wfh` then applies the weekday rule to everyone.

Per-day sets (rather than a per-employee weekday pattern) are the seam on
purpose: date-specific WFH from Odoo can later replace the rule without
touching any domain code.

Pure. No I/O.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date


@dataclass(frozen=True)
class WfhPolicy:
    """Which days within a shift are WFH (weekdays Mon=0..Sun=6)."""

    # WFH whenever the employee's shift covers them.
    wfh_weekdays: frozenset[int]
    # Exact working-day set → WFH days, for shifts that differ from the rule.
    overrides: Mapping[frozenset[int], frozenset[int]] = field(default_factory=dict)

    def wfh_weekdays_for(self, working_days: frozenset[int]) -> frozenset[int]:
        """WFH days for a shift. Never includes a day outside the shift."""
        override = self.overrides.get(working_days)
        if override is not None:
            return override
        return self.wfh_weekdays & working_days


def is_wfh(
    emp_code: str,
    day: date,
    wfh_emp_codes: frozenset[str] | None,
    fallback_weekdays: Iterable[int],
) -> bool:
    """Is `day` a WFH day for this employee?

    `wfh_emp_codes` is the roster's resolved set for `day`. When it's None
    (no schedule info) the weekday rule `fallback_weekdays` decides.
    """
    if wfh_emp_codes is not None:
        return emp_code in wfh_emp_codes
    return day.weekday() in fallback_weekdays
