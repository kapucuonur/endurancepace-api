# endurancepace-api

FastAPI backend for the **EndurancePace** React Native app. Runs on a Raspberry Pi 5
behind a Cloudflare Tunnel, same shape as `bikefit-api` (systemd + uvicorn + SQLite).

Every endpoint maps **1:1** to the frontend's `EnduranceApi` interface
(`EndurancePace/src/services/api.ts`) — the app's `RestApi` is a direct
fetch-per-method translation with no field renaming or reshaping.

---

## Quick start (local)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env                 # edit ENDURANCEPACE_JWT_SECRET_KEY

alembic upgrade head                 # create schema
python -m scripts.seed_db            # demo account + sample data
uvicorn main:app --reload --port 8006

# docs (dev only): set ENDURANCEPACE_ENABLE_DOCS=true, then http://localhost:8006/docs
```

Demo login: `demo@endurancepace.app` / `demo1234`.

```bash
pytest                               # end-to-end smoke tests (in-memory SQLite)
```

---

## Architecture

| Concern | Choice | Notes |
|---|---|---|
| Web | FastAPI + uvicorn | `main:app` shim at repo root so systemd `WorkingDirectory` = repo root (bikefit-api pattern) |
| DB | SQLite via SQLAlchemy 2.x | `ENDURANCEPACE_DATABASE_URL`; Postgres works too |
| Migrations | Alembic | `0001_initial`, `0002_garmin` |
| Auth | **Stateless JWT** (python-jose HS256, `sub`=email) | matches the real `bikefit-api/auth.py`; `Authorization: Bearer <jwt>` |
| Validation | Pydantic v2, `alias_generator=to_camel` | camelCase on the wire, snake_case in Python |
| Zones | `app/zones.py` — a port of the frontend `domain/zones.ts` | server recomputes HR/power/run-pace zones on threshold change |
| Garmin | `app/garmin/` — ported from ai-coach, DB-backed session state | unofficial email+password; run **`--workers 1`** (state is DB-backed, so multi-worker is a config flip later). See [Garmin sync](#garmin-sync). |

### Data model

One `User` ⇄ one `Athlete` (created together at signup). `TrainingPlan`, `RaceEvent`
and `Workout` belong to the athlete.

**The `Step` tree is a single JSON column** (`workouts.structure`), not normalised.
Interval structures are read/written whole by the app and never queried into;
normalising them would add joins and make the 1:1 contract lossy for zero benefit.
`plannedDuration` / `plannedTss` are computed client-side and simply persisted
(exactly as the app's mock layer does) — the server never recomputes them at runtime.
The seed script *does* compute them, via `app/workout_metrics.py` (a port of
`domain/workout.ts`), so seeded values match the app.

### Serialization policy

- **Reads emit every field.** Frontend-optional (`?`) fields come back as `null`
  rather than being omitted — one deliberate, harmless divergence from the mock's
  `JSON.stringify` (which drops `undefined`). Deterministic response shape, safe for
  the TS optional types.
- **Writes** (`PATCH`/`PUT` bodies) use `exclude_unset` — a missing key means
  "don't touch"; an explicit `null` clears the value.
- Nested JSON blobs (`structure`, `completed`, `thresholds`, zone lists) are stored
  the way the app stores them: camelCase keys, `null`/absent dropped.

---

## Endpoint map

| `EnduranceApi` method | HTTP |
|---|---|
| `getSnapshot()` | `GET /me/snapshot` |
| `resetToSeed()` | `POST /me/reset` — 403 unless `ENDURANCEPACE_ALLOW_RESET=true` |
| `updateAthlete(patch)` | `PATCH /me/athlete` — stores as given, **no** zone recompute |
| `updateThresholds(t)` | `PUT /me/athlete/thresholds` — merges, then recomputes zones |
| `listPlans()` | `GET /plans` |
| `createPlan(input)` | `POST /plans` |
| `updatePlan(id, patch)` | `PATCH /plans/{id}` |
| `deletePlan(id)` | `DELETE /plans/{id}` — 204; detaches its workouts (`planId → null`) |
| `listEvents()` | `GET /events` |
| `createEvent(input)` | `POST /events` |
| `updateEvent(id, patch)` | `PATCH /events/{id}` |
| `deleteEvent(id)` | `DELETE /events/{id}` — 204; nulls `goalEventId` on referencing plans |
| `listWorkouts()` | `GET /workouts` (all, incl. templates) |
| `listWorkoutsInRange(s,e)` | `GET /workouts?start=<ISO>&end=<ISO>` (scheduled, non-template) |
| `listLibraryWorkouts()` | `GET /workouts?template=true` |
| `getWorkout(id)` | `GET /workouts/{id}` — 404 → frontend maps to `undefined` |
| `createWorkout(input)` | `POST /workouts` |
| `updateWorkout(id, patch)` | `PATCH /workouts/{id}` |
| `deleteWorkout(id)` | `DELETE /workouts/{id}` — 204 |
| `scheduleFromTemplate(tId,date,planId?)` | `POST /workouts/{tId}/schedule` body `{ date, planId }` |
| `listCoachAthletes()` | `GET /coach/athletes` — 403 unless caller's email is in `COACH_EMAILS` |
| `coachAthleteSnapshot(id)` | `GET /coach/athletes/{id}/snapshot` |
| `assignWorkout(id, input)` | `POST /coach/athletes/{id}/workouts` — creates a `source:"coach"` workout |
| `updateAssignedWorkout(id, wId, patch)` | `PATCH /coach/athletes/{id}/workouts/{wId}` — coach's own assignments only |
| `withdrawAssignedWorkout(id, wId)` | `DELETE /coach/athletes/{id}/workouts/{wId}` — 204 |
| — | `POST /auth/signup` `{ email, password, name? }` → 201 `{ email }` |
| — | `POST /auth/login` `{ email, password }` → `{ token }` |
| — | `GET /health` |

`NewPlan` / `NewEvent` still carry `athleteId` (the app sends it); the server
ignores it and scopes to the authenticated athlete.

---

## Garmin sync

Ported from ai-coach's Garmin layer. **Unofficial** — the athlete links their
Garmin.com account with **email + password** (`garminconnect` / `garth`), no
OAuth app. This violates Garmin's ToS and their SSO rate-limits aggressively;
accepted trade-off (the official Developer Program is closed to new signups).

**Requires** `ENDURANCEPACE_FIELD_ENCRYPT_KEY` (Fernet) — encrypts the stored
Garmin password **and** the session token blob:

```bash
python -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())"
```

### What changed vs ai-coach

| ai-coach | here |
|---|---|
| `GLOBAL_CLIENTS` in-memory dict | `garmin_sessions` table (survives restarts, multi-worker safe) |
| session tokens stored as plaintext JSON | Fernet-encrypted blob |
| `SESSION_LAST_VERIFIED` / `FAILED_LOGIN_COOLDOWN` / `PENDING_SESSIONS` module dicts | `garmin_sessions` columns (`last_verified_at`, `cooldown_until`, `mfa_client_state` + `mfa_initiated_at` TTL) |
| MFA via a live login thread + `threading.Event` | `garth` `return_on_mfa` → `client_state` stored (encrypted) → `resume_login` on the 2nd request. No thread state. |
| MFA password-loss bug (`/connect-garmin/mfa` couldn't recover the password) | password persisted (encrypted) at `/connect`, before MFA completes |
| `GARMIN_PROXY_URL` (Render datacenter IP bans) | dropped — the Pi has a residential IP |
| pull-on-demand, no dedup | pull-on-demand + dedup by `activityId`, match-or-create against planned workouts |

All `garminconnect` / `garth` usage is isolated in `app/garmin/client.py`
(`garth` is unmaintained — pin, and keep the blast radius to one file).

### Endpoints (`/me/garmin`, all require the athlete's bearer token)

| Method | Path | |
|---|---|---|
| `POST` | `/me/garmin/connect` | `{ garminEmail, garminPassword }` → `{ status: "connected" \| "mfa_required" }` |
| `POST` | `/me/garmin/connect/mfa` | `{ mfaCode }` → `{ status: "connected" }` (400 if the ~10 min MFA window lapsed) |
| `DELETE` | `/me/garmin/connect` | 204 — clears creds, session row, disk tokens |
| `GET` | `/me/garmin/status` | `{ connected, garminEmail, state, displayName, lastSyncAt, lastVerifiedAt, cooldownRemaining, lastError }` |
| `POST` | `/me/garmin/sync?days=` | pull activities → `{ status, imported, updated, matched, skipped }` |
| `GET` | `/me/garmin/activities?limit=` | raw sanitized passthrough (debug) |

### Sync behaviour

- **Trigger:** the app calls `POST /me/garmin/sync` (on foreground / pull-to-refresh).
  Set `ENDURANCEPACE_GARMIN_SYNC_ON_SNAPSHOT=true` to also fire a best-effort sync
  from `GET /me/snapshot`. v2: `deploy/endurancepace-garmin-sync.{service,timer}`
  (systemd timer, no in-process scheduler).
- **Debounce / lock:** `garmin_sessions.sync_in_progress` + a min-interval
  (`ENDURANCEPACE_GARMIN_SYNC_MIN_INTERVAL_SECONDS`, default 120) — rapid
  refreshes return `{ status: "skipped", reason: "too_soon" | "already_running" }`.
- **Backfill:** first sync pulls `ENDURANCEPACE_GARMIN_SYNC_DEFAULT_DAYS` (30) days.
- **Mapping:** Garmin activity → `Workout` (`status="completed"`, `source="garmin"`,
  `external_id=activityId`, sanitized payload kept in `garmin_raw`). Sport from
  `ENDURANCEPACE_GARMIN_SPORT_MAP` (`typeKey` substring → sport); unmapped types
  (walk, yoga, …) are skipped.
- **Dedup:** `UNIQUE(athlete_id, external_id)`. Re-syncing updates in place.
- **Match-or-create:** if a **planned** manual workout exists on the same
  date + sport, it's marked completed and the Garmin actuals attach to it (its
  structured `plannedTss` is preserved). Ambiguous (>1 candidate) → closest by
  duration, with a `_matchNote` left in `garmin_raw`. Otherwise a new workout.

### TSS

`completed.actualTss` resolution order:

1. Garmin `trainingStressScore` if present and `> 0` (power/HR-derived — best).
2. HR estimate: `round(hours × (avgHR / thresholds.thresholdHr)² × 100)` — same
   `IF²·h·100` shape, IF from the **whole-session average HR** (this is
   TrainingPeaks' hrTSS method, not the "zone number as IF" antipattern).
3. `null`.

⚠️ Garmin only reliably fills `trainingStressScore` for **cycling with a power
meter**. Running/swimming rely on step 2 → set `thresholdHr` or imported actuals
stay `null`. `plannedTss` on a new import = `actualTss` (so week totals aren't
zero); on a matched planned workout the structured estimate is kept.

> **Maintenance note:** `garmin_raw` is ~5–20 KB per activity. Fine at this
> scale; add an archive/prune job once history + user count grow.

---

## Frontend `RestApi` (drop into `services/api.ts`)

```ts
class RestApi implements EnduranceApi {
  constructor(private baseUrl: string, private token: () => string | null) {}

