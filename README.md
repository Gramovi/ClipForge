# ClipForge

**ClipForge** z dlouhého videa (podcast, rozhovor, stream – klidně 2–3 hodiny) automaticky vytvoří
co nejvíc kvalitních krátkých klipů pro TikTok, Instagram Reels a YouTube Shorts: najde nejsilnější
momenty, ohodnotí je Virality Score, ořízne obraz na mluvčího, přidá animované titulky a vyexportuje
video v plné kvalitě.

> Aplikace žije v adresáři `clipforge/` tohoto repozitáře (kořen repozitáře obsahuje jiný, nesouvisející projekt).

## Obsah

- [Rychlý start](#rychlý-start)
- [Jak to funguje](#jak-to-funguje)
- [Získání API klíče (Anthropic)](#získání-api-klíče-anthropic)
- [Lokální model zdarma (Ollama)](#lokální-model-zdarma-ollama)
- [Konfigurace (.env)](#konfigurace-env)
- [Požadavky na hardware](#požadavky-na-hardware)
- [Náklady na hodinu videa](#náklady-na-hodinu-videa)
- [Architektura](#architektura)
- [Vývoj a testy](#vývoj-a-testy)
- [Známá omezení](#známá-omezení)

## Rychlý start

Potřebujete jen Docker (Docker Desktop nebo Docker Engine + Compose v2).

```bash
cd clipforge
cp .env.example .env          # doplňte ANTHROPIC_API_KEY (nebo přepněte na Ollama, viz níže)
docker compose up --build
```

Otevřete <http://localhost:3000>, zaregistrujte se a nahrajte video.

- První spuštění stahuje Docker obrazy a při prvním přepisu i model Whisper (large-v3 ≈ 3 GB) – to chvíli trvá.
  Modely se ukládají do volume `models`, takže se stahují jen jednou.
- Bez souboru `.env` aplikace také naběhne; v Nastavení pak uvidíte, že chybí API klíč a jak ho doplnit.
- Data (videa, klipy) jsou ve volume `media`, databáze ve volume `pgdata`.

Volitelné profily:

```bash
docker compose --profile ollama up --build            # + lokální LLM (Ollama), LLM_PROVIDER=ollama
docker compose --profile gpu up --build --scale worker=0   # Whisper na NVIDIA GPU (nvidia-container-toolkit)
```

## Jak to funguje

1. **Nahrání** – drag & drop, obnovitelný chunked upload (16 MB části, až 5 GB; při výpadku spojení
   nebo zavření stránky se naváže tam, kde přestal), nebo odkaz (YouTube apod. přes yt-dlp – jen vlastní
   obsah nebo obsah, ke kterému máte práva).
2. **Nastavení** – délka klipů (Auto / <30 s / 30–60 s / 60–90 s / 90 s–3 min), poměr stran (9:16, 1:1, 16:9),
   jazyk (auto-detekce nebo ruční volba), model přepisu, preset titulků, téma/klíčová slova, časový rozsah.
3. **Zpracování na pozadí** (RQ worker) s živým průběhem přes SSE: nahrávání → přepis → hledání momentů →
   reframing → render, s procenty a odhadem zbývajícího času. Stránku můžete zavřít.
4. **Výsledky** – mřížka klipů podle Virality Score (0–100) s rozpadem Hook / Flow / Hodnota / Trend,
   zdůvodněním, popiskem a hashtagy (ve stejném jazyce jako video).
5. **Editor** – živý náhled (ořez i titulky se počítají ze stejných dat jako finální render), úprava
   začátku/konce (posuvník, čísla, kliknutí na slovo v přepisu), oprava textu titulků bez změny časování,
   změna presetu a stylu, layout (sledování mluvčího / split screen / rozmazané pozadí), AI hook text,
   odstranění ticha a vycpávkových slov (ehm, hm, jako, prostě, vlastně…), brand template.
6. **Export** – MP4 (H.264 High, CRF 18, `yuv420p`, `+faststart`, AAC 192 kb/s, původní fps), `.srt`
   (UTF-8) a `.txt`; jednotlivě nebo vše jako ZIP.

### Hledání momentů

- Přepis s časem každého slova (faster-whisper, `word_timestamps=True`).
- Přepis se dělí na **překrývající se okna** (výchozí 12 min s překryvem 1,5 min, zarovnaná na věty), takže
  3hodinové video = ~17 oken a nic se neztratí na hranách.
- Každé okno jde do LLM se strukturovaným JSON výstupem (`start, end, title, hook, reason, scores, virality_score,
  description, hashtags, keywords, emojis`). Prompt hledá samostatně srozumitelné myšlenky se silným háčkem,
  emoce, kontroverzi, konkrétní rady, příběhy a vtipy; počet klipů není uměle omezen.
- Robustnost: retry s exponenciálním backoffem (respektuje `retry-after`), oprava rozbitého JSONu (code fences,
  čárky navíc, useknutý výstup, python literály…), validace schématu, opakovaný dotaz s popisem chyby.
  Selže-li jen část oken, výsledek se použije s upozorněním; při úplném výpadku dostane uživatel srozumitelnou chybu.
- Post-processing: zarovnání na začátek/konec věty (+ padding), vynucení zvolené délky, odstranění duplicit
  a klipů překrývajících se o víc než 50 %, seřazení podle skóre.

### Reframing

- Detekce obličejů 5× za sekundu: **OpenCV YuNet** (spolehlivý i pro menší obličeje v širokém záběru) a na
  výřezu každého obličeje **MediaPipe FaceLandmarker** pro měření otevření úst.
- **Aktivní mluvčí** = obličej s největší variabilitou otevření úst (s hysterezí, aby kamera neskákala).
- Virtuální kamera: „dead-zone“ sledování + vyhlazení klouzavým průměrem, reset při střihu (detekce změny scény).
- Bez obličeje → layout „celý záběr + rozmazané pozadí“; při 2 mluvčích lze zvolit split screen.

### Titulky

- `shared/caption-presets.json` je **jediný zdroj pravdy**: backend z něj generuje ASS (libass ve FFmpeg,
  animace `\k`/`\kf`, `\t`, `\fscx`, `\fad`, `\blur`…), frontend z téhož JSONu kreslí náhled.
- 14 presetů: Bold Pop, Karaoke, Minimal, Neon Glow, Box, Typewriter, Bounce, Gradient, Comic, Podcast Clean,
  Emoji, Highlight Keywords, Cinema, Impact Green. Vše jde upravit (font, velikost, barvy, obrys, stín, pozadí,
  pozice + posun, slova na obrazovce 1–4, VELKÁ písmena, animace, zvýraznění, emoji) a uložit jako vlastní preset.
- Vestavěné fonty (OFL, Google Fonts) jsou ověřené na plnou českou diakritiku; lze nahrát vlastní `.ttf/.otf`.
- Barevná emoji renderujeme jako PNG overlay (libass barevná emoji neumí).
- Brand Template: logo (pozice, průhlednost, velikost), barvy, font, intro/outro video.

## Získání API klíče (Anthropic)

1. Založte účet na <https://console.anthropic.com/> a nastavte platby (Billing).
2. V **Settings → API Keys** vytvořte klíč.
3. Vložte ho do `clipforge/.env`:
   ```
   LLM_PROVIDER=anthropic
   ANTHROPIC_API_KEY=sk-ant-...
   ANTHROPIC_MODEL=claude-sonnet-5-5     # nebo claude-haiku-5-5 (nejlevnější)
   ```
4. `docker compose up -d` (služby si načtou nový `.env`).

Klíč se používá jen ve workeru; nikdy se neposílá do prohlížeče a neloguje se. V aplikaci v **Nastavení**
vidíte, který poskytovatel a model se používá, zda klíč funguje a odhad ceny. Chybějící nebo neplatný klíč
se v projektu projeví srozumitelnou chybou s návodem.

## Lokální model zdarma (Ollama)

```bash
# .env
LLM_PROVIDER=ollama
OLLAMA_MODEL=qwen2.5:7b     # stáhne se automaticky při prvním použití
```
```bash
docker compose --profile ollama up --build
```

Pro lokální modely je validace a oprava JSONu přísnější (Ollama structured outputs + tolerantní parser,
automatické přepočítání časů relativních k oknu, extra pokus o opravu). Zpracování oken běží sekvenčně.

| Model (Ollama) | RAM/VRAM | Rychlost na CPU (8 jader) | Kvalita (čeština) |
|---|---|---|---|
| `qwen2.5:3b` | ~3 GB | rychlé | slabé názvy, občas nesmyslné hranice |
| `qwen2.5:7b` (výchozí) | ~5–6 GB | ~5–10 min na okno 12 min | použitelné, češtinu zvládá s chybami |
| `qwen2.5:14b` | ~10 GB | 2× pomalejší | výrazně lepší čeština |
| `llama3.1:8b` | ~6 GB | jako 7b | dobrá angličtina, slabší čeština |

Očekávejte, že lokální modely najdou méně klipů, skóre budou méně kalibrované a české popisky méně přirozené
než u Claude. Na GPU (8+ GB VRAM) je Ollama 10–30× rychlejší.

## Konfigurace (.env)

Všechny proměnné jsou v [`.env.example`](.env.example) s komentáři. Nejdůležitější:

| Proměnná | Výchozí | Význam |
|---|---|---|
| `LLM_PROVIDER` | `anthropic` | `anthropic` nebo `ollama` |
| `ANTHROPIC_API_KEY` | – | API klíč |
| `ANTHROPIC_MODEL` | `claude-sonnet-5-5` | `claude-haiku-5-5` = nejlevnější, `claude-sonnet-5-5` = nejvyšší kvalita |
| `ANTHROPIC_EFFORT` | `medium` | `low`/`medium`/`high` – hloubka uvažování modelu (cena × kvalita) |
| `OLLAMA_MODEL` | `qwen2.5:7b` | lokální model |
| `WHISPER_MODEL` | `large-v3` | pro češtinu `large-v3` (nejlepší) nebo `large-v3-turbo` (rychlejší, téměř stejně přesný); `medium`/`small` jen na slabém CPU s horší kvalitou |
| `WHISPER_DEVICE` | `auto` | `cpu` / `cuda` |
| `MAX_UPLOAD_BYTES` | 5 GB | limit uploadu |
| `X264_PRESET` / `X264_CRF` | `slow` / `18` | kvalita exportu (`medium` ≈ 2× rychlejší) |
| `RENDER_ON_PROCESS` | `true` | renderovat všechny klipy hned po zpracování |
| `SECRET_KEY` | – | **pro nasazení pro víc lidí změňte** |
| `COOKIE_SECURE` | `false` | `true` za HTTPS |

Model přepisu lze zvolit i u každého projektu zvlášť (UI upozorní na horší kvalitu malých modelů v češtině).

## Požadavky na hardware

| Konfigurace | Doporučení |
|---|---|
| Minimum | 4 jádra CPU, 8 GB RAM, 20 GB disku + místo na videa |
| Doporučeno (CPU) | 8+ jader, 16 GB RAM |
| Ideál | NVIDIA GPU s 8+ GB VRAM (Whisper large-v3 ~20–40× rychleji než reálný čas) |

Orientační rychlost přepisu (faster-whisper, int8 na CPU, změřeno na 4 jádrech):

| Model | 1 min audia trvá | 2 h podcast |
|---|---|---|
| `small` | ~0,6 min | ~1,2 h |
| `large-v3-turbo` | ~1,3 min | ~2,5 h |
| `large-v3` | ~2,5–3 min | ~5–6 h |
| `large-v3` na GPU (RTX 3060+) | ~2–4 s | ~5–8 min |

Render: preset `slow` na CPU zhruba 0,5–1× reálného času na klip 1080×1920 (4 jádra), `medium` ~2× rychleji.

## Náklady na hodinu videa

Odhad pro hledání momentů (přepis i render běží lokálně a nic nestojí). Počítá se s ~9 000 slovy za hodinu,
překryvem oken a výstupem ~3 500 tokenů na okno včetně uvažování modelu (≈ 36 tis. vstupních a 20 tis. výstupních tokenů na hodinu češtiny); čeština spotřebuje víc tokenů než angličtina.
Ceny Anthropic (listopad 2026): Haiku 5.5 $0.10 / $0.50, Sonnet 5.5 $2 / $10 za 1M vstupních / výstupních tokenů.

| Model | 1 h česky | 1 h anglicky |
|---|---|---|
| `claude-haiku-5-5` | ~$0.014 | ~$0.012 |
| `claude-sonnet-5-5` | ~$0.27 | ~$0.25 |
| Ollama (lokálně) | $0 (elektřina) | $0 |

Skutečnou spotřebu tokenů a cenu vidíte u každého projektu, odhad i v Nastavení. Ceny ověřujte na
<https://www.anthropic.com/pricing>.

## Architektura

```
frontend (Next.js 15, App Router, TS, Tailwind 4, shadcn/ui)   :3000
   └─ /api/* proxy ──► api (FastAPI)                          :8000
                         ├─ PostgreSQL (SQLAlchemy + Alembic)
                         ├─ Redis ──► worker (RQ, fronta "process"): přepis, LLM, reframing, render
                         │        └─► render-worker (RQ, fronta "render"): úpravy z editoru, ZIP
                         └─ úložiště (lokální disk přes abstrakci app/storage.py → později S3/R2)
volitelně: ollama (profil `ollama`), worker-gpu (profil `gpu`)
```

Rozhodnutí a jejich důvody:

- **RQ místo Celery** – jednodušší, pro dva typy úloh stačí; dvě fronty, aby úpravy z editoru nečekaly
  za několikahodinovým zpracováním jiného projektu.
- **SSE** pro průběh – jednosměrný stream stačí, funguje přes Next.js proxy a automaticky se obnoví.
- **Frontend proxyuje `/api`** – stejný origin, takže session je v httpOnly cookie (žádný token v JS).
- **YuNet + MediaPipe** – samotný MediaPipe FaceLandmarker má detektor jen pro blízké obličeje (selfie) a
  v širokém záběru podcastu obličeje nenajde; YuNet je najde a MediaPipe na výřezu měří ústa.
  MediaPipe se instaluje bez závislostí `jax/scipy` (~450 MB), které detektor nepotřebuje.
- **Emoji jako PNG overlay** – libass neumí barevné fonty.
- **Náhled v editoru** kreslí ořez do `<canvas>` podle dráhy kamery, kterou vrací backend (`/api/clips/{id}/plan`,
  stejný kód jako render), a titulky skládá z téhož JSONu; logika seskupování slov je zrcadlena v
  `frontend/src/lib/captions.ts` ↔ `backend/app/pipeline/captions.py`.
- Adresář `certs/` umožňuje přidat CA certifikát firemní TLS proxy do buildů (jinak není potřeba).

Struktura:

```
clipforge/
├─ backend/        FastAPI, worker, pipeline (app/pipeline/*), LLM vrstva (app/llm/*), testy, Alembic
├─ frontend/       Next.js aplikace, Playwright E2E (e2e/)
├─ shared/         caption-presets.json, emoji-keywords.json, fonty (OFL)
├─ scripts/        generátor testovacích videí (Piper TTS + obličeje s pohybem úst)
├─ docker-compose.yml, .env.example, PLAN.md, CLAUDE.md
```

## Vývoj a testy

Backend (Python 3.12, FFmpeg s libass):

```bash
cd clipforge/backend
python3.12 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/pip install --no-deps -r requirements-mediapipe.txt
.venv/bin/pytest -q                 # 63 testů: zarovnání, dedup, ASS/SRT + diakritika, JSON, poskytovatelé, FFmpeg, API
.venv/bin/ruff check . && .venv/bin/mypy app
```

Lokální běh bez Dockeru (Postgres + Redis musí běžet):

```bash
.venv/bin/alembic upgrade head
.venv/bin/uvicorn app.main:app --reload
.venv/bin/python -m app.worker
```

Frontend:

```bash
cd clipforge/frontend
npm ci
npm run dev                         # API_URL=http://localhost:8000
npm run lint && npx tsc --noEmit && npm run build
```

E2E (běžící stack, testovací video):

```bash
python scripts/make_test_media.py --help                   # vygeneruje testovací videa (viz hlavička skriptu)
cd frontend && npx playwright test                          # E2E_VIDEO=..., E2E_BASE_URL=...
```

## Známá omezení

- **Rychlost na CPU**: Whisper large-v3 na CPU zpracuje 2h podcast za několik hodin. Pro produkci doporučujeme GPU
  nebo `large-v3-turbo`.
- **Aktivní mluvčí** se určuje z pohybu úst; nefunguje u mluvčích z profilu, s rukou u úst nebo mimo záběr
  (pak kamera zůstává na posledním mluvčím / největším obličeji). Diarizace podle hlasu není implementovaná.
- **Odstranění ticha/vycpávek** se v živém náhledu editoru nezobrazuje, projeví se až ve vyrenderovaném videu.
- **Emoji** v náhledu používají systémový emoji font prohlížeče, ve videu Noto Color Emoji – vzhled se mírně liší.
- Náhled titulků je věrná CSS rekonstrukce ASS výstupu; drobné rozdíly v řádkování a vykreslení obrysu jsou možné.
- Import z odkazu závisí na yt-dlp a podmínkách dané služby; některé weby stahování blokují.
- Úložiště je zatím jen lokální disk (rozhraní je připravené na S3/R2).
- Autentizace je jednoduchá (e-mail + heslo, bez ověření e-mailu a obnovy hesla).
