# Credits

This integration is a fork of **[HA-Iceco-Integration](https://github.com/jeremyroe/HA-Iceco-Integration)**
by **Jeremy Roe** ([@jeremyroe](https://github.com/jeremyroe)), MIT-licensed.

The original provided the Home Assistant scaffolding, the entity model, the
`DataUpdateCoordinator`-as-push pattern, the APL35 protocol reverse-engineering
(`PRIMARY` / `SECONDARY` notifications, the `/S<id>/1/<value>` command format), and
the alarm logic. Thank you.

## What this fork changed

- **BLE connection layer rewritten** — serialised connect/disconnect, a single
  teardown path, `close_stale_connections` before every connect, clean release on
  unload (the original reconnected during shutdown and leaked the link), a
  keep-alive read that stops the fridge hanging up on an idle central, and a
  health check that keys off keep-alive liveness rather than status-frame arrival.
- **`/S00/0L` firmware support** — a new `parse_full_status()` for the unified
  status frame (additive; falls back to the original parsers), and a command map
  reverse-engineered live on a VL PRO Dual Zone:
  `S01` power, `S03`/`S05` setpoints, `S04` battery protection, `S06` mode,
  `S07` display unit.
- **Entity changes** — Mode / Battery Protection / Display Unit as `select`s;
  `hvac_action` on the climate zones; a Low-Battery binary sensor with the
  manual's cut-out/cut-in voltages; dropped the ECO/Lock switches.
- Discovery tightened to the Iceco manufacturer ID; `iot_class` corrected to
  `local_push`.
