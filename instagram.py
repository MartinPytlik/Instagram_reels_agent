"""
Ovládání Instagram aplikace přes uiautomator2.

Zahrnuje:
  - spuštění a navigaci (open_instagram, go_to_reels, go_back_to_reels, is_on_reels)
  - interakce s Reely (scroll_to_next_reel, like_reel, save_reel, follow_current_creator)
  - detekci reklam a overlayů (detect_ad_and_overlay, dismiss_overlay_safe)
  - sběr metadat (get_reel_info)
  - pomocná gesta (Bezierova křivka)
"""

import re
import subprocess
import time
import random
from datetime import datetime

from config import INSTAGRAM_PACKAGE


# ---------------------------------------------------------------------------
# Gesto – Bezierova křivka
# ---------------------------------------------------------------------------

def _bezier_curve(start: tuple, control: tuple, end: tuple, steps: int) -> list[tuple]:
    """Vrátí seznam bodů na kvadratické Bezierově křivce."""
    points = []
    for i in range(steps + 1):
        t = i / steps
        x = (1 - t) ** 2 * start[0] + 2 * (1 - t) * t * control[0] + t ** 2 * end[0]
        y = (1 - t) ** 2 * start[1] + 2 * (1 - t) * t * control[1] + t ** 2 * end[1]
        points.append((int(x), int(y)))
    return points


def _random_point(zone: dict) -> tuple:
    """Vrátí náhodný bod uvnitř definované zóny."""
    return (
        int(random.uniform(zone["x1"], zone["x2"])),
        int(random.uniform(zone["y1"], zone["y2"])),
    )


def _get_control_point(start: tuple, end: tuple) -> tuple:
    """Vrátí control point pro Bezierovu křivku (mírně doleva od středu)."""
    mid_x = (start[0] + end[0]) // 2
    mid_y = (start[1] + end[1]) // 2
    return (mid_x + random.randint(-60, -30), mid_y + random.randint(-20, 20))


# ---------------------------------------------------------------------------
# Spuštění a navigace
# ---------------------------------------------------------------------------

def open_instagram(device, device_prefix: str = "", serial_number: str = None):
    """
    Spustí aplikaci Instagram na zařízení.

    Raises:
        RuntimeError: Pokud se Instagram nepodaří spustit po třech pokusech.
    """
    prefix = f"[{device_prefix}] " if device_prefix else ""
    print(f"{prefix}Otevírám Instagram...")

    _verify_instagram_installed(serial_number, prefix)

    for attempt in range(3):
        try:
            device.app_start(INSTAGRAM_PACKAGE)
            time.sleep(3)
            if device.app_current().get("package") == INSTAGRAM_PACKAGE:
                print(f"{prefix}Instagram spuštěn.")
                return
            if attempt < 2:
                device.app_stop(INSTAGRAM_PACKAGE)
                time.sleep(1)
                _launch_via_monkey(serial_number)
        except Exception:
            if attempt < 2:
                time.sleep(2)

    # Poslední pokus přes 'am start'
    try:
        _launch_via_am_start(serial_number)
        time.sleep(3)
        if device.app_current().get("package") == INSTAGRAM_PACKAGE:
            return
    except Exception:
        pass

    raise RuntimeError(f"Nelze otevřít Instagram na {device_prefix or serial_number}.")


