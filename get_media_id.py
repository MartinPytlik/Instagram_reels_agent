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

