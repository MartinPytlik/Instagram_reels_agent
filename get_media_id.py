"""
Modul pro získání media_id z Instagram databáze na rootnutém telefonu.
Vyžaduje root přístup na zařízení.
"""

import re
import subprocess
import sqlite3
import json
import os
import zlib
import gzip


def decompress_and_parse(data):
    """
    Dekomprimuje a parsuje data z databáze.
    Instagram používá zlib kompresi.
    
    Args:
        data: Komprimovaná binární data
    
    Returns:
        dict: Rozparsovaný JSON nebo None
    """
    if not data:
        return None
    
    # Pokus 1: Přímý JSON (nekomprimovaný)
    try:
        return json.loads(data)
    except Exception:
        pass

    # Pokus 2: ZLIB komprese
    try:
        decompressed = zlib.decompress(data)
        return json.loads(decompressed)
    except Exception:
        pass

    # Pokus 3: GZIP komprese
    try:
        decompressed = gzip.decompress(data)
        return json.loads(decompressed)
    except Exception:
        pass

    # Pokus 4: Raw DEFLATE (bez hlavičky)
    try:
        decompressed = zlib.decompress(data, -zlib.MAX_WBITS)
        return json.loads(decompressed)
    except Exception:
        pass

    # Pokus 5: ZLIB s wbits 31 (pro gzip)
    try:
        decompressed = zlib.decompress(data, zlib.MAX_WBITS | 16)
        return json.loads(decompressed)
    except Exception:
        pass
    
    return None


def _find_db_path_on_device(adb_cmd: list) -> str | None:
    """
    Dynamicky najde cestu k flash_media databázi na rootnutém zařízení.
    Prohledá adresář Instagram databází a vrátí první nalezený flash_media soubor.
    Ignoruje extra řádky (např. "Granted root access") v suproces výstupu.
    """
    db_dir = "/data/data/com.instagram.android/databases"

    # Regex: flash_media_ následované číslem – žádné přípony -wal/-shm/-journal
    pattern = re.compile(r'^(flash_media_\d+)$')

    for cmd in (
        adb_cmd + ['shell', f"su -c 'ls {db_dir}'"],
        adb_cmd + ['shell', f"su 0 ls {db_dir}"],
    ):
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            for line in result.stdout.splitlines():
                name = line.strip()
                if pattern.match(name):
                    return f"{db_dir}/{name}"
        except Exception:
            continue

    return None


def sync_clips_db(serial_number=None):
    """
    Stáhne clips.db z telefonu – sekundární zdroj metadat Reelů.

    Returns:
        str: Cesta k lokální clips.db nebo None při chybě
    """
    try:
        devnull = subprocess.DEVNULL
        adb_cmd = ['adb']
        if serial_number:
            adb_cmd.extend(['-s', serial_number])

        db_dir = "/data/data/com.instagram.android/databases"
        local_db = f"clips_{serial_number}.db" if serial_number else "clips.db"

        subprocess.run(
            adb_cmd + ['shell', f"su -c 'cp {db_dir}/clips.db /sdcard/clips_temp.db'"],
            stdout=devnull, stderr=devnull, timeout=10,
        )
        result = subprocess.run(
            adb_cmd + ['pull', '/sdcard/clips_temp.db', local_db],
            capture_output=True, timeout=15,
        )
        if result.returncode == 0 and os.path.exists(local_db):
            return local_db
    except Exception:
        pass
    return None


def get_clips_media_info(db_path: str) -> list:
    """
    Čte metadata z clips.db – schema se zjistí dynamicky.

    Returns:
        list: Záznamy s alespoň 'username' a 'code' (shortcode)
    """
    if not os.path.exists(db_path):
        return []

    media_list = []
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        tables = [r[0] for r in cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()]

        for table in tables:
            try:
                cols = [r[1] for r in cursor.execute(f"PRAGMA table_info({table})").fetchall()]
                useful = {'code', 'shortcode', 'pk', 'username', 'like_count',
                          'comment_count', 'video_duration'}
                select = [c for c in cols if c in useful]
                if not select or 'code' not in cols:
                    continue

                rows = cursor.execute(
                    f"SELECT {', '.join(select)} FROM {table}"
                ).fetchall()

                for row in rows:
                    entry = dict(zip(select, row))
                    if entry.get('code') and entry.get('username'):
                        media_list.append(entry)
            except Exception:
                continue

        conn.close()
    except Exception as e:
        print(f"  [clips.db] Chyba při čtení: {e}")

    return media_list