def go_to_reels(device, device_prefix: str = ""):
    """Přejde na sekci Reels a ověří, že se navigace zdařila."""
    prefix = f"[{device_prefix}] " if device_prefix else ""

    if is_on_reels(device):
        return

    print(f"{prefix}Přecházím na Reels...")

    # Selektory cílí výhradně na navigační tab (resource ID), nikoli na nadpisy stránek.
    # Generické text/description selektory záměrně chybí – zachytily by "Reels" nadpis nahoře.
    _REELS_TAB_SELECTORS = [
        {"resourceIdMatches": ".*reels_tab.*"},
        {"resourceIdMatches": ".*clips_tab.*"},
        {"resourceId": "com.instagram.android:id/clips_tab"},
        {"resourceId": "com.instagram.android:id/reels_tab"},
    ]

    def _click_reels_tab():
        w, h = device.window_size()
        for selector in _REELS_TAB_SELECTORS:
            try:
                el = device(**selector)
                if el.exists(timeout=2):
                    # Ověř, že element je v dolní navigační liště (spodních 15 % obrazovky)
                    info = el.info
                    bounds = info.get("bounds", {})
                    center_y = (bounds.get("top", 0) + bounds.get("bottom", h)) // 2
                    if center_y > h * 0.80:
                        el.click()
                        return True
            except Exception:
                continue
        # Fallback: střed dolní navigační lišty
        device.click(w // 2, h - 80)
        return False

    # Pokus 1 – klikni a čekej až 6s na načtení prvního Reelu (polling)
    _click_reels_tab()
    if is_on_reels(device, wait_s=6.0):
        return

    # Pokus 2 – Reely se ještě nenačetly, zkus znovu
    _click_reels_tab()
    is_on_reels(device, wait_s=5.0)


def go_back_to_reels(device) -> bool:
    """
    Pokusí se vrátit na sekci Reels.

    Returns:
        True pokud se navigace zdaří, jinak False.
    """
    w, h = device.window_size()

    try:
        # Klikni přímo na střed dolní navigační lišty (Reels tab je typicky uprostřed)
        device.click(w // 2, h - 80)
        if is_on_reels(device, wait_s=3.0):
            return True

        # Zkus resource-ID selektory (jen navigační tab, ne nadpisy)
        for selector in [
            {"resourceIdMatches": ".*reels_tab.*"},
            {"resourceIdMatches": ".*clips_tab.*"},
            {"resourceId": "com.instagram.android:id/clips_tab"},
        ]:
            try:
                el = device(**selector)
                if el.exists(timeout=1):
                    info = el.info
                    bounds = info.get("bounds", {})
                    center_y = (bounds.get("top", 0) + bounds.get("bottom", h)) // 2
                    if center_y > h * 0.80:
                        el.click()
                        if is_on_reels(device, wait_s=2.0):
                            return True
            except Exception:
                continue

        return is_on_reels(device)

    except Exception as e:
        print(f"Chyba při návratu na Reels: {e}")

    return False


def is_on_reels(device, wait_s: float = 0.0) -> bool:
    """
    Vrátí True pokud je zařízení aktuálně na sekci Reels.

    Args:
        wait_s: Pokud > 0, polling dokud se Reels neobjeví nebo timeout.
                Vhodné hned po navigaci, kdy se UI ještě načítá.
    """
    deadline = time.monotonic() + wait_s
    while True:
        try:
            xml_str = device.dump_hierarchy()

            # Jasné negativní indikátory – homepage nebo Stories
            if re.search(r'content-desc="[^"]*Story[^"]*"', xml_str):
                return False
            for indicator in ("Suggested for you", "liked by"):
                if indicator in xml_str:
                    return False

            # Pozitivní indikátory (spolehlivé – vyskytují se pouze v Reels)
            if "Like number is" in xml_str:
                return True
            if 'content-desc="Unlike"' in xml_str:
                return True

        except Exception:
            pass

        if time.monotonic() >= deadline:
            break
        time.sleep(0.6)

    return False


# ---------------------------------------------------------------------------
# Interakce s Reely
# ---------------------------------------------------------------------------

def scroll_to_next_reel(device) -> bool:
    """Scrollne na další Reel pomocí Bezierova swipe gesta."""
    w, h = device.window_size()

    start = _random_point({"x1": int(w * 0.69), "y1": int(h * 0.79),
                            "x2": int(w * 0.74), "y2": int(h * 0.83)})
    end   = _random_point({"x1": int(w * 0.79), "y1": int(h * 0.51),
                            "x2": int(w * 0.83), "y2": int(h * 0.56)})
    control = _get_control_point(start, end)
    path = _bezier_curve(start, control, end, int(random.uniform(7, 12)))

    try:
        device.swipe_points(path, duration=random.uniform(0.02, 0.04))
    except Exception:
        device.swipe(start[0], start[1], end[0], end[1], duration=0.05)

    return True


def like_reel(device, device_prefix: str = ""):
    """Likuje aktuální Reel double-clickem mírně vpravo od středu."""
    prefix = f"[{device_prefix}] " if device_prefix else ""
    w, h = device.window_size()
    device.double_click(int(w * 0.58), int(h * 0.45), duration=0.1)
    print(f"{prefix}  Reel olikován.")


def save_reel(device, device_prefix: str = "") -> bool:
    """
    Uloží aktuální Reel (bookmark).

    Returns:
        True pokud bylo kliknuto na tlačítko Save.
    """
    prefix = f"[{device_prefix}] " if device_prefix else ""
    for sel in [
        {"description": "Save"},      {"descriptionContains": "Save"}, {"text": "Save"},
        {"description": "Uložit"},    {"descriptionContains": "Uložit"}, {"text": "Uložit"},
    ]:
        try:
            el = device(**sel)
            if el.exists(timeout=0.2):
                el.click()
                print(f"{prefix}  Reel uložen.")
                return True
        except Exception:
            continue

    # Fallback – klikni na pozici ikony bookmark
    try:
        w, h = device.window_size()
        device.click(int(w * 0.92), int(h * 0.76))
        return True
    except Exception:
        return False


def follow_current_creator(device, device_prefix: str = "") -> bool:
    """
    Klikne na tlačítko Follow (Sledovat).

    Returns:
        True pokud bylo kliknuto.
    """
    prefix = f"[{device_prefix}] " if device_prefix else ""
    for sel in [
        {"text": "Follow"},        {"text": "Sledovat"},
        {"description": "Follow"},  {"descriptionContains": "Follow"},
    ]:
        try:
            el = device(**sel)
            if el.exists(timeout=0.2):
                el.click()
                print(f"{prefix}  Sledován.")
                return True
        except Exception:
            continue
    return False


# ---------------------------------------------------------------------------
# Reklamy a overlaye
# ---------------------------------------------------------------------------

def detect_ad_and_overlay(device) -> dict:
    """
    Detekuje reklamu nebo overlay (Threads, „Open in App" dialog, apod.).

    Returns:
        dict s klíči:
          is_ad (bool), ad_data (dict | None),
          is_overlay (bool), overlay_data (dict | None)
    """
    result = {"is_ad": False, "ad_data": None, "is_overlay": False, "overlay_data": None}

    try:
        xml_str = device.dump_hierarchy()
        xml_lower = xml_str.lower()

        for pattern, reason in [
            ("Sponsored", "Sponsored"),
            ("Sponzorováno", "Sponzorováno"),
            ("Reklama", "Reklama"),
            ("sponsored", "sponsored"),
        ]:
            if pattern.lower() in xml_lower:
                result["is_ad"] = True
                result["ad_data"] = {"reason": reason, "timestamp": datetime.now().isoformat()}
                break

        # Speciální případ "Ad" – vyhnout se false positive z "Add"
        if not result["is_ad"]:
            if re.search(r"\bAd\b", xml_str) or 'content-desc="Ad"' in xml_str:
                result["is_ad"] = True
                result["ad_data"] = {"reason": "Ad", "timestamp": datetime.now().isoformat()}

        for pattern, reason in [
            ("Threads", "Threads"),
            ("Otevřít v aplikaci", "Open in app"),
            ("Open in App", "Open in app"),
            ("Get app", "Get app"),
            ("Stáhnout aplikaci", "Get app"),
            ("See more on Threads", "Threads"),
        ]:
            if pattern in xml_str or pattern.lower() in xml_lower:
                result["is_overlay"] = True
                result["overlay_data"] = {"reason": reason, "timestamp": datetime.now().isoformat()}
                break

    except Exception:
        pass

    return result


def dismiss_overlay_safe(device) -> bool:
    """
    Bezpečně zavře overlay tlačítkem zpět nebo swipe dolů.

    Returns:
        True pokud bylo provedeno nějaké gesto.
    """
    try:
        device.press("back")
        time.sleep(0.3)
        return True
    except Exception:
        pass
    try:
        w, h = device.window_size()
        device.swipe(w // 2, int(h * 0.6), w // 2, int(h * 0.4), duration=0.1)
        time.sleep(0.2)
        return True
    except Exception:
        pass
    return False


# ---------------------------------------------------------------------------
# Sběr metadat Reelu
# ---------------------------------------------------------------------------

# Slova UI prvků, která nechceme brát jako username
_UI_FILTER_WORDS: frozenset[str] = frozenset({
    "follow", "following", "sledovat", "message", "more", "like", "comment", "share",
    "instagram", "reels", "home", "search", "explore", "profile", "settings",
    "save", "uložit", "send", "poslat", "back", "zpět", "close", "zavřít",
    # Akce a UI prvky v CZ/EN lokalizaci Instagramu
    "repost", "repostovat", "remix", "remixovat", "add", "přidat",
    "sdílet", "report", "nahlásit", "not interested", "nezajímá",
    "audio", "zvuk", "effects", "efekty", "stickers", "nálepky",
    "profil", "profile", "story", "příběh", "reel", "video",
    "notifications", "oznámení", "activity", "aktivita",
})


def get_reel_info(device, serial_number=None, device_prefix: str = "") -> dict:
    """
    Získá metadata o aktuálně přehrávaném Reelu z UI hierarchie
    a doplní je z lokální cache databáze (pokud je dostupná).

    Returns:
        dict s klíči: username, description, likes_count, comments_count,
                      shares_count, audio_name, is_liked, media_id, timestamp, …
    """
    prefix = f"[{device_prefix}] " if device_prefix else ""
    info: dict = {
        "username":       None,
        "description":    None,
        "likes_count":    None,
        "comments_count": None,
        "reposts_count":  None,
        "shares_count":   None,
        "audio_name":     None,
        "is_liked":       False,
        "is_following":   False,
        "media_id":       None,
        "timestamp":      datetime.now().isoformat(),
    }

    try:
        xml_str = device.dump_hierarchy()

        info["username"] = _extract_username(xml_str)

        m = re.search(r"Like number is\s*(\d+)", xml_str)
        if m:
            info["likes_count"] = int(m.group(1))

        m = re.search(r"Comment number is\s*(\d+)", xml_str)
        if m:
            info["comments_count"] = int(m.group(1))

        m = re.search(r"Reshare number is\s*(\d+)", xml_str)
        if m:
            info["shares_count"] = int(m.group(1))

        if 'content-desc="Unlike"' in xml_str:
            info["is_liked"] = True

        m = re.search(r'content-desc="([^"]*•[^"]*)"', xml_str)
        if m:
            info["audio_name"] = m.group(1)

        for desc in re.findall(r'content-desc="([^"]{30,})"', xml_str):
            if not any(x in desc.lower() for x in
                       ("like", "comment", "share", "profile", "number is", "follow", "repost")):
                info["description"] = desc
                break

        _enrich_from_db(info, serial_number)

    except Exception as e:
        print(f"{prefix}Chyba při získávání info o Reelu: {e}")

    return info


# ---------------------------------------------------------------------------
# Privátní pomocné funkce
# ---------------------------------------------------------------------------

def _extract_username(xml_str: str) -> str | None:
    """Extrahuje username z XML UI hierarchie."""
    # Metoda 1: "Profile picture of {username}"
    m = re.search(r'Profile picture of ([^"]+)"', xml_str)
    if m:
        candidate = m.group(1).strip()
        if candidate.lower() not in _UI_FILTER_WORDS and len(candidate) > 1:
            return candidate

    # Metoda 2: hledej v atributech text / content-desc
    for pattern in (r'text="@?([a-zA-Z0-9._]+)"', r'content-desc="@?([a-zA-Z0-9._]+)"'):
        for m in re.finditer(pattern, xml_str):
            candidate = m.group(1).strip()
            if (candidate.lower() not in _UI_FILTER_WORDS
                    and 3 <= len(candidate) <= 30
                    and ("." in candidate or "_" in candidate or candidate.isalnum())):
                return candidate

    return None


def _enrich_from_db(info: dict, serial_number):
    """Doplní metadata z lokální cache databáze Instagram médií."""
    try:
        from db_cache import get_media_id_from_db, refresh_db_cache
        from get_media_id import get_reel_url

        username = info.get("username")
        if not username:
            return  # Bez username nelze spolehlivě spárovat s DB

        time.sleep(1.0)
        refresh_db_cache(serial_number)
        db_info = get_media_id_from_db(username, serial_number)

        if not db_info:
            # Instagram možná ještě nestačil zapsat do DB – krátký polling (max 2 s)
            for _ in range(4):
                time.sleep(0.5)
                refresh_db_cache(serial_number)
                db_info = get_media_id_from_db(username, serial_number)
                if db_info:
                    break

        if not db_info:
            return

        info["media_id"]      = db_info.get("pk") or db_info.get("media_id")
        info["shortcode"]     = db_info.get("code")
        info["reel_url"]      = get_reel_url(db_info)
        info["hashtags"]      = db_info.get("hashtags", [])
        info["video_duration"] = db_info.get("video_duration")

        if not info.get("likes_count") and db_info.get("like_count") is not None:
            info["likes_count"] = db_info["like_count"]
        if not info.get("comments_count") and db_info.get("comment_count") is not None:
            info["comments_count"] = db_info["comment_count"]
        if not info.get("description") and db_info.get("caption_text"):
            info["description"] = db_info["caption_text"]

    except Exception:
        pass


def _verify_instagram_installed(serial_number, prefix: str = ""):
    """Ověří, zda je Instagram nainstalovaný. Vyvolá RuntimeError pokud není."""
    try:
        adb_cmd = ["adb"]
        if serial_number:
            adb_cmd.extend(["-s", serial_number])
        result = subprocess.run(
            adb_cmd + ["shell", "pm", "list", "packages", "|", "grep", "instagram"],
            capture_output=True, text=True, timeout=5,
        )
        if INSTAGRAM_PACKAGE not in result.stdout:
            raise RuntimeError(f"Instagram není nainstalovaný na {prefix or 'zařízení'}.")
    except RuntimeError:
        raise
    except Exception:
        pass  # Nelze ověřit (timeout, ADB chyba) – pokračuj dál


def _launch_via_monkey(serial_number):
    """Spustí Instagram přes 'adb shell monkey'."""
    adb_cmd = ["adb"]
    if serial_number:
        adb_cmd.extend(["-s", serial_number])
    try:
        subprocess.run(
            adb_cmd + ["shell", "monkey", "-p", INSTAGRAM_PACKAGE,
                       "-c", "android.intent.category.LAUNCHER", "1"],
            timeout=5,
        )
        time.sleep(3)
    except Exception:
        pass


def _launch_via_am_start(serial_number):
    """Spustí Instagram přes 'adb shell am start'."""
    adb_cmd = ["adb"]
    if serial_number:
        adb_cmd.extend(["-s", serial_number])
    subprocess.run(
        adb_cmd + ["shell", "am", "start", "-n",
                   f"{INSTAGRAM_PACKAGE}/com.instagram.mainactivity.LauncherActivity"],
        timeout=5,
    )
