"""
Pomocný skript pro diagnostiku připojení Android zařízení přes ADB.
Spusť tento skript pro zjištění, proč telefony nejsou viditelné.
"""

import subprocess
import sys

def run_command(cmd, description):
    """Spustí příkaz a vrátí výstup."""
    print(f"\n{'='*60}")
    print(f"🔍 {description}")
    print('='*60)
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=10)
        print(result.stdout)
        if result.stderr:
            print("STDERR:", result.stderr)
        return result.stdout
    except subprocess.TimeoutExpired:
        print("⏱️ Příkaz překročil timeout")
        return ""
    except Exception as e:
        print(f"❌ Chyba: {e}")
        return ""

def main():
    print("="*60)
    print("    🔧 DIAGNOSTIKA ANDROID ZAŘÍZENÍ")
    print("="*60)
    
    # 1. Zkontroluj ADB verzi
    run_command("adb version", "ADB verze")
    
    # 2. Zkontroluj připojená zařízení
    output = run_command("adb devices", "Připojená zařízení")
    
    # 3. Detailní výstup
    run_command("adb devices -l", "Detailní informace o zařízeních")
    
    # 4. Zkontroluj USB zařízení (Windows)
    if sys.platform == "win32":
        print("\n" + "="*60)
        print("🔍 USB zařízení v Device Manageru (Windows)")
        print("="*60)
        print("Otevři Device Manager a zkontroluj:")
        print("  - Android devices")
        print("  - Other devices (žlutý trojúhelník = problém)")
        print("  - Universal Serial Bus controllers")
    
    # 5. Analýza výstupu
    print("\n" + "="*60)
    print("📊 ANALÝZA")
    print("="*60)
    
    if "List of devices attached" in output:
        lines = output.strip().split('\n')[1:]
        if not lines or all(not line.strip() for line in lines):
            print("❌ ŽÁDNÁ ZAŘÍZENÍ NENALEZENA")
            print("\n✅ ZKUS:")
            print("   1. Odpoj a znovu připoj USB kabel")
            print("   2. Na telefonu: Klikni na USB notifikaci → Vyber 'File transfer'")
            print("   3. Na telefonu: Povol popup 'Allow USB debugging?'")
            print("   4. Spusť: adb kill-server && adb start-server")
            print("   5. Zkus jiný USB kabel/port")
        else:
            devices_found = False
            for line in lines:
                if line.strip() and '\t' in line:
                    devices_found = True
                    parts = line.strip().split('\t')
                    serial = parts[0]
                    status = parts[1] if len(parts) > 1 else 'unknown'
                    
                    if status == 'device':
                        print(f"✅ {serial}: ONLINE")
                    elif status == 'unauthorized':
                        print(f"⚠️ {serial}: UNAUTHORIZED")
                        print("   → Na telefonu povol 'Allow USB debugging'")
                    elif status == 'offline':
                        print(f"⚠️ {serial}: OFFLINE")
                        print("   → Odpoj a znovu připoj USB kabel")
                    else:
                        print(f"❓ {serial}: {status}")
            
            if not devices_found:
                print("⚠️ ADB vidí něco, ale není to rozpoznané zařízení")
    
    print("\n" + "="*60)
    print("💡 Pokud stále nefunguje, zkus:")
    print("="*60)
    print("   1. Restart telefonu")
    print("   2. Restart PC")
    print("   3. Zkus jiný USB kabel")
    print("   4. Zkus jiný USB port")
    print("   5. Zkontroluj USB drivers v Device Manageru")
    print("="*60)

if __name__ == "__main__":
    main()