def sync_user_reel_medias_db(serial_number=None):
    """
    Stáhne user_reel_medias_room_db z telefonu.

    Tato databáze obsahuje reely a stories od sledovaných uživatelů
    (stories tray) – přímý zdroj shortcodu bez nutnosti dekomprese.

    Returns:
        str: Cesta k lokálnímu souboru nebo None při chybě
    """
    try:
        devnull = subprocess.DEVNULL
        adb_cmd = ['adb']
        if serial_number:
            adb_cmd.extend(['-s', serial_number])

        db_dir = "/data/data/com.instagram.android/databases"
        pattern = re.compile(r'^(user_reel_medias_room_db_\d+)$')

        result = subprocess.run(
            adb_cmd + ['shell', f"su -c 'ls {db_dir}'"],
            capture_output=True, text=True, timeout=10,
        )
        db_name = None
        for line in result.stdout.splitlines():
            name = line.strip()
            if pattern.match(name):
                db_name = name
                break

        if not db_name:
            return None

        local_db = f"user_reel_medias_{serial_number}.db" if serial_number else "user_reel_medias.db"
        subprocess.run(
            adb_cmd + ['shell', f"su -c 'cp {db_dir}/{db_name} /sdcard/urm_temp.db'"],
            stdout=devnull, stderr=devnull, timeout=10,
        )
        result = subprocess.run(
            adb_cmd + ['pull', '/sdcard/urm_temp.db', local_db],
            capture_output=True, timeout=15,
        )
        if result.returncode == 0 and os.path.exists(local_db):
            return local_db
    except Exception:
        pass
    return None


def get_user_reel_medias_info(db_path: str) -> list:
    """
    Parsuje user_reel_medias_room_db – shortcody jsou přímo v JSON poli 'medias'.

    Returns:
        list: Záznamy s 'username', 'code', 'pk', 'like_count', 'comment_count', 'video_duration'
    """
    if not os.path.exists(db_path):
        return []

    media_list = []
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        rows = cursor.execute(
            "SELECT id, data, stored_time FROM user_reel_medias"
        ).fetchall()
        for _, data_blob, stored_time in rows:
            try:
                if isinstance(data_blob, bytes):
                    data_str = data_blob.decode("utf-8", errors="replace")
                else:
                    data_str = str(data_blob)
                data = json.loads(data_str)
                for m in data.get("medias", []):
                    code = m.get("code")
                    username = m.get("user", {}).get("username")
                    if not code or not username:
                        continue
                    caption_obj = m.get("caption") or {}
                    caption_text = caption_obj.get("text") if isinstance(caption_obj, dict) else None
                    hashtags = re.findall(r'#(\w+)', caption_text) if caption_text else []
                    media_list.append({
                        "code":           code,
                        "username":       username,
                        "pk":             m.get("pk"),
                        "like_count":     m.get("like_count"),
                        "comment_count":  m.get("comment_count"),
                        "video_duration": m.get("video_duration"),
                        "caption_text":   caption_text,
                        "hashtags":       hashtags,
                        "stored_time":    stored_time,
                    })
            except Exception:
                continue
        conn.close()
    except Exception as e:
        print(f"  [user_reel_medias] Chyba při čtení: {e}")

    return media_list