  private async req<T>(path: string, init?: RequestInit): Promise<T> {
    const res = await fetch(`${this.baseUrl}${path}`, {
      ...init,
      headers: {
        'Content-Type': 'application/json',
        ...(this.token() ? { Authorization: `Bearer ${this.token()}` } : {}),
        ...(init?.headers ?? {}),
      },
    });
    if (res.status === 204) return undefined as T;
    if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
    return res.json() as Promise<T>;
  }
  private qs(o: Record<string, string | undefined>) {
    const p = new URLSearchParams();
    for (const [k, v] of Object.entries(o)) if (v != null) p.set(k, v);
    const s = p.toString();
    return s ? `?${s}` : '';
  }

  getSnapshot() { return this.req<AppSnapshot>('/me/snapshot'); }
  resetToSeed() { return this.req<AppSnapshot>('/me/reset', { method: 'POST' }); }

  updateAthlete(patch: Partial<Athlete>) {
    return this.req<Athlete>('/me/athlete', { method: 'PATCH', body: JSON.stringify(patch) });
  }
  updateThresholds(thresholds: ThresholdValues) {
    return this.req<Athlete>('/me/athlete/thresholds', { method: 'PUT', body: JSON.stringify(thresholds) });
  }

  listPlans() { return this.req<TrainingPlan[]>('/plans'); }
  createPlan(input: NewPlan) { return this.req<TrainingPlan>('/plans', { method: 'POST', body: JSON.stringify(input) }); }
  updatePlan(id: ID, patch: Partial<TrainingPlan>) {
    return this.req<TrainingPlan>(`/plans/${id}`, { method: 'PATCH', body: JSON.stringify(patch) });
  }
  deletePlan(id: ID) { return this.req<void>(`/plans/${id}`, { method: 'DELETE' }); }

