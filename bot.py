"""
Hlavní logika Instagram Reels Bota.

Obsahuje:
  - watch_and_interact  – hlavní smyčka procházení Reelů
  - save_reels_data     – uložení dat do JSON souboru
  - run_bot_for_device  – kompletní workflow pro jedno zařízení
"""

import json
import math
import re
import threading
import time
import random
import uuid

_UUID_RE = re.compile(
    r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$',
    re.IGNORECASE,
)

from config import WATCH_TIME_AD_OR_OVERLAY, INSTAGRAM_PACKAGE
from db_cache import sync_db_once
from get_media_id import sync_proc_mem
from device_manager import connect_device
from instagram import (
    detect_ad_and_overlay,
    dismiss_overlay_safe,
    get_reel_info,
    go_to_reels,
    open_instagram,
    scroll_to_next_reel,
)
from predictor import execute_actions, get_predicted_actions


# ---------------------------------------------------------------------------
# Hlavní smyčka
# ---------------------------------------------------------------------------

def watch_and_interact(
    device,
    num_reels: int = 0,
    device_prefix: str = "",
    serial_number: str = None,
    session_id: str | None = None,
    mem_cache: list[dict] | None = None,
) -> list[dict]:
    """
    Procházení Reelů na zařízení – sledování, interakce a sběr metadat.

    Args:
        device:        uiautomator2 Device objekt
        num_reels:     Počet Reelů k procházení (0 nebo záporné = neomezeně)
        device_prefix: Název zařízení pro výpisy konzole
        serial_number: Sériové číslo zařízení (pro synchronizaci DB)
        session_id:    ID sezení pro prediktor
        mem_cache:     Počáteční shortcody z paměti (zachycené po startu Instagramu)

    Returns:
        list[dict]: Metadata o všech procházených Reelech
    """
    prefix = f"[{device_prefix}] " if device_prefix else ""
    infinite = not num_reels or num_reels <= 0
    mode = "neomezeně (ukonči Ctrl+C)" if infinite else str(num_reels)
    print(f"{prefix}Začínám procházet Reels ({mode})...")

    sync_db_once(serial_number, device_prefix)

    all_reels: list[dict] = []
    reel_index = 0
    # Sleduje shortcody již odeslané prediktoru – zabraňuje duplicitám
    _sent_ids: set[str] = set()

    # Lokální cache shortcodů z paměti (počáteční scan + průběžné rescany)
    _mem_cache: list[dict] = list(mem_cache or [])
    # Čas posledního live scan paměti (cooldown 60s – nová dávka přijde až kolem reelu 50+)
    _last_mem_scan_t: float = time.monotonic()

    while True:
        if not infinite and reel_index >= num_reels:
            break

        # Ověř, že Instagram stále běží v popředí (ne že jsme z něj vyskočili)
        try:
            if device.app_current().get("package") != INSTAGRAM_PACKAGE:
                print(f"{prefix}  Instagram není v popředí – znovu otevírám...")
                open_instagram(device, device_prefix, serial_number)
                go_to_reels(device, device_prefix)
                time.sleep(1.0)
        except Exception:
            pass

        reel_index += 1

        counter = f"{reel_index}/{num_reels}" if not infinite else str(reel_index)
        print(f"{prefix}[{counter}] Reel")

        time.sleep(0.5)

        # Detekce reklamy nebo overlaye
        ad_overlay = detect_ad_and_overlay(device)
        if ad_overlay["is_ad"] or ad_overlay["is_overlay"]:
            reel_info = _handle_ad_or_overlay(device, ad_overlay, reel_index, device_prefix, serial_number)
            all_reels.append(reel_info)
            _scroll_if_not_last(device, reel_index, num_reels, infinite)
            continue

        # Normální Reel
        reel_info = _collect_reel_info(device, serial_number, device_prefix, reel_index)
        all_reels.append(reel_info)

        video_id = reel_info.get("shortcode") or reel_info.get("media_id")
        # Přeskoč shortcode který jsme již odeslali (stará data z DB nebo paměti)
        if video_id and video_id in _sent_ids:
            video_id = None
        predicted = (
            get_predicted_actions(video_id, reel_info=reel_info, session_id=session_id)
            if video_id else []
        )
        if video_id and predicted:
            _sent_ids.add(video_id)

        if predicted:
            reel_info["predicted_actions"] = [a.to_string() for a in predicted]
            print(f"{prefix}  Akce prediktoru: {reel_info['predicted_actions']}")
            state = execute_actions(device, predicted, reel_info=reel_info, device_prefix=device_prefix)
            if state.get("did_skip"):
                continue
        else:
            raw_dur = reel_info.get("video_duration")
            watch_s = int(math.ceil(float(raw_dur))) if isinstance(raw_dur, (int, float)) and raw_dur > 0 else 10

            if not video_id:
                # Shortcode chybí – zkus zásobu z paměti.
                # OkHttp buffer je čerstvý jen ~2 min po API dotazu; live scan tedy
                # spouštíme max jednou za 60s (aby nezpomaloval mezi dávkami).
                mem_entries = [e for e in _mem_cache if e["code"] not in _sent_ids]
                if not mem_entries and time.monotonic() - _last_mem_scan_t > 60:
                    print(f"{prefix}  Shortcode nenalezen – scanuju paměť procesu (~4s)...")
                    fresh = sync_proc_mem(serial_number, timeout_s=8)
                    _last_mem_scan_t = time.monotonic()
                    known = {e["code"] for e in _mem_cache}
                    for e in fresh:
                        if e["code"] not in known:
                            _mem_cache.append(e)
                    mem_entries = [e for e in fresh if e["code"] not in _sent_ids]
                elif not mem_entries:
                    secs_left = int(60 - (time.monotonic() - _last_mem_scan_t))
                    print(f"{prefix}  Shortcode nenalezen (paměť prázdná, cooldown ještě {secs_left}s)")
                # Filtruj shortcody z paměti – přeskoč již použité (ochrana duplicit)
                mem_entries = [e for e in mem_entries if e["code"] not in _sent_ids]
                if mem_entries:
                    mem_entry = mem_entries[0]
                    video_id = mem_entry["code"]
                    _sent_ids.add(video_id)
                    reel_info["shortcode"] = video_id
                    # Doplň metadata z paměti (duration, username, likes…)
                    for key in ("video_duration", "username", "like_count", "comment_count"):
                        if key in mem_entry and not reel_info.get(key):
                            reel_info[key] = mem_entry[key]
                    # Přepočítej watch_s pokud jsme dostali duration z paměti
                    raw_dur = reel_info.get("video_duration")
                    watch_s = int(math.ceil(float(raw_dur))) if isinstance(raw_dur, (int, float)) and raw_dur > 0 else 10
                    print(f"{prefix}  [MEM] Shortcode: {video_id}  dur={watch_s}s")
                    # Zkus predikci s novými daty
                    predicted = get_predicted_actions(video_id, reel_info=reel_info, session_id=session_id)
                    if predicted:
                        reel_info["predicted_actions"] = [a.to_string() for a in predicted]
                        print(f"{prefix}  Akce prediktoru (z paměti): {reel_info['predicted_actions']}")
                        state = execute_actions(device, predicted, reel_info=reel_info, device_prefix=device_prefix)
                        if state.get("did_skip"):
                            continue
                    else:
                        # Prediktor nedostupný nebo nerozhodl – sleduj celé video
                        print(f"{prefix}  Sledování: {watch_s}s (prediktor nedostupný)")
                        time.sleep(watch_s)
                else:
                    # Ani paměť nic nenašla – krátké neutrální sledování
                    print(f"{prefix}  Sledování: {watch_s}s (shortcode nenalezen ani v paměti)")
                    time.sleep(watch_s)
            else:
                print(f"{prefix}  Sledování: {watch_s}s (prediktor nedostupný)")
                time.sleep(watch_s)

        _print_reel_summary(prefix, reel_info)
        _scroll_if_not_last(device, reel_index, num_reels, infinite)

    print(f"{prefix}Hotovo – procházeno {reel_index} Reelů.")
    return all_reels