def sync_http_response_cache(serial_number=None):
    """
    Stáhne HTTP response cache z telefonu.

    Instagram cachuje API odpovědi (feed, reels, explore) ve formátu
    gzip jako soubory ``*-body_gzip.clean`` v adresáři
    /cache/http_responses/. Obsahují kompletní JSON s kódy (shortcodes)
    a usernames pro veškeré media načtené z internetu – ideální záložní
    zdroj dat pro každý reel.

    Nové soubory se stahují přírůstkově: soubory, které již lokálně
    existují, se přeskakují.

    Returns:
        str: Cesta k lokálnímu adresáři s cache nebo None při chybě
    """
    try:
        devnull = subprocess.DEVNULL
        adb_cmd = ['adb']
        if serial_number:
            adb_cmd.extend(['-s', serial_number])

        cache_dir = "/data/data/com.instagram.android/cache/http_responses"
        local_dir = f"http_cache_{serial_number}" if serial_number else "http_cache"
        os.makedirs(local_dir, exist_ok=True)

        # Zjisti seznam body souborů na zařízení
        result = subprocess.run(
            adb_cmd + ['shell', f"su -c 'ls {cache_dir}' 2>/dev/null"],
            capture_output=True, text=True, timeout=10,
        )
        filenames = [
            line.strip() for line in result.stdout.splitlines()
            if line.strip().endswith('-body_gzip.clean')
        ]

        if not filenames:
            return local_dir if os.listdir(local_dir) else None

        # Stáhni pouze nové soubory (přírůstkově)
        new_files = [f for f in filenames if not os.path.exists(os.path.join(local_dir, f))]

        if new_files:
            # Vytvoř tar archív jen z nových souborů najednou (rychlejší než N pullů)
            file_list = " ".join(new_files)
            subprocess.run(
                adb_cmd + ['shell',
                           f"su -c 'cd {cache_dir} && tar -czf /sdcard/http_new.tar.gz {file_list}'"],
                stdout=devnull, stderr=devnull, timeout=30,
            )
            tar_local = os.path.join(local_dir, "_new.tar.gz")
            r = subprocess.run(
                adb_cmd + ['pull', '/sdcard/http_new.tar.gz', tar_local],
                capture_output=True, timeout=30,
            )
            if r.returncode == 0 and os.path.exists(tar_local):
                import tarfile
                try:
                    with tarfile.open(tar_local, 'r:gz') as tf:
                        tf.extractall(local_dir)
                except Exception:
                    pass
                os.remove(tar_local)

        return local_dir

    except Exception as e:
        print(f"  [HTTP cache] Chyba při synchronizaci: {e}")
        return None


def _extract_media_from_json(obj: object, depth: int = 0) -> list:
    """Rekurzivně extrahuje záznamy s 'code' + 'username' z JSON objektu."""
    if depth > 8:
        return []
    results = []
    if isinstance(obj, dict):
        code = obj.get('code')
        user_obj = obj.get('user')
        username = (
            user_obj.get('username') if isinstance(user_obj, dict)
            else obj.get('username')
        )
        if code and username and len(code) >= 9:
            caption_obj = obj.get('caption') or {}
            caption_text = caption_obj.get('text') if isinstance(caption_obj, dict) else None
            hashtags = re.findall(r'#(\w+)', caption_text) if caption_text else []
            results.append({
                'code':           code,
                'username':       username,
                'pk':             obj.get('pk'),
                'like_count':     obj.get('like_count'),
                'comment_count':  obj.get('comment_count'),
                'video_duration': obj.get('video_duration'),
                'caption_text':   caption_text,
                'hashtags':       hashtags,
            })
        for v in obj.values():
            if isinstance(v, (dict, list)):
                results.extend(_extract_media_from_json(v, depth + 1))
    elif isinstance(obj, list):
        for item in obj:
            results.extend(_extract_media_from_json(item, depth + 1))
    return results


def get_http_cache_media_info(local_dir: str) -> list:
    """
    Parsuje stažené HTTP response cache soubory a extrahuje media záznamy.

    Returns:
        list: Záznamy s 'code', 'username' a dalšími metadaty
    """
    if not os.path.exists(local_dir):
        return []

    media_list: list = []
    seen_codes: set = set()

    for fname in os.listdir(local_dir):
        if not fname.endswith('-body_gzip.clean'):
            continue
        path = os.path.join(local_dir, fname)
        try:
            with open(path, 'rb') as f:
                raw = f.read()

            try:
                text = gzip.decompress(raw).decode('utf-8', errors='replace')
            except Exception:
                text = raw.decode('utf-8', errors='replace')

            try:
                obj = json.loads(text)
                for entry in _extract_media_from_json(obj):
                    code = entry.get('code')
                    if code and code not in seen_codes:
                        media_list.append(entry)
                        seen_codes.add(code)
            except Exception:
                pass
        except Exception:
            continue

    return media_list


