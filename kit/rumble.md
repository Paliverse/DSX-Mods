# Mod rumble and haptic feedback

DSX accepts `Rumble` as an additive instruction over the existing loopback UDP endpoint or the current-user `DSX.Mod.v1` named pipe. The pipe still uses a four-byte little-endian JSON payload length. Existing instruction numbers and response fields do not change.

## Discover support first

Send `{"Instructions":[{"Type":"GetDSXStatus"}]}` to obtain the current `Devices` list. Each entry has `Index`, `DeviceType`, `ConnectionType` and an additive `IsSupportRumble` Boolean.

- If `IsSupportRumble` is absent, this Engine does not advertise this extension. Older Engines ignore instruction type 9.
- If it is false, do not send rumble to that controller. Capability is controller-specific, not inferred from the connection type.
- If no controller is connected, the empty list advertises no device capability. Query again when a controller connects.
- Capability means the controller can render rumble, not that the user's current profile has enabled it or that DSX is licensed for controller output right now (otherwise the instruction is reported as `NotActivated`). A stop is accepted either way.

Use the `Index` returned by the latest query. Device indices can change when controllers connect or disconnect. Selector `-1` targets the desktop-selected controller; it does not fall back to the first controller when there is no published selection.

## Wire schema

`Rumble` is instruction type **9**, appended after `ToMode` (8). The canonical spelling is `Rumble`; Engine string matching is case-insensitive.

```json
{
  "Instructions": [
    { "Type": "Rumble", "Parameters": [0, 160, 80, 300] }
  ]
}
```

| Parameter | Meaning | Accepted values |
|---|---|---|
| 0 | Controller selector | Existing selector rules: index >= 0, `-1` for selected controller, or `null` for index 0 |
| 1 | Large/left motor | Integer 0–255 |
| 2 | Small/right motor | Integer 0–255 |
| 3 | Duration in milliseconds | Optional integer 1–5000; omitted or `null` defaults to 1000 |

An instruction must contain exactly three or four parameters. Motor and duration values must be integers; out-of-range, missing or fractional values reject the instruction without output and are reported as `InvalidParameter`; a controller without rumble is reported as `Unsupported` (see `Diagnostics` in `README.md`: pipe replies always include them, UDP replies when the request has `"Diagnostics": true`). Integer strings are also accepted for legacy client consistency; emit JSON numbers in new clients. `dsx-mod-v1.schema.json` describes canonical packets, including type 9; see `examples/rumble.json`.

Send `[0, 0, 0]` to stop the mod's contribution immediately. This does **not** stop a game's rumble or disable the user's input/audio haptics.

## Timing and ownership

- Duration is a runtime lease for this controller's mod rumble, not a persisted setting. The Engine sends motor-off when the deadline expires. Maximum requested duration is five seconds, so a mod exiting without a stop message cannot intentionally leave an unbounded effect.
- Use about 10–20 updates per second for continuous effects; choose a duration roughly two or three times the update interval. A resend of identical motors extends the deadline without another controller write.
- Changing nonzero motor values is limited to one accepted change per 20 ms per controller (50 Hz). Faster changes are ignored without changing the current effect or deadline and are reported as `RateLimited`. An explicit zero-motor stop is always admitted. This is an output admission limit, not a global UDP parsing limit.
- The most recently accepted mod instruction owns the controller's single mod-rumble contribution. There is no independent per-mod mixing or authentication token on legacy UDP. Keep UDP loopback-only and do not forward it onto a network.
- Mod and game rumble combine by per-motor maximum. Both continue through the existing Engine output compositor. The user's rumble enable switch and intensity remain authoritative. Existing input/audio feedback and overlay settings retain their behavior.
- `ResetToUserSettings`, endpoint disable/stop, Engine stop, entitlement loss, or controller disconnection clear the contribution. A reconnected controller has a new connection epoch; an old timer cannot drive that connection.
- UDP and a pipe connection closing cannot identify which mod currently owns shared legacy overrides. Bounded duration provides stop-on-exit without resetting another mod's LEDs or trigger effects.
- If a motor-off write fails, Engine retains the pending stop and retries it with backoff (100 ms, doubling up to 2 s). No software API can guarantee a physical stop while the controller transport itself is failing.

## USB and Bluetooth

The instruction has the same logical motor-pair semantics on both connections; do not emit transport-specific HID reports.

| Controller | Rendering |
|---|---|
| DualSense / DualSense Edge | Haptic actuators through firmware-compatible rumble, or the existing Engine Rumble-to-Haptics PCM source when enabled in the user's profile |
| DualShock 4 | Physical rumble motors |
| PSVR2 Sense | Each half's actuator through its side-specific vibration, or the existing Engine Rumble-to-Haptics PCM source when enabled (Bluetooth PCM reports; on USB the half's own audio endpoint) |
| Xbox | Existing supported Engine backend's rumble motors |
| Access / unsupported devices | `IsSupportRumble` false; instruction ignored |

Rumble-to-Haptics over Bluetooth follows the same DSX+ rules as the user's own haptics. `Rumble` cannot start an audio endpoint, select speaker/headset routing, load files, or change those rules.

`Rumble` plays no sound. For haptics waveforms and game-audio routing use `Haptics` (type 10), for the controller speaker `Audio` (type 11); the reply's `IsSupportHaptics` and `IsSupportSpeaker` say which controllers have them. See `README.md`.
