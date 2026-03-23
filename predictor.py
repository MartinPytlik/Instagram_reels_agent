"""
Integrace s prediktorovým API.

Prediktor na základě metadat videa doporučí sérii akcí (like, save, skip, …).
Pokud API není dostupné nebo vrátí chybu, funkce vrátí prázdný seznam a bot
použije výchozí (fallback) chování.
"""

import re
import math
import uuid
import time
import random

import requests

from config import PREDICTOR_URL, PREDICTOR_ENABLED, PREDICTOR_TIMEOUT_S
from models import PredictedAction, PredictedActionType
from instagram import like_reel, save_reel, scroll_to_next_reel


# Jedna requests.Session pro celý proces
_http_session: requests.Session = requests.Session()


# ---------------------------------------------------------------------------
# Veřejné funkce
# ---------------------------------------------------------------------------

def get_predicted_actions(
    video_id: str,
    reel_info: dict | None = None,
    session_id: str | None = None,
) -> list[PredictedAction]:
    """
    Zavolá prediktor API a vrátí seznam doporučených akcí.

    Args:
        video_id:   Shortcode nebo media_id videa
        reel_info:  Metadata Reelu (likes, duration, hashtags, …)
        session_id: ID sezení přiřazené danému zařízení v prediktoru

    Returns:
        Seznam PredictedAction objektů, nebo prázdný seznam při chybě / vypnutém prediktoru.
    """
    if not PREDICTOR_ENABLED or not video_id:
        return []

    reel_info = reel_info or {}
    payload = _build_payload(video_id, reel_info, session_id)

    try:
        resp = _http_session.post(PREDICTOR_URL, json=payload, timeout=PREDICTOR_TIMEOUT_S)
        resp.raise_for_status()
        data = resp.json()
        return _parse_response(data, video_id)
    except Exception as e:
        print(f"[Predictor] Chyba při volání API (video_id={video_id}): {e!r}")
        return []


def execute_actions(
    device,
    actions: list[PredictedAction],
    reel_info: dict | None = None,
    device_prefix: str = "",
) -> dict:
    """
    Provede akce doporučené prediktorem na zařízení.

    Args:
        device:        uiautomator2 Device objekt
        actions:       Seznam akcí k provedení
        reel_info:     Metadata aktuálního Reelu
        device_prefix: Prefix pro výpisy konzole

    Returns:
        dict {"did_skip": bool} – True pokud byla provedena akce SKIP
    """
    prefix = f"[{device_prefix}] " if device_prefix else ""
    state = {"did_skip": False}

    for action in actions:
        time.sleep(random.uniform(0.4, 1.2))
        at = action.action_type

        if at == PredictedActionType.LIKE:
            if not (reel_info and reel_info.get("is_liked")):
                like_reel(device, device_prefix)

        elif at == PredictedActionType.SAVE:
            save_reel(device, device_prefix)

        elif at == PredictedActionType.SKIP:
            scroll_to_next_reel(device)
            time.sleep(random.uniform(0.05, 0.15))
            state["did_skip"] = True
            break

        elif at in (
            PredictedActionType.FINISH_WATCHING,
            PredictedActionType.CONTINUE_WATCHING,
            PredictedActionType.REWATCH,
        ):
            duration = float(action.seconds) if action.seconds and action.seconds > 0 \
                       else random.uniform(2.0, 7.0)
            time.sleep(duration)

        else:
            print(f"{prefix}Neznámá akce od prediktoru: {action.to_string()}")

    return state


# ---------------------------------------------------------------------------
# Privátní pomocné funkce
# ---------------------------------------------------------------------------

def _normalise_description(text: str | None) -> str | None:
    """Sloučí víceodstavcový popisek do jednoho odstavce."""
    if not text:
        return text
    return " ".join(text.split())


def _build_payload(video_id: str, reel_info: dict, session_id: str | None) -> dict:
    """Sestaví tělo požadavku pro prediktor API."""
    raw_duration = reel_info.get("video_duration")
    video_duration = (
        int(math.ceil(float(raw_duration)))
        if isinstance(raw_duration, (int, float)) and raw_duration > 0
        else None
    )

    return {
        "session_id": session_id or str(uuid.uuid4()),
        "video_metadata": {
            "video_id":          str(video_id),
            "video_author":      reel_info.get("username"),
            "video_time_duration": video_duration,
            "description":       _normalise_description(reel_info.get("description")),
            "hashtags":          reel_info.get("hashtags", []),
            "likes_count":       reel_info.get("likes_count"),
            "comments_count":    reel_info.get("comments_count"),
            "reposts_count":     reel_info.get("reposts_count"),
            "shares_count":      reel_info.get("shares_count"),
        },
    }


def _parse_response(data: dict, video_id: str) -> list[PredictedAction]:
    """Parsuje odpověď API na seznam PredictedAction objektů."""
    raw_actions = data.get("predicted_actions", [])
    actions = []

    for item in raw_actions:
        raw_type, raw_seconds = _parse_item(item)
        if raw_type is None:
            continue

        action_type = _resolve_action_type(raw_type)
        if action_type is None:
            continue

        seconds = _parse_seconds(raw_seconds)
        actions.append(PredictedAction(action_type=action_type, seconds=seconds))

    if not actions:
        print(f"[Predictor] Žádné akce pro video_id={video_id}. Odpověď: {data!r}")

    return actions


def _parse_item(item) -> tuple:
    """
    Parsuje jeden záznam z 'predicted_actions'.

    Podporuje formáty:
      - "skip"
      - "continue_watching_for: 3 seconds"
      - {"action_type": "like", "seconds": 5}
    """
    if isinstance(item, str):
        m = re.match(r"^continue_watching_for:\s*(\d+)\s*seconds?", item.strip())
        if m:
            return "continue_watching", int(m.group(1))
        return item.strip(), None

    if isinstance(item, dict):
        return item.get("action_type") or item.get("action"), item.get("seconds")

    return None, None


def _resolve_action_type(raw_type: str) -> PredictedActionType | None:
    """Převede řetězec na PredictedActionType (case-insensitive)."""
    for candidate in (raw_type, str(raw_type).lower()):
        try:
            return PredictedActionType(candidate)
        except ValueError:
            continue
    print(f"[Predictor] Neznámý typ akce: {raw_type!r}")
    return None


def _parse_seconds(raw_seconds) -> int | None:
    """Převede hodnotu seconds na int, nebo vrátí None."""
    if raw_seconds is None:
        return None
    try:
        return int(float(raw_seconds))
    except (TypeError, ValueError):
        return None