def sync_instagram_db(serial_number=None):
    """
    Synchronizuje Instagram databázi z telefonu do lokálního souboru.
    Vyžaduje root přístup.
    
    Args:
        serial_number: Serial number zařízení (pokud None, použije se první dostupné)
    
    Returns:
        str: Cesta k lokální databázi nebo None při chybě
    """
    try:
        devnull = subprocess.DEVNULL

        adb_cmd = ['adb']
        if serial_number:
            adb_cmd.extend(['-s', serial_number])

        db_path = _find_db_path_on_device(adb_cmd)
        if not db_path:
            print("❌ Chyba při synchronizaci DB: Databáze flash_media nenalezena na zařízení.")
            return None

        wal_path = f"{db_path}-wal"

        subprocess.run(
            adb_cmd + ['shell', f"su -c 'cp {db_path} /sdcard/flash_media.db'"],
            stdout=devnull, stderr=devnull, check=True,
        )
        subprocess.run(
            adb_cmd + ['shell', f"su -c 'cp {wal_path} /sdcard/flash_media.db-wal'"],
            stdout=devnull, stderr=devnull,
        )

        local_db = f"flash_media_{serial_number}.db" if serial_number else "flash_media.db"
        subprocess.run(adb_cmd + ['pull', '/sdcard/flash_media.db', local_db], stdout=devnull, stderr=devnull, check=True)
        subprocess.run(adb_cmd + ['pull', '/sdcard/flash_media.db-wal', f'{local_db}-wal'], stdout=devnull, stderr=devnull)

        return local_db

    except Exception as e:
        print(f"❌ Chyba při synchronizaci DB: {e}")
        return None


def get_cached_media_info(db_path="flash_media.db"):
    """
    Získá informace o všech uložených médiích z databáze.
    
    Args:
        db_path: Cesta k lokální databázi
    
    Returns:
        list: Seznam slovníků s informacemi o médiích
    """
    if not os.path.exists(db_path):
        print("⚠️ Databáze neexistuje, synchronizuji...")
        db_path = sync_instagram_db()
        if not db_path:
            return []
    
    media_list = []
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        cursor.execute("SELECT id, type, data, stored_time FROM medias")
        rows = cursor.fetchall()
        
        for full_id, media_type, data, stored_time in rows:
            # Rozděl ID
            parts = full_id.split('_')
            media_id = parts[0] if len(parts) >= 1 else full_id
            user_id = parts[1] if len(parts) >= 2 else None
            
            # Dekóduj data
            media_info = {
                "media_id": media_id,
                "user_id": user_id,
                "full_id": full_id,
                "type": media_type,
                "stored_time": stored_time,
            }
            
            # Pokus o dekomprimaci dat
            if data:
                parsed = decompress_and_parse(data)
                if parsed:
                    # Extrahuj důležité informace
                    caption_text = parsed.get("caption", {}).get("text") if parsed.get("caption") else None
                    
                    # Extrahuj hashtagy z caption
                    hashtags = re.findall(r'#(\w+)', caption_text) if caption_text else []
                    
                    media_info.update({
                        "pk": parsed.get("pk"),
                        "code": parsed.get("code"),  # Shortcode pro URL
                        "username": parsed.get("user", {}).get("username"),
                        "like_count": parsed.get("like_count"),
                        "comment_count": parsed.get("comment_count"),
                        "video_duration": parsed.get("video_duration"),
                        "caption_text": caption_text,
                        "hashtags": hashtags,
                    })
            
            media_list.append(media_info)
        
        conn.close()
        
    except Exception as e:
        print(f"❌ Chyba při čtení DB: {e}")
    
    return media_list


def get_current_reel_media_id():
    """
    Získá media_id aktuálního Reelu, který se právě přehrává.
    
    Funguje tak, že:
    1. Synchronizuje databázi
    2. Získá nejnovější médium podle stored_time
    
    Returns:
        dict: Informace o aktuálním médiu nebo None
    """
    # Synchronizuj databázi
    db_path = sync_instagram_db()
    if not db_path:
        return None
    
    # Získej všechna média
    media_list = get_cached_media_info(db_path)
    
    if not media_list:
        return None
    
    # Seřaď podle stored_time (nejnovější první)
    media_list.sort(key=lambda x: x.get("stored_time", 0), reverse=True)
    
    return media_list[0] if media_list else None


_SCAN_CODE_RE = re.compile(rb'"code":"([A-Za-z0-9_-]{9,14})"')
_SCAN_FLOAT_RE = re.compile(rb'"video_duration":([\d.]+)')
_SCAN_USER_RE = re.compile(rb'"username":"([^"]{1,40})"')
_SCAN_LIKES_RE = re.compile(rb'"like_count":(\d+)')
_SCAN_COMMENTS_RE = re.compile(rb'"comment_count":(\d+)')

# Prefixové skupiny adres pro cílený scan (od nejpravděpodobnějšího).
# Na základě experimentů jsou OkHttp buffery Instagramu konzistentně v rozsahu 0x6e3x.
_SCAN_ADDR_PREFIXES = [
    (0x6E340000_00000000 >> 24, 0x6E35000000000000 >> 24),  # 6e34…
    (0x6E300000_00000000 >> 24, 0x6E400000_00000000 >> 24),  # 6e3…
    (0x6E000000_00000000 >> 24, 0x7300000000000000 >> 24),  # 6e…–72…
]


