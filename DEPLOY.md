# Deploying to Railway

This repo is a monorepo with two services that deploy independently:

- **`backend/`** — FastAPI, talks to Supabase + Odoo.
- **`frontend/`** — Next.js 14, calls the backend over HTTPS.

Each becomes one Railway service. Both build from this single GitHub repo.

---

## 1. Create the Railway project

1. In Railway, **New Project → Deploy from GitHub repo → select this repo.**
2. Railway will guess what to deploy. **Cancel its first guess** — we'll add two services manually so each gets the right build config.

## 2. Add the backend service

1. In the project, **+ New → GitHub Repo → pick this repo again.**
2. **Settings → Service Settings:**
   - **Root Directory**: leave empty (defaults to repo root).
   - **Watch Paths** (optional): `backend/**` and `config/**`. So pushes that only touch the frontend don't redeploy the backend.
3. **Settings → Build:**
   - Builder: Dockerfile (auto-detected from `backend/railway.toml`).
   - Dockerfile path: `backend/Dockerfile` (also from the toml).
4. **Variables → Add the following:**

   | Variable | Value |
   |---|---|
   | `SUPABASE_URL` | Your Supabase project URL |
   | `SUPABASE_SERVICE_ROLE_KEY` | Service-role key (backend-only, never expose to frontend) |
   | `ODOO_URL` | e.g. `https://your-org.odoo.com` |
   | `ODOO_DB` | Your Odoo database name |
   | `ODOO_USERNAME` | The integration user's email/username |
   | `ODOO_PASSWORD` | The integration user's password or API key |
   | `APP_TIMEZONE` | `Asia/Amman` (or other IANA tz) |
   | `APP_LOG_LEVEL` | `INFO` |
   | `CORS_ALLOW_ORIGINS` | **Leave for now; you'll set this after the frontend deploys.** |
   | `ODOO_EMPLOYEE_CACHE_TTL` | `300` (5 min; optional) |

   `PORT` is injected automatically — don't set it.

5. **Settings → Networking → Generate Domain.** Note the URL (e.g. `https://attendance-backend-production.up.railway.app`).
6. Wait for the first deploy. Hit `/health` on the generated URL — should return `{"status":"ok"}`.

## 3. Add the frontend service

1. **+ New → GitHub Repo → pick this repo again** (yes, third time).
2. **Settings → Service Settings:**
   - **Root Directory**: `frontend`. This is critical — without it, Next.js can't find its files.
   - **Watch Paths** (optional): `frontend/**`.
3. **Build/Dockerfile path**: `Dockerfile` (auto-detected from `frontend/railway.toml`).
4. **Variables:**

   | Variable | Value |
   |---|---|
   | `NEXT_PUBLIC_API_BASE_URL` | **The backend URL from step 2.5**, no trailing slash. |

   Railway passes this to the Dockerfile as a build arg automatically (because we declared `ARG NEXT_PUBLIC_API_BASE_URL` in the Dockerfile). Next.js inlines `NEXT_PUBLIC_*` vars **at build time**, so if you change this var later you must redeploy.

5. **Settings → Networking → Generate Domain.** Note the URL.
6. Wait for the deploy. Open the URL — you should see the dashboard, though the data will fail to load until you fix CORS in the next step.

## 4. Wire CORS

1. Go back to the **backend** service → **Variables**.
2. Set `CORS_ALLOW_ORIGINS` to the frontend's URL (the one from step 3.5), no trailing slash. Example:

   ```
   CORS_ALLOW_ORIGINS=https://attendance-frontend-production.up.railway.app
   ```

   Multiple origins are supported as a comma-separated list (no spaces).

3. Railway will redeploy the backend automatically. The frontend should now load real data.

## 5. Verify

- Open the frontend URL.
- The Pulse Bar should show Present / Late / Absent counts.
- Click the calendar → it should open the picker.
- Switch to Weekly / Monthly tabs.
- Network tab: requests to `/api/dashboard` should hit the backend URL and return 200.

---

## Troubleshooting

### "There was an error deploying from source"

That error from Railway is generic. Check the build logs:

- **`COPY backend/pyproject.toml ./pyproject.toml: file does not exist`** → Root Directory is set on the backend service. Clear it (leave empty) so the build context is the repo root.
- **`npm ERR! enoent`** → Root Directory is NOT set on the frontend service. Set it to `frontend`.
- **`Module not found: Can't resolve 'react-day-picker'`** → Frontend deps didn't install. Trigger a redeploy; if it persists, check `package-lock.json` is committed.

### Frontend loads but data is empty / CORS errors in the console

`CORS_ALLOW_ORIGINS` on the backend doesn't match the frontend URL. Common mistakes: trailing slash, `http://` vs `https://`, wrong subdomain. Check the browser console — the error message includes the exact origin Railway is calling from.

### Frontend shows old `NEXT_PUBLIC_API_BASE_URL`

That variable is baked into the bundle at build time. Changing it requires a redeploy (Railway → Deployments → Redeploy).

### Backend can't reach Odoo

- Check `ODOO_URL` doesn't have a trailing slash.
- If Odoo is on a private network, Railway can't reach it. You'd need a tunnel or a public Odoo endpoint.

### Backend can't reach Supabase

- Supabase is public over HTTPS; if it works locally it should work on Railway.
- Make sure you're using the **service-role key**, not the anon key (the backend needs RLS bypass).

---

## Cost shape

Both services are tiny — backend's Odoo calls are cached for 5 minutes and Supabase reads are paginated. On Railway's Hobby tier you'll comfortably stay under the included usage with this dashboard's load (one team of ~90 people).
