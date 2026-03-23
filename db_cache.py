"""
Cache pro Instagram databázi médií.

Synchronizace z telefonu probíhá pouze jednou za spuštění bota pro každé
zařízení zvlášť. Databáze vyžaduje root přístup na zařízení.
"""

from get_media_id import sync_instagram_db, get_cached_media_info


# Slovník {cache_key: {"synced": bool, "media_list": list}}
_db_cache: dict = {}


def sync_db_once(serial_number: str = None, device_prefix: str = ""):
    """
    Synchronizuje Instagram databázi z telefonu JEDNOU pro dané zařízení.

    Při opakovaném volání se synchronizace přeskočí (data jsou v cache).
    """
    global _db_cache

    prefix = f"[{device_prefix}] " if device_prefix else ""
    cache_key = serial_number or "default"

    if _db_cache.get(cache_key, {}).get("synced"):
        return

    _db_cache.setdefault(cache_key, {"synced": False, "media_list": []})

    print(f"{prefix}Synchronizuji databázi médií...")
    db_path = sync_instagram_db(serial_number)

    if db_path:
        _db_cache[cache_key]["media_list"] = get_cached_media_info(db_path)
        _db_cache[cache_key]["synced"] = True
        count = len(_db_cache[cache_key]["media_list"])
        print(f"{prefix}  Načteno {count} médií z databáze.")
    else:
        print(f"{prefix}  Synchronizace DB selhala (zařízení pravděpodobně nemá root přístup).")


def refresh_db_cache(serial_number: str = None):
    """
    Obnoví obsah cache databáze ze zařízení.

    Vhodné volat po procházení nových Reels, aby se načetly aktuální záznamy.
    """
    global _db_cache

    cache_key = serial_number or "default"
    db_path = sync_instagram_db(serial_number)

    if db_path:
        _db_cache.setdefault(cache_key, {"synced": False, "media_list": []})
        _db_cache[cache_key]["media_list"] = get_cached_media_info(db_path)


def get_media_id_from_db(username: str = None, serial_number: str = None) -> dict | None:
    """
    Vrátí metadata média z cache databáze.

    Pokud je zadán username, vrátí první záznam se shodným username.
    Jinak vrátí nejnovější záznam (podle stored_time).

    Returns:
        dict s metadaty nebo None pokud cache neobsahuje žádná data.
    """
    global _db_cache

    cache_key = serial_number or "default"

    try:
        media_list: list = _db_cache.get(cache_key, {}).get("media_list", [])

        if not media_list:
            return None

        if username:
            for media in media_list:
                if media.get("username", "").lower() == username.lower():
                    return media

        return max(media_list, key=lambda x: x.get("stored_time", 0), default=None)

    except Exception:
        return None
