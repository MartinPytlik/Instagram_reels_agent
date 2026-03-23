# Instagram Reels Bot

Automatizovaný bot pro procházení Instagram Reels na fyzických Android zařízeních přes USB. Bot ovládá telefon pomocí UI automace, sbírá metadata videí a na základě doporučení externího prediktoru provádí akce (like, save, přeskočení, sledování po dobu X sekund).

---

## Obsah

- [Jak to funguje](#jak-to-funguje)
- [Požadavky](#požadavky)
- [Instalace](#instalace)
- [Konfigurace](#konfigurace)
- [Spuštění](#spuštění)
- [Struktura projektu](#struktura-projektu)
- [Popis modulů](#popis-modulů)
- [Výstupní data](#výstupní-data)
- [Diagnostika](#diagnostika)

---

## Jak to funguje

```
Android telefon (USB)
        │
        │  ADB + uiautomator2
        ▼
  device_manager.py  ──►  Připojení, odemčení obrazovky
        │
        ▼
   instagram.py      ──►  Spuštění Instagramu, navigace na Reels
        │
        ▼
     bot.py          ──►  Hlavní smyčka: čtení UI, scroll, interakce
        │                      │
        │                      ▼
        │             get_media_id.py  ──►  Sync Instagram DB (root)
        │             db_cache.py     ──►  Cache metadat videí
        │
        ▼
   predictor.py      ──►  API volání → doporučené akce
        │
        ▼
  Výstup: reels_data_<zařízení>.json
```

1. Bot se připojí k telefonům přes USB a ADB.
2. Otevře Instagram a přejde na sekci Reels.
3. Pro každé video získá metadata z UI hierarchie (username, likes, komentáře) a doplní je z Instagram SQLite databáze na rootnutém telefonu (media_id, shortcode, délka videa, hashtagy).
4. Metadata odešle na prediktor API, které vrátí doporučené akce.
5. Bot akce provede (like, uložení, sledování po danou dobu, přeskok).
6. Vše zaznamenává do JSON souboru.

---

## Požadavky

### Software
- **Python 3.11+**
- **Android Debug Bridge (ADB)** – součást [Android SDK Platform Tools](https://developer.android.com/tools/releases/platform-tools)

### Python balíčky
```
uiautomator2>=3.0.0
requests>=2.31.0
```

### Telefony
- Android zařízení s **povoleným USB debuggingem**
- Nainstalovaný Instagram
- **Root přístup** pro čtení Instagram databáze médií (získání media_id a shortcode)
- Nainstalovaný uiautomator2 server na telefonu

### Prediktor (volitelné)
REST API dostupné na `http://localhost:8000/api/predict_actions` (nebo jiné URL nastavené přes env. proměnnou). Pokud prediktor není dostupný, bot sleduje každé video po dobu jeho délky.

---

## Instalace

### 1. Nainstaluj Python závislosti

```bash
pip install -r requirements.txt
```

### 2. Nainstaluj ADB

Stáhni [Android SDK Platform Tools](https://developer.android.com/tools/releases/platform-tools), rozbal a přidej složku do `PATH`.

Ověř instalaci:
```bash
adb version
```

### 3. Připrav telefony

Na každém telefonu:
1. **Nastavení → O telefonu** – klikej 7× na „Číslo sestavení" pro aktivaci vývojářského režimu
2. **Nastavení → Možnosti vývojáře** – zapni „USB debugging"
3. Připoj telefon USB kabelem a povol popup „Povolit USB debugging?"
4. Inicializuj uiautomator2 server:

```bash
python -m uiautomator2 init
```

### 4. Ověř připojení

```bash
adb devices
```

Nebo spusť diagnostický skript:
```bash
python check_devices.py
```

---

## Konfigurace

Upraví soubor `config.py`:

```python
# Sériová čísla telefonů (zjistíš přes: adb devices)
DEVICES = [
    {"serial": "R58Y90R811Y", "name": "Device1"},
    {"serial": "R58Y90R6JWV", "name": "Device2"},
]
```

### Proměnné prostředí

| Proměnná | Výchozí hodnota | Popis |
|---|---|---|
| `PREDICTOR_URL` | `http://localhost:8000/api/predict_actions` | URL prediktor API |
| `PREDICTOR_ENABLED` | `1` | Zapnutí/vypnutí prediktoru (`0` = vypnuto) |
| `PREDICTOR_TIMEOUT_S` | `60` | Timeout volání prediktoru v sekundách |

Příklad:
```bash
set PREDICTOR_URL=http://192.168.1.10:8000/api/predict_actions
set PREDICTOR_ENABLED=0
```

---

## Spuštění

```bash
# Obě zařízení, neomezeně Reelů
python reels_bot.py

# Jen jedno zařízení
python reels_bot.py --device Device1
python reels_bot.py --device R58Y90R811Y

# Omezený počet Reelů (50 na každém zařízení)
python reels_bot.py --reels 50

# Vlastní session ID pro prediktor
python reels_bot.py --session-id 550e8400-e29b-41d4-a716-446655440000

# Kombinace parametrů
python reels_bot.py --device Device1 --reels 100
```

Bot se ukončí klávesovou zkratkou **Ctrl+C**.

---

## Struktura projektu

```
RealsyBOt/
│
├── reels_bot.py          # Vstupní bod – argparse a spuštění
├── config.py             # Konfigurace (URL, zařízení, časování)
├── models.py             # Datové modely (PredictedAction, PredictedActionType)
│
├── device_manager.py     # Správa ADB připojení k zařízením
├── instagram.py          # Ovládání Instagram UI (navigace, gesta, sběr dat)
├── db_cache.py           # Cache Instagram databáze médií
├── predictor.py          # Volání prediktor API a provádění akcí
├── bot.py                # Hlavní smyčka procházení Reelů
│
├── get_media_id.py       # Synchronizace Instagram SQLite DB z telefonu
├── check_devices.py      # Diagnostický nástroj pro ADB problémy
│
├── requirements.txt      # Python závislosti
│
├── reels_data_device1.json   # Ukázka výstupních dat (Device1)
└── reels_data_device2.json   # Ukázka výstupních dat (Device2)
```

---

## Popis modulů

### `reels_bot.py`
Vstupní bod programu. Zpracovává argumenty příkazové řádky (`--device`, `--reels`, `--session-id`) a spouští vlákna pro každé zařízení paralelně.

### `config.py`
Centrální konfigurace – sériová čísla zařízení, URL prediktoru, časové rozsahy sledování videí.

### `models.py`
Datové modely sdílené napříč projektem:
- `PredictedActionType` – výčet typů akcí (`like`, `save`, `skip`, `finish_watching`, `continue_watching`, `rewatch`)
- `PredictedAction` – jedna akce s volitelnou délkou trvání

### `device_manager.py`
Správa fyzických zařízení:
- Zjišťování dostupných zařízení přes ADB
- Testování ADB spojení
- Připojení přes uiautomator2 a odemčení obrazovky

### `instagram.py`
Celé ovládání Instagram aplikace:
- Spuštění aplikace a navigace na Reels
- Scroll na další video (Bezierovo gesto pro přirozenější pohyb)
- Like (double-click), Save (bookmark), Follow
- Detekce reklam a overlayů
- Sběr metadat z UI hierarchie (username, likes, komentáře, audio)

### `db_cache.py`
Správa lokální cache Instagram SQLite databáze médií. Synchronizace z telefonu probíhá jednou na začátku pro každé zařízení zvlášť.

### `predictor.py`
Komunikace s prediktor API:
- Sestavení payloadu z metadat videa
- Parsování odpovědi na `PredictedAction` objekty
- Provedení doporučených akcí na zařízení

### `bot.py`
Hlavní logika bota:
- Smyčka procházení Reelů s detekcí reklam
- Fallback chování při nedostupném prediktoru
- Uložení výsledků do JSON souboru
- Souhrn po dokončení

### `get_media_id.py`
Synchronizace Instagram interní SQLite databáze z rootnutého telefonu. Databáze obsahuje metadata přehrávaných videí (media_id, shortcode, délka, hashtagy, počty liků a komentářů). Data jsou komprimována pomocí zlib/gzip.

### `check_devices.py`
Samostatný diagnostický skript pro řešení problémů s připojením telefonů přes ADB.

---

## Výstupní data

Bot ukládá metadata každého zobrazeného Reelu do JSON souboru `reels_data_<zařízení>.json`.

Příklad záznamu:

```json
{
  "username": "example_user",
  "description": "Popis videa #tag",
  "likes_count": 12543,
  "comments_count": 87,
  "shares_count": 34,
  "audio_name": "Název skladby • Interpret",
  "is_liked": true,
  "media_id": "3123456789012345678",
  "shortcode": "CxYzAbCdEfG",
  "reel_url": "https://www.instagram.com/reel/CxYzAbCdEfG/",
  "hashtags": ["tag1", "tag2"],
  "video_duration": 15.0,
  "predicted_actions": ["continue_watching_for: 15 seconds", "like"],
  "reel_number": 1,
  "is_ad": false,
  "timestamp": "2025-03-15T14:32:01.123456"
}
```

---

## Diagnostika

**Žádná zařízení nenalezena:**
```bash
python check_devices.py
```

**Ruční restart ADB:**
```bash
adb kill-server
adb start-server
adb devices
```

**Inicializace uiautomator2 na telefonu:**
```bash
adb -s <serial> shell python -m uiautomator2 init
# nebo
python -m uiautomator2 init --serial <serial>
```

**Spuštění jen na jednom zařízení pro testování:**
```bash
python reels_bot.py --device Device1 --reels 5
```
