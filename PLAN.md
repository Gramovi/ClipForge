# ClipForge – plán práce

Aplikace z dlouhého videa automaticky vytvoří krátké klipy (9:16 / 1:1 / 16:9)
s animovanými titulky, Virality Score a popisky. Tento soubor je zdroj pravdy
o stavu práce – při přerušení pokračuj od první neodškrtnuté položky.

Legenda: `[x]` hotovo a otestováno, `[ ]` zbývá, `[~]` částečně (viz poznámka).

## Fáze 1 – kostra + Docker + DB
- [x] Struktura repa (`backend/`, `frontend/`, `shared/`), `.gitignore`, `.env.example`
- [x] FastAPI aplikace, konfigurace přes `pydantic-settings`
- [x] SQLAlchemy modely + Alembic migrace (users, projects, clips, uploads, presets, brand_templates, fonts)
- [ ] Dockerfile backendu (api + worker), Dockerfile frontendu, `docker-compose.yml` (frontend, api, worker, redis, postgres, profil `ollama`, profil `gpu`)
- [x] Testy: pytest kostra, ruff, mypy
- [ ] Commit

## Fáze 2 – upload + fronta + průběh
- [ ] Obnovitelný chunked upload (init → PUT chunk s offsetem → stav → complete), limit velikosti
- [ ] Import z URL (yt-dlp) s poznámkou o právech
- [ ] RQ fronta, job `process_project`, stavy a kroky v DB
- [ ] SSE endpoint s průběhem (krok, %, ETA)
- [x] Abstrakce úložiště (`LocalStorage`, rozhraní pro S3)
- [ ] Testy + commit

## Fáze 3 – přepis
- [ ] faster-whisper, `word_timestamps=True`, model z `WHISPER_MODEL` (výchozí `large-v3`), volba modelu na projekt
- [ ] Extrakce audia FFmpegem, časový rozsah zpracování
- [ ] Auto-detekce jazyka + ruční volba
- [ ] Testovací videa (CZ + EN TTS, krátké i 20–30 min)
- [ ] Testy + commit

## Fáze 4 – hledání momentů přes LLM
- [x] Abstraktní vrstva `LLMProvider` (Anthropic, Ollama), přepínání `LLM_PROVIDER`
- [x] Překrývající se okna přepisu (12 min, překryv 90 s)
- [x] Prompt + JSON schéma, validace, oprava rozbitého JSONu, retry s backoffem, rate limit
- [x] Post-processing: zarovnání na věty, padding, dedup (>50 % překryv), vynucení délky, řazení
- [ ] Odhad ceny (Anthropic) podle tokenů, srozumitelné chyby (chybí klíč / neplatný klíč)
- [ ] Testy + commit

## Fáze 5 – render klipu + reframing
- [ ] Detekce obličejů (MediaPipe FaceLandmarker, fallback OpenCV Haar), 5 vzorků/s
- [ ] Aktivní mluvčí (pohyb úst), vyhlazení dráhy ořezu
- [ ] Layouty: crop sledující obličej, split screen, fit + blur
- [ ] FFmpeg render (H.264 High, CRF 18, preset, yuv420p, +faststart, AAC 192k, původní fps, bez upscalu)
- [ ] Testy + commit

## Fáze 6 – titulky + presety
- [x] `shared/caption-presets.json` – ≥ 12 presetů (jeden zdroj pravdy)
- [ ] Generátor ASS (karaoke `\k`, `\t`, `\fscx`…), emoji, zvýraznění klíčových slov, hook text
- [ ] Fonty s českou diakritikou + nahrání vlastního .ttf/.otf
- [ ] SRT (UTF-8), uživatelské presety, Brand Template (logo, barvy, font, intro/outro)
- [ ] Vizuální kontrola ≥ 4 presetů (snímky)
- [ ] Testy + commit

## Fáze 7 – frontend: výsledky + editor
- [ ] Next.js App Router + TS + Tailwind + shadcn-style UI, texty v `lib/i18n/cs.ts`
- [ ] Nový projekt (upload/URL + parametry), živý průběh
- [ ] Mřížka klipů podle skóre (rozpad, zdůvodnění, popisek, hashtagy)
- [ ] Editor: přehrávač s živým náhledem titulků (ze stejného JSONu), timeline, klik na slovo, úprava textu, styl, odstranění ticha/vycpávek, hook
- [ ] Commit

## Fáze 8 – export + ZIP
- [ ] Render na vyžádání po úpravě, stažení MP4 + SRT + TXT, ZIP všech
- [ ] Testy + commit

## Fáze 9 – auth + dashboard
- [ ] Registrace/přihlášení (e-mail + heslo, bcrypt, JWT v httpOnly cookie)
- [ ] Oddělení dat uživatelů (všechny dotazy filtrují `user_id`)
- [ ] Dashboard: seznam projektů, přejmenování, mazání
- [ ] Nastavení: poskytovatel/model, odhad ceny, stav API klíče
- [ ] Testy + commit

## Fáze 10 – leštění + ověření
- [ ] Playwright E2E (registrace → upload → hotovo → klip → preset → export → stažení), konzole, mobil
- [ ] Chybové stavy: poškozený soubor, bez řeči, bez obličeje, příliš velký, chybí klíč, výpadek LLM
- [ ] E2E pipeline na 20–30min CZ + EN videu, ffprobe kontroly
- [ ] `docker compose up` na čistém stavu
- [ ] README (česky), build/lint/typecheck bez chyb
- [ ] Commit + push

## Poznámky / rozhodnutí
- Stav k prvnímu commitu: veškerý kód napsán, jednotkové testy (63) zelené, frontend build OK. End-to-end ověření (Docker, reálná videa, Playwright) následuje – položky výše se odškrtávají až po ověření.
- Aplikace žije v podadresáři `clipforge/`, protože kořen repozitáře obsahuje jinou (nesouvisející) aplikaci.
