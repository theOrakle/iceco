# Iceco Refrigerator BLE Protocol

> **Note:** All findings documented here are inferred from Bluetooth packet captures and empirical hardware testing. This is not official documentation from Iceco. Field names and interpretations are best-effort reverse engineering.

---

## BLE Service and Characteristics

| Role | UUID |
|------|------|
| Service | `0000fff0-0000-1000-8000-00805f9b34fb` |
| Write (commands) | `0000fff1-0000-1000-8000-00805f9b34fb` |
| Notify (status) | `0000fff4-0000-1000-8000-00805f9b34fb` |

- Device advertises as **SimpleBLEPeripheral**
- All data is ASCII-encoded
- Commands must be sent **write-without-response** (`response=False` in bleak). Write-with-response is silently rejected by the firmware.

---

## Commands

Sent to the Write characteristic (FFF1).

### Format

```
/S<ID>/1/<Value>\n
```

### Command Reference

| Command | ID | Value | Notes |
|---------|----|-------|-------|
| Set left zone setpoint | `03` | `+XX` or `-XX` | °C, e.g. `+04` or `-18` |
| Set right zone setpoint | `05` | `+XX` or `-XX` | °C, same format |
| Power toggle | `00` | `-01` | Toggles on↔off |
| ECO mode | `01` | `001` = ECO on, `000` = MAX mode | Not a toggle — explicit value |
| Lock control panel | `06` | `002` = lock, `001` = unlock | Not a toggle — explicit value |

**Temperature encoding:** positive values use 3-digit zero-padded format (`+004`), negative use minus sign (`-18`). Commands are **always in °C** regardless of the fridge's physical display unit setting.

### Examples

```
/S03/1/+04\n    → set left zone to 4°C
/S05/1/-18\n    → set right zone to -18°C
/S00/1/-01\n    → toggle power
/S01/1/001\n    → enable ECO mode
/S01/1/000\n    → enable MAX mode
/S06/1/002\n    → lock control panel
/S06/1/001\n    → unlock control panel
```

---

## Status Notifications

Received from the Notify characteristic (FFF4). Two distinct notification formats are sent periodically.

---

### PRIMARY Notification

Contains **setpoints** (target temperatures) and power/battery state.

#### Format

```
,<L_Setpoint>,<R_Setpoint>,<BattProtect>,<Voltage>,<PowerStatus>\n
```

#### Fields

| Field | Example | Description |
|-------|---------|-------------|
| L_Setpoint | `+04` | Left zone setpoint in **°C** (signed integer) |
| R_Setpoint | `-18` | Right zone setpoint in **°C** (signed integer) |
| BattProtect | `2` | Battery protection level: 1, 2, or 3 |
| Voltage | `127` | Battery voltage × 10 (e.g. `127` = 12.7V) |
| PowerStatus | `1` | `0`=off, `1`=on+unlocked, `2`=on+locked |

#### Notes

- **Always reported in °C**, regardless of the fridge's physical unit mode setting.
- Updates immediately when a setpoint command is accepted by the firmware.
- The PowerStatus field encodes both power state and lock state in a single value.

#### Example

```
,+04,-18,2,127,1\n
→ Left: 4°C setpoint, Right: -18°C setpoint, BattProtect: 2, 12.7V, power on + unlocked
```

---

### SECONDARY Notification

Contains **current physical temperatures** (actual sensor readings) and operational mode state.

#### Format

```
/S00/U/<ZoneCount>,<EcoMax>,<UnitMode>,<L_Temp>,<R_Temp>\n
```

#### Fields

| Field | Example | Description |
|-------|---------|-------------|
| ZoneCount | `2` | Number of active zones (e.g. `2` = dual zone) |
| EcoMax | `1` | `0` = ECO mode active, `1` = MAX mode active |
| UnitMode | `2` | `1` = Celsius display, `2` = Fahrenheit display |
| L_Temp | `+28` | Left zone current temperature in fridge's display unit |
| R_Temp | `-18` | Right zone current temperature in fridge's display unit |