def sync_proc_mem(serial_number: str | None = None, timeout_s: int = 20, exhaustive: bool = False) -> list[dict]:
    """
    Přečte shortcody přímo z paměti procesu Instagramu (OkHttp JSON buffery).

    Místo shell skriptu (který byl pomalý) provádí celý scan v Pythonu:
    1. Stáhne /proc/{pid}/maps přes ADB.
    2. Filtruje anonymní rw-p segmenty v nativním adresním rozsahu.
    3. Pro každý segment spustí ``dd`` přes ADB s timeoutem a prohledá
       výstup regexem pro ``"code":"XXXX"``.
    4. Okamžitě vrátí první nalezené výsledky.

    Vyžaduje root a zapnutý Instagram.

    Args:
        serial_number: ADB sériové číslo zařízení (None = první dostupné)
        timeout_s: Celkový maximální čas scanu v sekundách
        exhaustive: Pokud True, skenuje všechny segmenty (ne jen první s daty).
                    Vhodné pro počáteční scan – zachytí více shortcodů.

    Returns:
        Seznam dict s klíčem 'code' a 'source'='proc_mem'
    """
    import time as _time

    deadline = _time.monotonic() + timeout_s
    adb = ["adb"]
    if serial_number:
        adb += ["-s", serial_number]

    # 1. Získej PID Instagramu
    try:
        r = subprocess.run(
            adb + ["shell", "su -c 'pidof com.instagram.android'"],
            capture_output=True, text=True, timeout=5,
        )
        pid = r.stdout.strip().split()[0] if r.stdout.strip() else None
        if not pid:
            return []
    except Exception:
        return []

    # 2. Stáhni maps
    try:
        r = subprocess.run(
            adb + ["shell", f"su -c 'cat /proc/{pid}/maps'"],
            capture_output=True, text=True, timeout=10,
        )
        maps_text = r.stdout
    except Exception:
        return []

    # 3. Parsuj mapu a vyber cílové segmenty
    segments: list[tuple[int, int]] = []
    for line in maps_text.splitlines():
        parts = line.split()
        if len(parts) < 2:
            continue
        if parts[1] != "rw-p":
            continue
        name = parts[5] if len(parts) >= 6 else ""
        # Přeskoč knihovny a systémové cesty
        if any(x in name for x in (".so", "/data/app/", "/system/", "/apex/",
                                    "dalvik", "boot")):
            continue
        addr_range = parts[0]
        try:
            sh, eh = addr_range.split("-")
            start = int(sh, 16)
            end = int(eh, 16)
        except ValueError:
            continue
        size = end - start
        if size < 256 * 1024 or size > 16 * 1024 * 1024:
            continue
        segments.append((start, end))

    if not segments:
        return []

    # 4. Seřaď segmenty – nejdřív 6e34…, pak ostatní
    def _priority(seg: tuple[int, int]) -> int:
        s = seg[0]
        if 0x6E3400000000 <= s < 0x6E3500000000:
            return 0
        if 0x6E3000000000 <= s < 0x6E4000000000:
            return 1
        if 0x6E0000000000 <= s < 0x7300000000_00:
            return 2
        return 3

    segments.sort(key=_priority)

    # 5. Skenuj segmenty jeden po druhém
    found_codes: list[dict] = []
    for start, end in segments:
        if _time.monotonic() >= deadline:
            break
        size = end - start
        skip = start // 4096
        count = size // 4096 + 1
        remaining = max(1, int(deadline - _time.monotonic()))
        try:
            r = subprocess.run(
                adb + ["shell",
                       f"su -c 'dd if=/proc/{pid}/mem bs=4096 skip={skip} count={count} 2>/dev/null'"],
                capture_output=True,
                timeout=min(remaining + 1, 5),  # max 5s na jeden segment
            )
            data: bytes = r.stdout
        except subprocess.TimeoutExpired:
            continue
        except Exception:
            continue

        code_matches = list(_SCAN_CODE_RE.finditer(data))
        if not code_matches:
            continue

        # Předem vyextrahuj všechny výskyty metadat v segmentu (pozice + hodnota).
        # Ke každému code pak přiřadíme nejbližší výskyt – každé video v API odpovědi
        # má vlastní video_duration/username, ale vzdálenost code↔metadata může být
        # desítky KB, takže windowing nestačí.
        def _nearest(matches, pos, decode=False, as_int=False, max_dist=40_000):
            best, best_dist = None, max_dist
            for mm in matches:
                dist = abs(mm.start() - pos)
                if dist < best_dist:
                    best_dist = dist
                    val = mm.group(1)
                    if decode:
                        val = val.decode("utf-8", errors="replace")
                    elif as_int:
                        try:
                            val = int(val)
                        except ValueError:
                            continue
                    else:
                        try:
                            val = float(val)
                        except ValueError:
                            continue
                    best = val
            return best

        dur_matches  = list(_SCAN_FLOAT_RE.finditer(data))
        user_matches = list(_SCAN_USER_RE.finditer(data))
        like_matches = list(_SCAN_LIKES_RE.finditer(data))
        comm_matches = list(_SCAN_COMMENTS_RE.finditer(data))

        all_codes_seen: set[str] = {e["code"] for e in found_codes}
        seen: set[str] = set()
        for m in code_matches:
            code = m.group(1).decode("ascii", errors="replace")
            if code in seen or code in all_codes_seen:
                continue
            seen.add(code)

            pos = m.start()
            dur      = _nearest(dur_matches,  pos)
            username = _nearest(user_matches, pos, decode=True)
            likes    = _nearest(like_matches, pos, as_int=True)
            comments = _nearest(comm_matches, pos, as_int=True)

            entry: dict = {"code": code, "source": "proc_mem"}
            if dur is not None:
                entry["video_duration"] = dur
            if username:
                entry["username"] = username
            if likes is not None:
                entry["like_count"] = likes
            if comments is not None:
                entry["comment_count"] = comments
            found_codes.append(entry)
        if not exhaustive:
            break  # Stačí první segment s daty (rychlý fallback)

    return found_codes


