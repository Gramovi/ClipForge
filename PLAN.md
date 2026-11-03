# ClipForge – plán práce

Aplikace z dlouhého videa automaticky vytvoří krátké klipy (9:16 / 1:1 / 16:9)
s animovanými titulky, Virality Score a popisky. Tento soubor je zdroj pravdy
o stavu práce – při přerušení pokračuj od první neodškrtnuté položky.

Legenda: `[x]` hotovo a otestováno, `[ ]` zbývá, `[~]` částečně (viz poznámka).

## Fáze 1 – kostra + Docker + DB
- [x] Struktura repa (`backend/`, `frontend/`, `shared/`), `.gitignore`, `.env.example`
- [x] FastAPI aplikace, konfigurace přes `pydantic-settings`
- [x] SQLAlchemy modely + Alembic migrace (users, projects, clips, uploads, presets, brand_templates, fonts)
- [x] Dockerfile backendu (api + worker), Dockerfile frontendu, `docker-compose.yml` (frontend, api, worker, redis, postgres, profil `ollama`, profil `gpu`)
- [x] Testy: pytest kostra, ruff, mypy
- [x] Commit

## Fáze 2 – upload + fronta + průběh
- [x] Obnovitelný chunked upload (init → PUT chunk s offsetem → stav → complete), limit velikosti
- [x] Import z URL (yt-dlp) s poznámkou o právech
- [x] RQ fronta, job `process_project`, stavy a kroky v DB
- [x] SSE endpoint s průběhem (krok, %, ETA)
- [x] Abstrakce úložiště (`LocalStorage`, rozhraní pro S3)
- [x] Testy + commit

## Fáze 3 – přepis
- [x] faster-whisper, `word_timestamps=True`, model z `WHISPER_MODEL` (výchozí `large-v3`), volba modelu na projekt
- [x] Extrakce audia FFmpegem, časový rozsah zpracování
- [x] Auto-detekce jazyka + ruční volba
- [x] Testovací videa (CZ + EN TTS, krátké i 20–30 min)
- [x] Testy + commit

## Fáze 4 – hledání momentů přes LLM
- [x] Abstraktní vrstva `LLMProvider` (Anthropic, Ollama), přepínání `LLM_PROVIDER`
- [x] Překrývající se okna přepisu (12 min, překryv 90 s)
- [x] Prompt + JSON schéma, validace, oprava rozbitého JSONu, retry s backoffem, rate limit
- [x] Post-processing: zarovnání na věty, padding, dedup (>50 % překryv), vynucení délky, řazení
- [x] Odhad ceny (Anthropic) podle tokenů, srozumitelné chyby (chybí klíč / neplatný klíč)
- [x] Testy + commit

## Fáze 5 – render klipu + reframing
- [x] Detekce obličejů (MediaPipe FaceLandmarker, fallback OpenCV Haar), 5 vzorků/s
- [x] Aktivní mluvčí (pohyb úst), vyhlazení dráhy ořezu
- [x] Layouty: crop sledující obličej, split screen, fit + blur
- [x] FFmpeg render (H.264 High, CRF 18, preset, yuv420p, +faststart, AAC 192k, původní fps, bez upscalu)
- [x] Testy + commit

## Fáze 6 – titulky + presety
- [x] `shared/caption-presets.json` – ≥ 12 presetů (jeden zdroj pravdy)
- [x] Generátor ASS (karaoke `\k`, `\t`, `\fscx`…), emoji, zvýraznění klíčových slov, hook text
- [x] Fonty s českou diakritikou + nahrání vlastního .ttf/.otf
- [x] SRT (UTF-8), uživatelské presety, Brand Template (logo, barvy, font, intro/outro)
- [x] Vizuální kontrola ≥ 4 presetů (snímky)
- [x] Testy + commit

## Fáze 7 – frontend: výsledky + editor
- [x] Next.js App Router + TS + Tailwind + shadcn-style UI, texty v `lib/i18n/cs.ts`
- [x] Nový projekt (upload/URL + parametry), živý průběh
- [x] Mřížka klipů podle skóre (rozpad, zdůvodnění, popisek, hashtagy)
- [x] Editor: přehrávač s živým náhledem titulků (ze stejného JSONu), timeline, klik na slovo, úprava textu, styl, odstranění ticha/vycpávek, hook
- [x] Commit

## Fáze 8 – export + ZIP
- [x] Render na vyžádání po úpravě, stažení MP4 + SRT + TXT, ZIP všech
- [x] Testy + commit

## Fáze 9 – auth + dashboard
- [x] Registrace/přihlášení (e-mail + heslo, bcrypt, JWT v httpOnly cookie)
- [x] Oddělení dat uživatelů (všechny dotazy filtrují `user_id`)
- [x] Dashboard: seznam projektů, přejmenování, mazání
- [x] Nastavení: poskytovatel/model, odhad ceny, stav API klíče
- [x] Testy + commit

## Fáze 10 – leštění + ověření
- [x] Playwright E2E (registrace → upload → hotovo → klip → preset → export → stažení), konzole, mobil
- [x] Chybové stavy: poškozený soubor, bez řeči, bez obličeje, příliš velký, chybí klíč, výpadek LLM
- [~] E2E pipeline na 20–30min CZ + EN videu, ffprobe kontroly (viz Poznámky)
- [x] `docker compose up` (ověřeno v sandboxu; base image přes mirror kvůli rate limitu Docker Hubu)
- [x] README (česky), build/lint/typecheck bez chyb
- [x] Commit + push

## Poznámky / rozhodnutí
- Aplikace žije v podadresáři `clipforge/`, protože kořen repozitáře obsahuje jinou (nesouvisející) aplikaci.
- YuNet (OpenCV) detekuje obličeje, MediaPipe FaceLandmarker jen měří ústa na výřezu – samotný MediaPipe
  v širokém záběru obličeje nenajde (detektor je jen „short range“).
- MediaPipe se instaluje `--no-deps` (bez jax/scipy, −450 MB).
- `av<16` – faster-whisper 1.2.1 nefunguje s PyAV 16+.
- Next.js proxy: `middlewareClientMaxBodySize: 64mb`, chunk uploadu 8 MB (výchozí limit 10 MB ořezával chunky).
- Bez Anthropic API klíče v testovacím prostředí: Anthropic vrstva ověřena unit testy (mock SSE streamu)
  a skutečným voláním API s neplatným klíčem (→ srozumitelná chyba 401). Kvalita výběru momentů
  s Claude NEBYLA v tomto prostředí změřena; E2E běhy používaly Ollama `qwen2.5:3b` na CPU.
- Testovací média: `scripts/make_test_media.py` (Piper TTS, 2 mluvčí, pohyb úst, střihy).
