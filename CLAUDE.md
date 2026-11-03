# ClipForge – konvence projektu

## Struktura
- `backend/` – Python 3.12, FastAPI (`app/main.py`), RQ worker (`app/worker.py`), pipeline v `app/pipeline/`.
- `frontend/` – Next.js (App Router) + TypeScript + Tailwind. UI texty jen v `src/lib/i18n/cs.ts`.
- `shared/caption-presets.json` – JEDINÝ zdroj pravdy pro presety titulků. Backend (ASS generátor) i
  frontend (náhled) čtou tentýž soubor. Nepřidávej presety jinam.
- `PLAN.md` – stav práce po fázích; po dokončení položky ji odškrtni.

## Pravidla
- Dlouhé operace (přepis, LLM, render, ZIP) běží VŽDY ve workeru přes RQ, nikdy v HTTP requestu.
- Každý dotaz na data uživatele filtruje `user_id` (helpery v `app/api/deps.py`).
- Soubory jen přes `app.storage` (abstrakce pro pozdější S3/R2).
- LLM jen přes `app.llm.get_provider()`; žádné přímé volání SDK mimo `app/llm/`.
- API klíče se nikdy nelogují ani neposílají na frontend (`settings.public_dict()` je vynechává).
- Text je všude UTF-8 (SRT, ASS, TXT, JSON); testy hlídají českou diakritiku.
- Časy v backendu jsou v sekundách (`float`) relativně k začátku zdrojového videa.

## Příkazy
- Backend testy: `cd backend && .venv/bin/pytest -q`
- Lint/typy: `cd backend && .venv/bin/ruff check . && .venv/bin/mypy app`
- Frontend: `cd frontend && npm run lint && npx tsc --noEmit && npm run build`
- E2E: `cd frontend && npx playwright test` (vyžaduje běžící stack)
- Celý stack: `docker compose up --build`

## Commity
- Po každé fázi: testy zelené → commit s popisnou zprávou (česky nebo anglicky, konzistentně anglicky v předmětu).