#### Notes

- Reports **current physical sensor readings**, not setpoints.
- Temperatures are in the **fridge's configured display unit** (set via physical buttons). UnitMode indicates which unit is active.
- `EcoMax` reflects the actual compressor mode — no confirmation echo needed.
- There is **no echo behavior** — SECONDARY always reflects real sensor data. When the fridge is at equilibrium, current temp naturally equals setpoint; this is normal, not an echo.

#### Example

```
/S00/U/2,0,2,+28,+32\n
→ dual zone, ECO mode active, Fahrenheit display, left: 28°F current, right: 32°F current
```

---

## Confirmed Behaviors

- **Connection keep-alive:** The fridge firmware treats an active BLE connection as a keep-alive. If the connection drops while the fridge is running, the fridge continues operating normally.
- **Power-off behavior:** When powered off via command, the BLE stack remains active and the fridge continues advertising. Reconnecting BLE while the fridge is off will power it back on — the firmware treats an incoming BLE connection as a wake signal.
- **Command acceptance:** The fridge beeps and the LCD updates when a command is accepted. No beep indicates rejection (e.g. wrong format or write-with-response).
- **Exclusive connection:** Only one BLE central can connect at a time. The Iceco mobile app and HA cannot be connected simultaneously.

---

## Firmware variant: the `/S00/0L/` unified status frame

Some units (confirmed on a **VL PRO Dual Zone**, 2026-08) do **not** send the
PRIMARY (`,...`) or SECONDARY (`/S00/U/...`) notifications above. Instead they
emit a single unified frame on FFF4, roughly every 15–30 s **while powered on**
and also while in standby (compressor off):

```
/S00/0L/<f0>,<f1>,<f2>,<f3>,<f4>,<f5>,<f6>,<f7>,<f8>,<f9>,<f10>,<f11>\n
```

| idx | field | meaning |
|-----|-------|---------|
| f0  | zone count | `2` = dual zone |
| f1  | **power** | `1` = display + compressor on, `0` = standby |
| f2  | unit | `1` = °C, `2` = °F (display unit for f3/f4) |
| f3  | left/zone-1 current temp | in f2's unit |
| f4  | right/zone-2 current temp | in f2's unit |
| f5  | left/zone-1 setpoint | **always °C** |
| f6  | right/zone-2 setpoint | **always °C** |
| f7  | battery protection | `1` = L, `2` = M, `3` = H |
| f8  | input voltage ×10 | e.g. `127` → 12.7 V (12 V pack), `268` → 26.8 V (AC brick) |
| f9  | **mode** | `1` = ECO, `2` = MAX |
| f10 | unknown | constant `0` in all observed states |
| f11 | unknown | constant `000` |

### Commands on this firmware

The command **format** is unchanged (`/S<id>/1/<value>` written no-response to
FFF1), but the **ids differ from the APL35**:

| Function | id / value | status |
|----------|------------|--------|
| Left zone setpoint  | `/S03/1/<±NN>` (°C) | confirmed |
| Right zone setpoint | `/S05/1/<±NN>` (°C) | confirmed |
| Power on  | `/S01/1/001` | confirmed |
| Power off (standby) | `/S01/1/000` | confirmed |
| ECO / MAX | ? | **unknown** — `/S01/1/002` is a no-op; `/S02/1/001` changes setpoints |
| Panel lock | ? | **unknown** |
| Battery protection level | ? | **unknown** |

The APL35 `S00`/`S01`/`S06` ids do **not** apply — sending the APL35 "ECO"
command (`/S01/1/00x`) powers the fridge into standby on this firmware. The
unknown commands need an Android BLE HCI snoop / iOS PacketLogger capture of the
Iceco app to identify.

### Behaviour notes for this firmware

- BLE stays up whenever the unit has DC/AC power, independent of the power
  (standby) state. Connecting does **not** wake it from standby.
- The fridge stops sending frames within ~7 s of a central that goes silent, so a
  periodic GATT read of FFF4 (every ~5 s) is needed to hold the link.
