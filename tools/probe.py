#!/usr/bin/env python3
"""Iceco BLE probe — figure out what keeps the fridge connection alive.

Run on the Raspberry Pi with the HASS iceco integration DISABLED and the
phone app closed. Do all three passes and paste me the output of each:

    python3 probe.py                    # 1. connect + listen, dump GATT table
    python3 probe.py --read             # 2. + GATT read every 5s as keepalive
    python3 probe.py --write-setpoint   # 3. + re-send current L setpoint every 5s

For each: how long does the link survive, and do NOTIFY lines keep coming?
"""
import argparse
import asyncio
import sys
import time

from bleak import BleakClient, BleakScanner

ADDR = "F2:AF:39:F1:D1:13"
WRITE_UUID = "0000fff1-0000-1000-8000-00805f9b34fb"
NOTIFY_UUID = "0000fff4-0000-1000-8000-00805f9b34fb"

start = time.monotonic()
last_left_setpoint = None


def ts() -> str:
    return f"{time.monotonic() - start:7.2f}s"


def on_notify(_char, data: bytearray) -> None:
    global last_left_setpoint
    raw = bytes(data)
    print(f"[{ts()}] NOTIFY {raw!r}")
    try:
        msg = raw.decode("ascii").strip()
        if msg.startswith("/S00/0L/"):
            last_left_setpoint = int(msg.split("/", 3)[3].split(",")[5])
    except Exception:
        pass


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--read", action="store_true", help="GATT-read keepalive every 5s")
    ap.add_argument("--write-setpoint", action="store_true",
                    help="re-send current left setpoint every 5s")
    ap.add_argument("--seconds", type=int, default=180)
    args = ap.parse_args()

    print(f"[{ts()}] scanning for {ADDR} ...")
    device = await BleakScanner.find_device_by_address(ADDR, timeout=20.0)
    if device is None:
        print("device not found — power-cycle the fridge and close the app, then retry")
        sys.exit(1)

    disconnected = asyncio.Event()

    def on_disc(_c):
        print(f"[{ts()}] *** DISCONNECTED ***")
        disconnected.set()

    print(f"[{ts()}] connecting ...")
    async with BleakClient(device, disconnected_callback=on_disc) as client:
        print(f"[{ts()}] connected. GATT table:")
        for s in client.services:
            print(f"  service {s.uuid}")
            for c in s.characteristics:
                print(f"    char {c.uuid}  props={','.join(c.properties)}  handle={c.handle}")

        await client.start_notify(NOTIFY_UUID, on_notify)
        print(f"[{ts()}] subscribed to {NOTIFY_UUID}; holding for {args.seconds}s\n")

        deadline = time.monotonic() + args.seconds
        while time.monotonic() < deadline and not disconnected.is_set():
            await asyncio.sleep(5)
            if disconnected.is_set():
                break
            try:
                if args.read:
                    val = await client.read_gatt_char(NOTIFY_UUID)
                    print(f"[{ts()}] keepalive READ ok -> {bytes(val)!r}")
                elif args.write_setpoint:
                    if last_left_setpoint is None:
                        print(f"[{ts()}] no setpoint learned yet, skipping write")
                        continue
                    lv = last_left_setpoint
                    payload = f"-{abs(lv):02d}" if lv < 0 else f"{lv:03d}"
                    cmd = f"/S03/1/{payload}\n".encode()
                    await client.write_gatt_char(WRITE_UUID, cmd, response=False)
                    print(f"[{ts()}] keepalive WRITE {cmd!r}")
            except Exception as e:  # noqa: BLE001
                print(f"[{ts()}] keepalive error: {e!r}")

        print(f"\n[{ts()}] done (link dropped: {disconnected.is_set()})")


if __name__ == "__main__":
    asyncio.run(main())
