"""
Správa Android zařízení přes ADB a uiautomator2.

Poskytuje funkce pro:
  - zjišťování dostupných zařízení (list_available_devices)
  - testování ADB spojení (test_device_adb)
  - připojení k zařízení a odemčení obrazovky (connect_device)
"""

import subprocess
import time

import uiautomator2 as u2


# ---------------------------------------------------------------------------
# Veřejné funkce
# ---------------------------------------------------------------------------

def list_available_devices(retry: bool = True) -> list[str]:
    """
    Vrátí seznam sériových čísel připojených Android zařízení.

    Pokud retry=True a žádné online zařízení nenajde, pokusí se restartovat
    ADB server a dotaz zopakovat.
    """
    try:
        result = _run_adb_devices(timeout=8)

        if not _has_online_devices(result) and retry:
            _restart_adb_server()
            result = _run_adb_devices(timeout=10)

        return _parse_adb_output(result.stdout) if result else []

    except FileNotFoundError:
        print("ADB není nainstalované nebo není v PATH.")
        return []
    except Exception as e:
        print(f"Chyba při zjišťování zařízení: {e}")
        return []


def test_device_adb(serial_number: str) -> tuple[bool, str]:
    """
    Ověří, zda ADB na daném zařízení reaguje.

    Returns:
        (True, zpráva)  – zařízení je dostupné
        (False, zpráva) – zařízení neodpovídá nebo nastala chyba
    """
    try:
        result = subprocess.run(
            ["adb", "-s", serial_number, "shell", "echo", "ok"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0 and "ok" in (result.stdout or ""):
            return True, "ADB reaguje"
        return False, result.stderr or result.stdout or f"exit code {result.returncode}"
    except subprocess.TimeoutExpired:
        return False, "Timeout – zařízení neodpovídá"
    except Exception as e:
        return False, str(e)


def connect_device(serial_number: str, device_prefix: str = ""):
    """
    Připojí se k Android zařízení přes USB a odemkne obrazovku.

    Args:
        serial_number: ADB sériové číslo zařízení
        device_prefix: Název zařízení pro výpisy konzole

    Returns:
        uiautomator2 Device objekt

    Raises:
        ConnectionError: Pokud se připojení nezdaří
    """
    prefix = f"[{device_prefix}] " if device_prefix else ""
    print(f"{prefix}Připojuji se k zařízení {serial_number}...")

    try:
        device = u2.connect(serial_number)
        product = device.info.get("productName", "neznámé zařízení")
        print(f"{prefix}Připojeno k: {product}")
        _unlock_screen(device)
        return device
    except Exception as e:
        raise ConnectionError(f"Nelze se připojit k {serial_number}: {e}") from e


# ---------------------------------------------------------------------------
# Privátní pomocné funkce
# ---------------------------------------------------------------------------

def _run_adb_devices(timeout: float = 10):
    """Spustí 'adb devices' a vrátí výsledek nebo None při timeoutu."""
    try:
        return subprocess.run(
            ["adb", "devices"], capture_output=True, text=True, timeout=timeout
        )
    except subprocess.TimeoutExpired:
        return None


def _has_online_devices(result) -> bool:
    """Zkontroluje, zda výstup 'adb devices' obsahuje alespoň jedno online zařízení."""
    if not result:
        return False
    for line in result.stdout.strip().split("\n")[1:]:
        parts = line.strip().split("\t")
        if len(parts) >= 2 and parts[1] == "device":
            return True
    return False


def _restart_adb_server():
    """Restartuje ADB server."""
    try:
        subprocess.run(["adb", "kill-server"], capture_output=True, timeout=5)
        time.sleep(0.5)
        subprocess.run(["adb", "start-server"], capture_output=True, timeout=10)
        time.sleep(2)
    except Exception:
        pass


def _parse_adb_output(stdout: str) -> list[str]:
    """Parsuje výstup 'adb devices' a vrátí seznam online sériových čísel."""
    devices, unauthorized, offline = [], [], []

    for line in stdout.strip().split("\n")[1:]:
        if not line.strip() or "\t" not in line:
            continue
        parts = line.strip().split("\t")
        serial = parts[0]
        status = parts[1] if len(parts) > 1 else "unknown"

        if status == "device":
            devices.append(serial)
        elif status == "unauthorized":
            unauthorized.append(serial)
        elif status == "offline":
            offline.append(serial)

    if unauthorized:
        print(f"Neautorizovaná zařízení: {', '.join(unauthorized)} – povol USB debugging na telefonu.")
    if offline:
        print(f"Offline zařízení: {', '.join(offline)} – odpoj a znovu připoj USB kabel.")

    return devices


def _unlock_screen(device):
    """Odemkne obrazovku telefonu pomocí unlock() a swipe gesta."""
    device.unlock()
    width, height = device.window_size()
    device.swipe(
        width // 2, int(height * 0.85),
        width // 2, int(height * 0.15),
        duration=0.02,
    )
    time.sleep(0.3)