def get_proc_mem_info(result_file: str | None) -> list[dict]:
    """Zpětně kompatibilní wrapper – přijme buď výsledek (list) nebo cestu k souboru.

    Nová implementace ``sync_proc_mem`` vrací rovnou list[dict], ale bot.py
    může volat i starší rozhraní s cestou k souboru.
    """
    if isinstance(result_file, list):
        return result_file  # type: ignore[return-value]
    if not result_file or not os.path.exists(result_file):
        return []
    try:
        with open(result_file, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
        codes = re.findall(r'"code":"([A-Za-z0-9_-]{9,14})"', content)
        seen: set[str] = set()
        results: list[dict] = []
        for code in codes:
            if code not in seen:
                seen.add(code)
                results.append({"code": code, "source": "proc_mem"})
        return results
    except Exception:
        return []


def get_reel_url(media_info):
    """
    Vytvoří URL pro Reel z media_info.
    
    Args:
        media_info: Slovník s informacemi o médiu (musí obsahovat 'code')
    
    Returns:
        str: URL Reelu nebo None
    """
    code = media_info.get("code")
    if code:
        return f"https://www.instagram.com/reel/{code}/"
    return None


if __name__ == "__main__":
    print("🔄 Synchronizuji databázi z telefonu...")
    db = sync_instagram_db()
    
    if db:
        print(f"✅ Databáze stažena: {db}\n")
        
        print("📋 Uložená média:")
        print("=" * 60)
        
        media_list = get_cached_media_info(db)
        
        for i, media in enumerate(media_list):
            print(f"\n🎬 Médium #{i+1}")
            print(f"   📌 Media ID: {media.get('pk') or media.get('media_id')}")
            print(f"   🔗 Shortcode: {media.get('code')}")
            print(f"   👤 Username: {media.get('username')}")
            print(f"   ❤️ Likes: {media.get('like_count'):,}" if media.get('like_count') else "   ❤️ Likes: N/A")
            print(f"   💬 Comments: {media.get('comment_count'):,}" if media.get('comment_count') else "   💬 Comments: N/A")
            print(f"   ⏱️ Duration: {media.get('video_duration'):.1f}s" if media.get('video_duration') else "   ⏱️ Duration: N/A")
            
            # Hashtagy
            hashtags = media.get('hashtags', [])
            if hashtags:
                print(f"   #️⃣ Hashtags ({len(hashtags)}): {' '.join(['#' + h for h in hashtags])}")
            
            url = get_reel_url(media)
            if url:
                print(f"   🔗 URL: {url}")
    else:
        print("❌ Nepodařilo se stáhnout databázi")