# ---------------------------------------------------------------------------
# Ukládání dat
# ---------------------------------------------------------------------------

def save_reels_data(reels_info: list[dict], filename: str = "reels_data.json", device_prefix: str = ""):
    """Uloží metadata o Reelech do JSON souboru."""
    prefix = f"[{device_prefix}] " if device_prefix else ""
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(reels_info, f, ensure_ascii=False, indent=2)
    print(f"{prefix}Data uložena do {filename}")


# ---------------------------------------------------------------------------
# Workflow pro jedno zařízení
# ---------------------------------------------------------------------------

def run_bot_for_device(
    serial_number: str,
    device_name: str,
    num_reels: int = 0,
    session_id: str | None = None,
):
    """
    Spustí kompletní workflow bota pro jedno zařízení.

    Kroky: připojení → Instagram → Reels → procházení → uložení dat

    Může být spuštěno v samostatném vlákně (threading.Thread).
    """
    if not session_id or not _UUID_RE.match(str(session_id)):
        session_id = str(uuid.uuid4())

    device = connect_device(serial_number, device_name)
    open_instagram(device, device_name, serial_number)

    # Počáteční scan paměti probíhá souběžně s navigací na Reels.
    # OkHttp buffer obsahuje odpověď API jen krátce po načtení feedu –
    # čím dřív scan začne, tím větší šance data zachytit.
    _initial_mem: list[dict] = []

    def _do_initial_mem_scan():
        time.sleep(5)  # Instagram potřebuje čas načíst feed a dokončit initial API dotaz
        _initial_mem.extend(sync_proc_mem(serial_number, timeout_s=18, exhaustive=True))

    _mem_thread = threading.Thread(target=_do_initial_mem_scan, daemon=True)
    _mem_thread.start()

    go_to_reels(device, device_name)

    # Počkej na dokončení scanu (sleep 5s + scan 18s = max 25s)
    _mem_thread.join(timeout=25)
    print(f"[{device_name}] Počáteční scan paměti: nalezeno {len(_initial_mem)} shortcodů.")
    initial_mem = _initial_mem

    reels_info = watch_and_interact(
        device,
        num_reels=num_reels,
        device_prefix=device_name,
        serial_number=serial_number,
        session_id=session_id,
        mem_cache=initial_mem,
    )

    filename = f"reels_data_{device_name.lower().replace(' ', '_')}.json"
    save_reels_data(reels_info, filename, device_name)

    _print_summary(device_name, reels_info)


