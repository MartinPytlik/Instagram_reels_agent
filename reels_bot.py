"""
Instagram Reels Bot – vstupní bod programu.

Automaticky scrolluje Reels na více Android zařízeních paralelně.
Na základě metadat videa volá prediktor, který rozhoduje o akci
(like, save, skip, sledování po dobu X sekund, …).

Závislosti:
  - Android Debug Bridge (ADB) v PATH
  - uiautomator2 nainstalovaný na telefonech (python -m uiautomator2 init)
  - Root přístup na telefonech (pro čtení Instagram databáze médií)

Použití:
  python reels_bot.py
      Obě zařízení, neomezeně, náhodná session ID.

  python reels_bot.py --device Device1
      Jen Device1.

  python reels_bot.py --reels 50
      50 Reelů na každém zařízení.

  python reels_bot.py --session-id Device1:<uuid> Device2:<uuid>
      Každému zařízení přiřaď vlastní session ID.

  python reels_bot.py --session-id <uuid>
      Stejné session ID pro všechna zařízení.
"""

import sys
import time
import threading
import argparse

from config import DEVICES
from bot import run_bot_for_device


def _parse_session_ids(raw: list[str], devices: list[dict]) -> dict[str, str]:
    """
    Parsuje seznam session ID z příkazové řádky.

    Podporuje dva formáty:
      - "Device1:<uuid>"  → přiřadí UUID konkrétnímu zařízení podle jména nebo sériáku
      - "<uuid>"          → přiřadí UUID všem zařízením (nebo prvnímu v pořadí)

    Pokud je zadáno více holých UUID než zařízení, přebytečné se ignorují.
    Pokud je zadáno méně, zbývající zařízení dostanou náhodné UUID (None → uuid.uuid4 v bot.py).

    Returns:
        dict {serial_number: session_id}
    """
    result: dict[str, str] = {}

    bare_uuids: list[str] = []

    for item in raw:
        if ":" in item:
            # Formát "Jméno:uuid" nebo "Serial:uuid"
            # Rozdělíme pouze na první dvojtečku (UUID samotné dvojtečky neobsahují)
            name_part, uuid_part = item.split(":", 1)
            name_part = name_part.strip()
            uuid_part = uuid_part.strip()
            matched = [d for d in devices if name_part in (d["name"], d["serial"])]
            if matched:
                result[matched[0]["serial"]] = uuid_part
            else:
                print(f"Upozornění: zařízení '{name_part}' nenalezeno v konfiguraci, session ID ignorováno.")
        else:
            bare_uuids.append(item.strip())

    # Holá UUID přiřaď zařízením v pořadí (pokud ještě nemají přiřazené)
    unassigned = [d for d in devices if d["serial"] not in result]
    for device, uid in zip(unassigned, bare_uuids):
        result[device["serial"]] = uid

    return result


def main():
    parser = argparse.ArgumentParser(
        description="Instagram Reels Bot – automatické procházení Reels na více zařízeních.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--device",
        type=str,
        default=None,
        metavar="DEVICE",
        help="Spustit jen na jednom zařízení: serial nebo jméno (Device1, Device2)",
    )
    parser.add_argument(
        "--reels",
        type=int,
        default=0,
        metavar="N",
        help="Počet Reelů na zařízení (0 = neomezeně, výchozí: 0)",
    )
    parser.add_argument(
        "--session-id",
        nargs="+",
        default=None,
        metavar="ID",
        help=(
            "Session ID pro prediktor. Formáty:\n"
            "  <uuid>                   – stejné ID pro všechna zařízení\n"
            "  Device1:<uuid> Device2:<uuid>  – ID per zařízení\n"
            "  <uuid1> <uuid2>          – ID v pořadí dle konfigurace\n"
            "Výchozí: náhodné UUID pro každé zařízení"
        ),
    )
    args = parser.parse_args()

    devices = list(DEVICES)

    # Filtrování na konkrétní zařízení
    if args.device:
        device_filter = args.device.strip()
        devices = [d for d in devices if device_filter in (d["serial"], d["name"])]
        if not devices:
            names = ", ".join(f"{d['name']} ({d['serial']})" for d in DEVICES)
            print(f"Zařízení '{device_filter}' není v konfiguraci.")
            print(f"Dostupná zařízení v konfiguraci: {names}")
            sys.exit(1)

    # Session ID z configu jako výchozí, --session-id může přepsat
    session_ids = {d["serial"]: d["session_id"] for d in devices if d.get("session_id")}
    if args.session_id:
        session_ids.update(_parse_session_ids(args.session_id, devices))

    print("=" * 50)
    print("    Instagram Reels Bot")
    print("=" * 50)
    print()

    for d in devices:
        sid = session_ids.get(d["serial"], "(náhodné)")
        print(f"  [{d['name']}] {d['serial']}  |  session: {sid}")

    # Spuštění vláken
    print()
    threads: list[threading.Thread] = []
    for device_config in devices:
        sid = session_ids.get(device_config["serial"])  # None → bot.py vygeneruje UUID
        t = threading.Thread(
            target=run_bot_for_device,
            args=(device_config["serial"], device_config["name"], args.reels, sid),
            name=f"Thread-{device_config['name']}",
        )
        t.start()
        threads.append(t)
        print(f"Spuštěno vlákno pro {device_config['name']} ({device_config['serial']})")
        time.sleep(1)

    print(f"\nČekám na dokončení {len(threads)} vláken...\n")
    for t in threads:
        t.join()

    print("\n" + "=" * 50)
    print("Všechna zařízení dokončena.")
    print("=" * 50)


if __name__ == "__main__":
    main()
