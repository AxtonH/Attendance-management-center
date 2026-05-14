from app.features.employees.service import build_employees_today
from app.shared.models import Employee

from tests._fixtures import DAY, emp, punch


class TestEmployeesToday:
    def test_first_and_last_punch(self):
        employees = [emp("1001", "Khaled"), emp("1002", "Layla")]
        punches = [
            punch("1001", 9, 5, 1),
            punch("1001", 17, 30, 2),
            punch("1002", 8, 45, 3),
        ]
        result = build_employees_today(employees, punches, DAY)
        rows = {r.emp_code: r for r in result.rows}
        assert rows["1001"].punch_in.hour == 9
        assert rows["1001"].punch_out is not None
        assert rows["1001"].punch_out.hour == 17
        # 09:05 → 17:30 = 8h25m = 505 minutes.
        assert rows["1001"].worked_minutes == 505
        assert rows["1002"].punch_in.hour == 8
        assert rows["1002"].punch_out is None
        # Single-punch day: no defensible duration to show.
        assert rows["1002"].worked_minutes is None

    def test_excludes_inactive_employees(self):
        employees = [
            Employee(emp_code="1001", name="Active", department="", active=True),
            Employee(emp_code="1002", name="Inactive", department="", active=False),
        ]
        punches = [punch("1001", 9, 0, 1), punch("1002", 9, 0, 2)]
        result = build_employees_today(employees, punches, DAY)
        codes = {r.emp_code for r in result.rows}
        assert codes == {"1001"}

    def test_empty_input_returns_empty(self):
        result = build_employees_today([], [], DAY)
        assert result.rows == []
