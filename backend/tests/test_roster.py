from datetime import datetime
from pathlib import Path

import pytest
import yaml

from app.shared.models import Punch
from app.infra.roster import PunchDerivedRosterProvider


@pytest.fixture
def provider(tmp_path: Path) -> PunchDerivedRosterProvider:
    (tmp_path / "shift_rules.yaml").write_text(
        yaml.safe_dump(
            {"default_shift": {"start": "09:00", "grace_minutes": 15, "absent_after": "10:30"}}
        )
    )
    return PunchDerivedRosterProvider(tmp_path)


def _punch(emp_code: str | None, name: str | None, tid: int = 1) -> Punch:
    return Punch(
        transaction_id=tid,
        emp_code=emp_code,
        employee_name=name,
        punch_time=datetime(2026, 5, 12, 9, 0),
    )


class TestPunchDerivedRoster:
    def test_dedupes_by_emp_code(self, provider):
        punches = [_punch("1001", "Khaled", 1), _punch("1001", "Khaled", 2)]
        emps = provider.employees_from_punches(punches)
        assert len(emps) == 1
        assert emps[0].emp_code == "1001"
        assert emps[0].name == "Khaled"

    def test_falls_back_to_emp_code_when_name_missing(self, provider):
        punches = [_punch("1001", None, 1)]
        emps = provider.employees_from_punches(punches)
        assert emps[0].name == "1001"

    def test_skips_rows_without_emp_code(self, provider):
        punches = [_punch(None, "Mystery", 1), _punch("1001", "Khaled", 2)]
        emps = provider.employees_from_punches(punches)
        assert {e.emp_code for e in emps} == {"1001"}

    def test_departments_is_empty(self, provider):
        assert provider.departments() == []

    def test_default_shift_loads_yaml(self, provider):
        rule = provider.default_shift()
        assert rule.start == "09:00"
        assert rule.grace_minutes == 15
