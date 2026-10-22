# Iceco for Home Assistant

<p align="center">
  <img src="assets/iceco.png" alt="ICECO" width="120" />
</p>

Home Assistant integration for Iceco portable dual-zone Bluetooth refrigerators.

> Forked from [jeremyroe/HA-Iceco-Integration](https://github.com/jeremyroe/HA-Iceco-Integration)
> (MIT). This version reworks the BLE connection layer and adds support for the
> newer **`/S00/0L`** firmware (single unified status frame, different command
> map) found on the **VL PRO Dual Zone** and similar units. See [CREDITS.md](CREDITS.md).

# Installation

There are two main ways to install this custom component within your Home Assistant instance:

1. Using HACS (see https://hacs.xyz/ for installation instructions if you do not already have it installed):

   1. From within Home Assistant, click on the link to **HACS**
   2. Click the three-dot menu (⋮) in the top right corner and select **Custom repositories**
   3. Enter the URL for this repository in the section that says _Add custom repository URL_ and select **Integration** in the _Category_ dropdown list
   4. Click the **ADD** button
   5. Close the _Custom repositories_ window
   6. Search for **Iceco** in HACS and select it from the results (HACS uses a single unified search/filter list rather than separate category tabs)
   7. Click to download/install it, and proceed with any on-screen instructions
   8. Restart your Home Assistant instance and then proceed to the _Configuration_ section below.

2. Manual Installation:
   1. Download or clone this repository
   2. Copy the contents of the folder **custom_components/iceco** into the same file structure on your Home Assistant instance
      - An easy way to do this is using the [Samba add-on](https://www.home-assistant.io/getting-started/configuration/#editing-configuration-via-sambawindows-networking), but feel free to do so however you want
   3. Restart your Home Assistant instance and then proceed to the _Configuration_ section below.

While the manual installation above seems like less steps, it's important to note that you will not be able to see updates to this custom component unless you are subscribed to the watch list. You will then have to repeat each step in the process. By using HACS, you'll be able to see that an update is available and easily update the custom component.

# Configuration

There is a config flow for this integration. After installing the custom component:

1. Power the refrigerator on so it advertises over Bluetooth
2. Go to **Settings** → **Devices & services**
3. Home Assistant should auto-discover the fridge — click **Configure**, or click **+ Add integration** and search for **Iceco**
4. Confirm the discovered device (or enter its Bluetooth address manually)

Only one Bluetooth central can connect to the fridge at a time, so turn the **BLE Connection** switch off before using the Iceco phone app.

---

## Entities

| Section | Entity | Notes |
|---|---|---|
| Controls | **Left Zone**, **Right Zone** | `climate` — setpoint, on/off, and a derived `hvac_action` (Cooling / Idle / Off) |
| Controls | **Power** | display + compressor on/off |
| Configuration | **Mode** | ECO / MAX |
| Configuration | **Battery Protection** | Low / Medium / High low-voltage cut-off |
| Configuration | **Display Unit** | °C / °F shown on the fridge's own screen |
| Configuration | **BLE Connection** | turn off to release the fridge for the phone app |
| Sensors | **Low Battery** | supply voltage at/below the compressor cut-out for the active level |
| Sensors | **Power Loss Alarm** | fridge unreachable for the configured timeout |
| Sensors | **Left / Right Zone Temperature Alarm** | zone drifted from setpoint past the threshold for the configured duration |
| Diagnostic | **Battery Voltage** | with the protection level and cut-out / cut-in voltages as attributes |

## Compatibility

| Firmware | Status |
|---|---|
| `/S00/0L` unified frame — ICECO **VL PRO Dual Zone** (confirmed) | ✅ full support |
| APL35 `PRIMARY` / `SECONDARY` frames | 🟡 parsed via the original code path; command routing is not yet firmware-conditional |

## Protocol

Status frame on characteristic `FFF4`, roughly every 15–30 s:

```
/S00/0L/<zones>,<power>,<unit>,<L_cur>,<R_cur>,<L_set>,<R_set>,<battProt>,<voltage>,<mode>,<f10>,<f11>
```

Commands, written no-response to `FFF1` as `/S<id>/1/<value>\n`:

| id | function | values |
|----|----------|--------|
| `S01` | power | `001` on · `000` standby |
| `S03` | left setpoint | signed °C — `/S03/1/+04`, `/S03/1/-18` |
| `S04` | battery protection | `001` Low · `002` Medium · `003` High |
| `S05` | right setpoint | signed °C |
| `S06` | mode | `001` ECO · `002` MAX |
| `S07` | display unit | `001` °C · `002` °F |

Full field map and reverse-engineering notes: [PROTOCOL.md](PROTOCOL.md).

## Notes & limitations

- The panel lock has no known command or status field on `/S00/0L` and the Iceco
  app doesn't expose it — there is no lock entity.
- `f10` / `f11` in the status frame are unidentified (constant `0` / `000` so far).
- `iceco.send_command` is a debug service that writes an arbitrary string to
  `FFF1` — for further reverse-engineering only.
