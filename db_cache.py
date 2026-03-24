"""
Cache pro Instagram databázi médií.

Synchronizace z telefonu probíhá pouze jednou za spuštění bota pro každé
zařízení zvlášť. Databáze vyžaduje root přístup na zařízení.
"""

from get_media_id import (
    sync_instagram_db, get_cached_media_info,
    sync_clips_db, get_clips_media_info,
    sync_user_reel_medias_db, get_user_reel_medias_info,
    sync_http_response_cache, get_http_cache_media_info,
)


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


def refresh_db_cache(serial_number: str = None, device_prefix: str = ""):
    """
    Obnoví obsah cache databáze ze zařízení.

    Vhodné volat po procházení nových Reels, aby se načetly aktuální záznamy.
    """
    global _db_cache

    prefix = f"[{device_prefix}] " if device_prefix else ""
    cache_key = serial_number or "default"
    db_path = sync_instagram_db(serial_number)

    _db_cache.setdefault(cache_key, {"synced": False, "media_list": []})

    combined: list = []

    if db_path:
        combined.extend(get_cached_media_info(db_path))

    # Sekundární zdroj: clips.db (obsahuje videa, která flash_media nemá)
    clips_path = sync_clips_db(serial_number)
    if clips_path:
        clips_entries = get_clips_media_info(clips_path)
        existing_codes = {m.get("code") for m in combined if m.get("code")}
        for entry in clips_entries:
            if entry.get("code") not in existing_codes:
                combined.append(entry)
                existing_codes.add(entry["code"])

    # Terciární zdroj: user_reel_medias_room_db (reely sledovaných uživatelů – přímý shortcode)
    urm_path = sync_user_reel_medias_db(serial_number)
    if urm_path:
        urm_entries = get_user_reel_medias_info(urm_path)
        existing_codes = {m.get("code") for m in combined if m.get("code")}
        for entry in urm_entries:
            if entry.get("code") not in existing_codes:
                combined.append(entry)
                existing_codes.add(entry["code"])

    # Kvarterní zdroj: HTTP response cache – Instagram cachuje API odpovědi se všemi videi
    http_dir = sync_http_response_cache(serial_number)
    if http_dir:
        http_entries = get_http_cache_media_info(http_dir)
        existing_codes = {m.get("code") for m in combined if m.get("code")}
        for entry in http_entries:
            if entry.get("code") not in existing_codes:
                combined.append(entry)
                existing_codes.add(entry["code"])

    if combined:
        # Akumuluj – přidej jen záznamy, které v cache ještě nejsou
        existing = _db_cache[cache_key]["media_list"]
        existing_keys = {m.get("code") or m.get("full_id") for m in existing}
        new_count = 0
        for entry in combined:
            key = entry.get("code") or entry.get("full_id")
            if key and key not in existing_keys:
                existing.append(entry)
                existing_keys.add(key)
                new_count += 1
        if new_count > 0:
            total = len(existing)
            print(f"{prefix}  [DB] +{new_count} nových médií (celkem {total}).")


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
            # Kolaborativní Reely mají username ve formátu "X and Y" – zkus každé zvlášť
            candidates = [u.strip() for u in username.split(" and ")] if " and " in username else [username]
            for candidate in candidates:
                for media in media_list:
                    if media.get("username", "").lower() == candidate.lower():
                        return media
            return None  # Username zadán, ale nenalezen – nevracet náhodný starý záznam

        return max(media_list, key=lambda x: x.get("stored_time", 0), default=None)

    except Exception:
        return None
