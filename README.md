# Iceco Refrigerator — Home Assistant

Home Assistant integration for **Iceco portable dual-zone refrigerators** over Bluetooth
LE. Read and control temperature setpoints, mode, battery protection and the display
unit; get power-loss, low-battery and temperature-deviation alarms.

> **Fork.** Started from [jeremyroe/HA-Iceco-Integration](https://github.com/jeremyroe/HA-Iceco-Integration)
> (MIT). This version rewrites the BLE connection layer and adds support for the
> newer **`/S00/0L`** firmware — a single unified status frame and a different
> command map — found on the **VL PRO Dual Zone** and similar units. The original
> targets the APL35's `PRIMARY` / `SECONDARY` notifications. See
> [`PROTOCOL.md`](PROTOCOL.md) and [`CREDITS.md`](CREDITS.md).

---

## Compatibility

| Firmware | Status |
|---|---|
| `/S00/0L` unified frame (ICECO **VL PRO Dual Zone**, confirmed) | ✅ fully supported — reverse-engineered live |
| APL35 `PRIMARY` / `SECONDARY` frames | 🟡 parsing falls back to the original path; command routing is not firmware-conditional yet (see *Known limitations*) |

Both advertise BLE service `FFF0` with write char `FFF1` and notify char `FFF4`.

---

## What you get

**Controls** — Left / Right zone climate (setpoint, on/off), Power.
**Configuration** — Mode (ECO / MAX), Battery Protection (Low / Medium / High),
Display Unit (°C / °F), BLE Connection (disconnect to free the fridge for the app).
**Sensors** — Low Battery, Power-Loss alarm, per-zone Temperature-Deviation alarm.
**Diagnostic** — Battery Voltage (with the protection cut-out / cut-in voltages as
attributes).

`climate` entities report `hvac_action` (Cooling / Idle / Off) derived per zone —
there is no direct "which side is the compressor feeding" field in the protocol.

---

## Installation

### HACS (custom repository)

1. HACS → ⋮ → **Custom repositories** → add
   `https://github.com/theOrakle/iceco` as category **Integration**.
2. Install **Iceco Refrigerator**, restart Home Assistant.

### Manual

Copy `custom_components/iceco/` into `config/custom_components/`, restart.

---

## Setup

Power the fridge on. HA auto-discovers it via Bluetooth (the advert carries the
Iceco manufacturer ID `0xAFF2`). **Settings → Devices & Services** → add the
discovered *Iceco Refrigerator*, or enter the BLE address manually.

The integration holds one persistent BLE connection and issues a silent keep-alive
read every 5 s — this firmware drops a central that goes quiet ~7 s after it stops
streaming. Only one BLE central can connect at a time, so turn the **BLE Connection**
switch off before using the Iceco phone app.

---

## Protocol (`/S00/0L` firmware)

Status frame on `FFF4`, roughly every 15–30 s while running (and in standby):

```
/S00/0L/<zones>,<power>,<unit>,<L_cur>,<R_cur>,<L_set>,<R_set>,<battProt>,<voltage>,<mode>,<f10>,<f11>
```

Commands, written no-response to `FFF1` as `/S<id>/1/<value>\n`:

| id | function | values |
|----|----------|--------|
| `S01` | power | `001` on · `000` standby |
| `S03` | left / zone-1 setpoint | signed °C — `/S03/1/+04`, `/S03/1/-18` |
| `S04` | battery protection | `001` Low · `002` Medium · `003` High |
| `S05` | right / zone-2 setpoint | signed °C |
| `S06` | mode | `001` ECO · `002` MAX |
| `S07` | display unit | `001` °C · `002` °F |

Full field map and the reverse-engineering notes are in [`PROTOCOL.md`](PROTOCOL.md).

---

## Known limitations

- **Firmware routing isn't conditional.** Commands assume the `/S00/0L` map. On an
  APL35, `S01` is ECO (not power) — so on that firmware the Power / Mode controls
  would misbehave. A `FirmwareProfile` (parser + command map + capability set,
  selected from the frame type or the firmware-revision characteristic) is the
  planned fix.
- **Panel lock** has no known command or status field on `/S00/0L` and the Iceco
  app doesn't expose it — no lock entity.
- `f10` / `f11` in the frame are unidentified (constant `0` / `000` in every state
  observed — possibly fault codes).
- `iceco.send_command` is a debug service for further reverse-engineering; it
  writes arbitrary strings to `FFF1`. Use with care.

---

## Development

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements_test.txt
pytest
```

Parser tests use real frame captures. `tools/probe.py` is a standalone `bleak`
script for GATT exploration.

---

## License

MIT — see [`LICENSE`](LICENSE). Original work © Jeremy Roe; this fork's changes
© theOrakle.
