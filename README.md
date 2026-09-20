# BlueSky Signal Desk

A production-minded FastAPI dashboard and background worker for discovering BlueSky users who engage with keyword-matched posts. It inspects public profile/post signals, applies a strict follower threshold, records every candidate in SQLite, and optionally follows matches with a daily cap and randomized delay.

## Quick start

1. Create an environment and install dependencies:

   ```powershell
   py -m venv .venv
   .\.venv\Scripts\python.exe -m pip install -r requirements.txt
   ```

   PowerShell may block `Activate.ps1` on machines with restrictive execution policies. Activation is optional; run project commands through the environment directly:

   ```powershell
   .\.venv\Scripts\python.exe -m uvicorn main:app --reload
   ```

   For a temporary activation in the current PowerShell process only, use:

   ```powershell
   Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
   .\.venv\Scripts\Activate.ps1
   ```

2. Copy `.env.example` to `.env` and add your credentials. In PowerShell:

   ```powershell
   Copy-Item .env.example .env
   notepad .env
   ```

   Set `BSKY_HANDLE` to your handle, such as `name.bsky.social`, and set `BSKY_APP_PASSWORD` to a BlueSky App Password. Keep `DRY_RUN=true` until the discovery behavior is verified.

3. Start the dashboard:

   ```powershell
   .\.venv\Scripts\python.exe -m uvicorn main:app --reload
   ```

   If port `8000` is already in use, either open the existing server at http://127.0.0.1:8000 or start another instance on a different port:

   ```powershell
   .\.venv\Scripts\python.exe -m uvicorn main:app --reload --port 8001
   ```

4. Open http://127.0.0.1:8000.

## Operating notes

- `DRY_RUN=true` records matches and logs intended follows without making follow mutations.
- Set `DRY_RUN=false` only after reviewing the discovered users. Use a dedicated BlueSky account and a modest `MAX_FOLLOWS_PER_DAY`.
- The worker pauses automatically after reaching the daily follow cap. `PAUSE`, `RESUME`, and `STOP` are available from the dashboard.
- SQLite data is stored at `data/bsky_bot.db`; logs are written to `logs/bsky-bot.log` and the console.
- BlueSky API behavior and rate limits can change. Review the current BlueSky terms and API guidance before enabling live follows.

## Layout

- `config.py` - validated environment configuration.
- `database.py` - SQLAlchemy schema and persistence helpers.
- `bsky_client.py` - authenticated ATProtocol integration.
- `worker.py` - search, liker inspection, filtering, and rate-limited action loop.
- `main.py` - FastAPI app, control API, export endpoint, and dashboard.