# ---------------------------------------------------------------------------
# Privátní pomocné funkce
# ---------------------------------------------------------------------------

def _handle_ad_or_overlay(device, ad_overlay: dict, reel_index: int,
                          device_prefix: str, serial_number) -> dict:
    """Zpracuje detekovanou reklamu nebo overlay."""
    prefix = f"[{device_prefix}] " if device_prefix else ""
    label = "Reklama" if ad_overlay["is_ad"] else "Overlay"
    wait = WATCH_TIME_AD_OR_OVERLAY[0]

    print(f"{prefix}  {label} – {wait:.1f}s (přeskakuji bez interakce)")
    time.sleep(wait)

    reel_info = get_reel_info(device, serial_number, device_prefix)
    reel_info.update({
        "reel_number":   reel_index,
        "device_prefix": device_prefix,
        "is_ad":         ad_overlay["is_ad"],
        "is_overlay":    ad_overlay["is_overlay"],
        "ad_data":       ad_overlay.get("ad_data"),
        "overlay_data":  ad_overlay.get("overlay_data"),
    })

    if ad_overlay["is_overlay"]:
        dismiss_overlay_safe(device)
        time.sleep(0.2)

    return reel_info


def _collect_reel_info(device, serial_number, device_prefix: str, reel_index: int) -> dict:
    """Získá a vrátí metadata aktuálního Reelu."""
    reel_info = get_reel_info(device, serial_number, device_prefix)
    reel_info["reel_number"]   = reel_index
    reel_info["device_prefix"] = device_prefix
    reel_info["is_ad"]         = False
    reel_info["is_overlay"]    = False

    # U prvního Reelu občas UI ještě nenačetlo username – zkus znovu
    if not reel_info.get("username") and reel_index == 1:
        time.sleep(1)
        reel_info = get_reel_info(device, serial_number, device_prefix)
        reel_info["reel_number"]   = reel_index
        reel_info["device_prefix"] = device_prefix

    return reel_info


def _scroll_if_not_last(device, reel_index: int, num_reels: int, infinite: bool):
    """Scrollne na další Reel pokud ještě nejsme na posledním."""
    if infinite or reel_index < num_reels:
        scroll_to_next_reel(device)
        time.sleep(random.uniform(0.05, 0.15))


def _print_reel_summary(prefix: str, reel_info: dict):
    """Vypíše stručné info o právě zpracovaném Reelu."""
    username = reel_info.get("username")
    likes    = reel_info.get("likes_count")

    parts = []
    if username:
        parts.append(f"@{username}")
    if likes is not None:
        parts.append(f"{likes:,} likes")

    if parts:
        print(f"{prefix}  " + " | ".join(parts))


def _print_summary(device_name: str, reels_info: list[dict]):
    """Vypíše souhrnnou tabulku po dokončení procházení."""
    prefix = f"[{device_name}] "
    print(f"\n{prefix}{'=' * 50}")
    print(f"{prefix}SOUHRN – {len(reels_info)} Reelů")
    print(f"{prefix}{'=' * 50}")
    for reel in reels_info:
        username  = reel.get("username", "N/A")
        likes     = reel.get("likes_count", "N/A")
        likes_str = f"{likes:,}" if isinstance(likes, int) else str(likes)
        print(f"{prefix}  #{reel['reel_number']}: @{username} | {likes_str} likes")
    print(f"{prefix}{'=' * 50}")