  listEvents() { return this.req<RaceEvent[]>('/events'); }
  createEvent(input: NewEvent) { return this.req<RaceEvent>('/events', { method: 'POST', body: JSON.stringify(input) }); }
  updateEvent(id: ID, patch: Partial<RaceEvent>) {
    return this.req<RaceEvent>(`/events/${id}`, { method: 'PATCH', body: JSON.stringify(patch) });
  }
  deleteEvent(id: ID) { return this.req<void>(`/events/${id}`, { method: 'DELETE' }); }

  listWorkouts() { return this.req<Workout[]>('/workouts'); }
  listWorkoutsInRange(startISO: ISODate, endISO: ISODate) {
    return this.req<Workout[]>(`/workouts${this.qs({ start: startISO, end: endISO })}`);
  }
  listLibraryWorkouts() { return this.req<Workout[]>('/workouts?template=true'); }
  async getWorkout(id: ID) {
    try { return await this.req<Workout>(`/workouts/${id}`); }
    catch (e) { if (String(e).startsWith('Error: 404')) return undefined; throw e; }
  }
  createWorkout(input: NewWorkout) { return this.req<Workout>('/workouts', { method: 'POST', body: JSON.stringify(input) }); }
  updateWorkout(id: ID, patch: Partial<Workout>) {
    return this.req<Workout>(`/workouts/${id}`, { method: 'PATCH', body: JSON.stringify(patch) });
  }
  deleteWorkout(id: ID) { return this.req<void>(`/workouts/${id}`, { method: 'DELETE' }); }
  scheduleFromTemplate(templateId: ID, dateISO: ISODate, planId: ID | null = null) {
    return this.req<Workout>(`/workouts/${templateId}/schedule`, {
      method: 'POST', body: JSON.stringify({ date: dateISO, planId }),
    });
  }
}
```

Auth (login/signup, token storage) lives outside `EnduranceApi` — add a small
`services/auth.ts` that POSTs to `/auth/*` and stashes the token in AsyncStorage,
then `new RestApi(BASE_URL, () => tokenFromStore)`.

---

## Deploy to the Pi

```bash
# on the Pi
git clone <repo> /home/pi/endurancepace-api
cd /home/pi/endurancepace-api
python3 -m venv /home/pi/endurancepace_env
/home/pi/endurancepace_env/bin/pip install -r requirements.txt

cp .env.example .env
#  - ENDURANCEPACE_JWT_SECRET_KEY   : openssl rand -hex 32
#  - ENDURANCEPACE_FIELD_ENCRYPT_KEY: python -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())"
/home/pi/endurancepace_env/bin/alembic upgrade head
/home/pi/endurancepace_env/bin/python -m scripts.seed_db   # optional

sudo cp deploy/endurancepace-api.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now endurancepace-api
sudo systemctl status endurancepace-api          # listening on :8006 (--workers 1)
```

Config comes from `/home/pi/endurancepace-api/.env` (pydantic-settings reads it
relative to `WorkingDirectory`). After a pull: `alembic upgrade head && sudo systemctl restart endurancepace-api`.

### Cloudflare Tunnel

Public hostname `endurancepace-api.coachonurai.com` → `http://localhost:8006`
(same tunnel as bikefit-api / ai-coach). Either add it in the Zero Trust
dashboard (Networks → Tunnels → the tunnel → Public Hostname) or in the config:

```yaml
# ~/.cloudflared/config.yml
ingress:
  - hostname: endurancepace-api.coachonurai.com   # <-- add this
    service: http://localhost:8006
  - service: http_status:404                      # keep last
```

```bash
sudo systemctl restart cloudflared   # only if you edited config.yml
```

Then point the app at `https://endurancepace-api.coachonurai.com`.

### Hardening

Done:
- **CORS** — `ENDURANCEPACE_CORS_ORIGINS` defaults to the Expo web dev ports, not
  `*`. Native app is unaffected (no `Origin`). Add your real web domain here
  before shipping a web build.
- **`/docs` / `/redoc` / `/openapi.json`** — 404 unless `ENDURANCEPACE_ENABLE_DOCS=true`.
- **Rate limiting** (slowapi, per real client via `CF-Connecting-IP`):
  `POST /auth/login` 10/min, `POST /auth/signup` 5/hour → 429. Toggle with
  `ENDURANCEPACE_RATELIMIT_ENABLED`.

Still on you:
- **`ENDURANCEPACE_JWT_SECRET_KEY`** — real random value (`openssl rand -hex 32`).
- **`ENDURANCEPACE_FIELD_ENCRYPT_KEY`** — generate on the box, back it up
  (losing it = every Garmin link must be re-done).
- **`ENDURANCEPACE_ALLOW_RESET=false`** in prod.
- **Demo account** — `demo@endurancepace.app` has a known password and is
  publicly reachable. Delete it before onboarding real users (or set
  `ENDURANCEPACE_DEMO_EMAIL` / `ENDURANCEPACE_DEMO_PASSWORD`).
- **Pi SSH** — move off password auth to keys, then disable
  `PasswordAuthentication` in `sshd_config`.
