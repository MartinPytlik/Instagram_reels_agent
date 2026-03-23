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
import time
import random
import uuid

_UUID_RE = re.compile(
    r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$',
    re.IGNORECASE,
)

from config import WATCH_TIME_AD_OR_OVERLAY
from db_cache import sync_db_once, refresh_db_cache
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
) -> list[dict]:
    """
    Procházení Reelů na zařízení – sledování, interakce a sběr metadat.

    Args:
        device:        uiautomator2 Device objekt
        num_reels:     Počet Reelů k procházení (0 nebo záporné = neomezeně)
        device_prefix: Název zařízení pro výpisy konzole
        serial_number: Sériové číslo zařízení (pro synchronizaci DB)
        session_id:    ID sezení pro prediktor

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

    while True:
        if not infinite and reel_index >= num_reels:
            break

        reel_index += 1

        if reel_index % 5 == 0:
            refresh_db_cache(serial_number)
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
        predicted = (
            get_predicted_actions(video_id, reel_info=reel_info, session_id=session_id)
            if video_id else []
        )

        if predicted:
            reel_info["predicted_actions"] = [a.to_string() for a in predicted]
            print(f"{prefix}  Akce prediktoru: {reel_info['predicted_actions']}")
            state = execute_actions(device, predicted, reel_info=reel_info, device_prefix=device_prefix)
            if state.get("did_skip"):
                continue
        else:
            # Fallback: sleduj celé video (nebo 10 s jako konzervativní odhad)
            raw_dur = reel_info.get("video_duration")
            watch_s = int(math.ceil(float(raw_dur))) if isinstance(raw_dur, (int, float)) and raw_dur > 0 else 10
            print(f"{prefix}  Sledování: {watch_s}s (prediktor nedostupný nebo bez video_id)")
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
    go_to_reels(device, device_name)

    reels_info = watch_and_interact(
        device,
        num_reels=num_reels,
        device_prefix=device_name,
        serial_number=serial_number,
        session_id=session_id,
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
    username = reel_info.get("username", "N/A")
    likes    = reel_info.get("likes_count")
    media_id = reel_info.get("media_id", "")

    parts = [f"@{username}"]
    if likes is not None:
        parts.append(f"{likes:,} likes")
    if media_id:
        parts.append(f"id={media_id}")

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
