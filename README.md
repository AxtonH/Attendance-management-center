# Prezlab Attendance Dashboard

Read-only attendance dashboard for the P&C team. Punches arrive in Supabase every 5 minutes from a ZKTeco BioTime extract script; this app surfaces them as Present/Late/Absent counts, a department roll-up, an arrival-pattern histogram, and an exceptions feed.

## Phase status

**Phase 1 (current) — display only, no roster.**
- Reads punches from the existing `attendance` table in Supabase.
- Employees are derived per-request from distinct `(emp_code, employee_name)` pairs in the punches themselves; the only file in `config/` is `shift_rules.yaml`.
- Single org-wide shift: 09:00 start, 15-min grace.
- **No absence detection.** Without a roster, we cannot list who was expected. The Absent tile shows `—`, the department roll-up shows a placeholder, and the Exceptions panel is Late-only.
- No authentication.

**Phase 2 (next) — Odoo + auth.**
- Replace `PunchDerivedRosterProvider` with an Odoo-backed implementation (same `RosterProvider` protocol, so domain code does not change). This lights up the Absent tile, department roll-up, and absent-row exceptions.
- Add Microsoft 365 SSO.
- Per-department or per-employee shift rules.

## Layout

```
repo/
├── backend/        FastAPI service (Python 3.11+)
│   ├── app/
│   │   ├── api/        thin route handlers
│   │   ├── domain/     pure logic — rules, computations, response models
│   │   ├── infra/      Supabase client, roster loader
│   │   ├── config.py   env settings (pydantic-settings)
│   │   └── main.py     app factory
│   └── tests/      pytest, hits domain only
├── frontend/       Next.js 14 App Router + TypeScript + Tailwind
│   ├── app/        routes
│   ├── components/ dashboard/, layout/, ui/, providers/
│   └── lib/        api client, query hooks, zod schemas, formatters
├── config/         shift_rules.yaml (roster + departments arrive with Odoo)
└── docker-compose.yml
```

The split is intentional: anything I/O lives in `backend/app/infra`, anything pure lives in `backend/app/domain`. When Odoo lands, only `infra/roster.py` changes (swap `PunchDerivedRosterProvider` for an `OdooRosterProvider` that satisfies the same protocol).

## Running locally

### Prerequisites
- Python 3.11+
- Node 20+
- A Supabase project with the `attendance` table from the schema you already deployed.

### One-time setup
1. Copy `.env.example` to `.env` and fill in `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` (the service-role key bypasses RLS; keep it backend-only).
2. Install backend dependencies:
   ```sh
   cd backend
   python -m venv .venv
   .venv/Scripts/python -m pip install -e ".[dev]"     # Windows
   # or: .venv/bin/python -m pip install -e ".[dev]"   # macOS/Linux
   ```
3. Install frontend dependencies:
   ```sh
   cd frontend
   npm install
   ```

### Day-to-day: one command
From the repo root:
```sh
python run.py
```
This launches the backend (uvicorn on :8000) and the frontend (Next.js dev server on :3000, or the next free port if 3000 is busy), waits for both to be ready, then opens the dashboard in your browser. Logs from both services are streamed with prefixes. `Ctrl+C` stops both cleanly.

API docs: <http://localhost:8000/docs>

### Running services individually
Useful when iterating on just one side:
```sh
# Terminal 1 — backend with auto-reload
cd backend && .venv/Scripts/python -m uvicorn app.main:app --reload --port 8000

# Terminal 2 — frontend
cd frontend && npm run dev
```

### Or use Docker
```sh
docker compose up --build
```

## API surface

| Method | Path                       | Returns                                          |
|--------|----------------------------|--------------------------------------------------|
| GET    | `/health`                  | Liveness probe                                   |
| GET    | `/api/overview`            | Present / Late / Absent counts                   |
| GET    | `/api/exceptions`          | Flagged employees (absent / late / pattern)      |
| GET    | `/api/departments/rollup`  | Per-department status counts                     |
| GET    | `/api/arrivals/histogram`  | Bucketed first-punch times for the histogram     |

All endpoints accept `?date=YYYY-MM-DD` (defaults to today in `APP_TIMEZONE`).

## Configuration

| File                       | Purpose                                              |
|----------------------------|------------------------------------------------------|
| `config/shift_rules.yaml`  | `start`, `grace_minutes`, `absent_after`             |

Phase 1 has no roster file: employees are inferred from punches. Departments are unavailable until phase 2 (Odoo).

## Notes on data assumptions

- `punch_time` is `TIMESTAMP` without timezone in the schema. We treat it as `APP_TIMEZONE` (default `Asia/Amman`). If your BioTime extract script normalizes to UTC, change `APP_TIMEZONE` accordingly.
- "Earliest punch of the day" determines status. Subsequent punches (clock-out, re-entry) are ignored for phase-1 classifications.
- The day's "roster" is whoever shows up in the punch data for that day. An employee with no punch is invisible to phase 1 — not absent, just unknown.

## Testing
- Backend: `pytest` covers shift rules and the attendance service end-to-end on in-memory fixtures. No Supabase access required.
- Frontend: `npm run typecheck` for static checks; integration testing comes with phase 2.
