# DSX Mod System (protocol v1)

Mods drive DSX controller output (adaptive triggers, lightbar, LEDs, rumble, haptics) and temporary input remaps by sending small JSON packets to DSX on the same PC. This folder is the developer kit:

| File | Use |
|---|---|
| `README.md` | This reference. |
| `rumble.md` | `Rumble` (type 9): timing, rate limit, and how USB and Bluetooth controllers render it. |
| `dsx-mod-v1.schema.json` | JSON Schema for request packets. Add `"$schema": "<path>/dsx-mod-v1.schema.json"` to a packet file for editor validation. |
| `examples/*.json` | Ready-to-send packets. |
| `DsxModClient.cs` | Reference client and tester (.NET 10 SDK, no project): `dotnet run DsxModClient.cs -- examples/lightbar-and-leds.json` |

The schema checks the recommended packet shape and byte ranges. It uses canonical names and explicit controller indices; DSX also accepts older case variants, numeric strings and omitted indices. DSX's reply is authoritative for mode-specific trigger ranges, connected controllers, capabilities and licensing.

## 1. Turn it on

Both transports are off by default. In DSX open **Settings > Networking**:

- **Incoming UDP**: DSX listens on `127.0.0.1` at the shown port (default `6969`). DSX writes the current port to `%LOCALAPPDATA%\DSX\DSX_UDP_PortNumber.txt`; read it instead of hard-coding 6969. Only local programs can reach it, so Windows Firewall does not matter.
- **Mod System**: DSX serves the named pipe `DSX.Mod.v1` for the current Windows user.

The **live feed** on the same tab shows recent packets while the tab is open (up to 100 entries).

## 2. Transports

| | UDP | Named pipe `DSX.Mod.v1` |
|---|---|---|
| Request | One packet per datagram to `127.0.0.1:<port>` | Frame = 4-byte little-endian length + UTF-8 JSON |
| Reply | One datagram back to the sender's address | One frame on the same connection |
| Limits | 65,507 bytes | 65,507 bytes per frame; up to 16 connections; keep the connection open |
| Errors | Valid JSON that is not a DSX packet gets a normal reply (with `InvalidPacket` when the request has `"Diagnostics": true`). A JSON syntax error cannot carry the flag, so it gets a plain reply; the reference client reports it locally | Invalid JSON gets a reply with diagnostics; a bad frame length or a frame cut short closes the connection |

DSX sends one reply for a processed packet. Use a timeout: without a reply, delivery cannot be confirmed.

## 3. Request

```json
{"Diagnostics": true, "Instructions": [
  {"Type": "RGBUpdate", "Parameters": [0, 255, 64, 0, 255]},
  {"Type": "TriggerUpdate", "Parameters": [0, 2, 22, 2, 6, 8]}
]}
```

- At most 128 instructions per packet, at most 64 parameters per instruction. Instructions apply in order.
- `"Diagnostics": true` (optional) asks for the `Diagnostics` array in UDP replies (section 5). Pipe replies always include it. Older DSX versions ignore the flag.
- `"ModId"` (optional): 1-64 characters from `A-Z a-z 0-9 . _ -`, naming your mod in DSX (live feed, the game's mod activity).
- `"AppId"` (optional): the game's Steam app id (integer, a numeric string also works). `Haptics` audio routing (form 2) needs it to find the game's audio. An invalid `ModId` or `AppId` is ignored and reported as `InvalidIdentity`; the rest of the packet still applies.
- What mods may drive: in DSX, **Settings > Networking > Mod system** (expand the card) has a switch each for adaptive triggers (types 1 and 4), LEDs (2, 3, 5, 6), haptics (9 and 10) and audio (11), all on by default. An instruction whose switch is off is refused with `DisabledByUser`; turning a switch off ends what mods were playing in that group and gives the user's profile back. The `Haptics` and `Audio` stops are always allowed.
- `Type` is the ordinal or the name (any letter case). The schema uses the names below.
- `Parameters[0]` selects the controller: an index into the reply's `Devices`, or `-1` for the controller selected in DSX. Omitted or `null` means `0`.
- Parameters are integers. Numeric strings (`"10"`) are accepted for older mods.

| Type | Name | Parameters after the controller index |
|---|---|---|
| 0 | `GetDSXStatus` | none; changes nothing, returns the reply |
| 1 | `TriggerUpdate` | trigger (1 left, 2 right), mode (section 4), up to 11 mode values 0-255 |
| 2 | `RGBUpdate` | red, green, blue 0-255; brightness 0-255 (optional, default 255, scales the color) |
| 3 | `PlayerLED` | five on/off LEDs (`true`/`false` or 1/0). Deprecated: use 6 |
| 4 | `TriggerThreshold` | trigger (0 reset both, 1 left, 2 right), threshold 0-255 (when the emulated trigger reports pressed; not needed for 0) |
| 5 | `MicLED` | 0 on, 1 pulse, 2 off |
| 6 | `PlayerLEDNewRevision` | 0-4 = player 1-5 pattern, 5 = all off |
| 7 | `ResetToUserSettings` | none; drops this controller's output and threshold overrides now |
| 8 | `ToMode` | input, mode (table below) |
| 9 | `Rumble` | large motor 0-255, small motor 0-255, duration 1-5000 ms (optional, default 1000); `[i, 0, 0]` stops. Not applied if any value is invalid. See `rumble.md` |
| 10 | `Haptics` | form, then the form's values (table below). Not applied if any value is invalid |
| 11 | `Audio` | action, then the action's values (table below). Not applied if any value is invalid |

`Haptics` forms (DualSense, DualSense Edge and PS VR2 Sense; over Bluetooth only with DSX+; the reply's `IsSupportHaptics` says so per device):

| Form | Parameters | Effect |
|---|---|---|
| 0 stop | `[i, 0]` | Ends this controller's mod haptics now: preset and routing. Always allowed |
| 1 preset | `[i, 1, waveform, frequency, intensity, duration]` | Waveform 0 sine, 1 square, 2 triangle, 3 sawtooth, 4 white noise, 5 pink noise; frequency 20-500 Hz; intensity 0-255 (255 = the user's own haptics strength, never more; 0 stops); duration 1-5000 ms, optional (default 200). It shares the controller's mod rumble with `Rumble`: the latest wins, a same-value resend extends it, changes are limited to one every 20 ms. While a mod's haptics are active, the controller's other rumble also plays through that waveform |
| 2 audio routing | `[i, 2, gain, band]` | Drives the haptics from the game's own audio: DSX captures the process of `AppId` from the user's DSX game library. Gain 1-100 % of the user's haptics strength; band 0 full, 1 low, 2 high. The game's audio never plays on the controller speaker. While routing runs it replaces the audio source of the user's profile (and what that source played on the speaker) |

Mod haptics end on stop, `ResetToUserSettings`, the 60-second lease below, or when the user turns mod haptics off. Each mod (`ModId`+`AppId`) may send a haptics change once every 20 ms. Changing the waveform, frequency or routing, or stopping, can start or restart the controller's audio stream (0.1-0.3 s; the first preset may play as plain rumble meanwhile), so those changes are limited to one per second per controller. A new `AppId` on a controller replaces the previous game's haptics.

`Audio` actions (controllers with a speaker: DualSense and DualSense Edge on USB, and a USB DualShock 4 V2; over Bluetooth only with DSX+; the reply's `IsSupportSpeaker` says so per device):

| Action | Parameters | Effect |
|---|---|---|
| 0 play | `[i, 0, sampleRate, volume, pcm]` | Plays `pcm` once on the controller speaker: base64 of signed 16-bit little-endian **mono** PCM, 2-32768 bytes (even length), at `sampleRate` 8000-48000 Hz; volume 0-100. A play replaces the mod sound playing on that controller. One play every 50 ms per mod and controller |
| 1 stop | `[i, 1]` | Stops the mod sound playing on this controller now, whichever mod started it (one sound per controller; the last play wins). Always allowed |
| 2 volume | `[i, 2, volume]` | Changes the volume (0-100) of the mod sound playing on this controller now |

Volume 100 peaks at half of full scale; the controller then applies the user's own speaker volume, so a mod is never louder than the user's setting. The sound plays on the speaker only, never on the haptics. If DSX is not already streaming audio to the controller, the first play starts its stream (the sound starts about a second later); DSX stops that stream 5 seconds after the last sound ends. 32768 bytes is about 1 second at 16 kHz: send longer sounds as several plays.

`ToMode` inputs and modes:

| Input | Modes |
|---|---|
| 0 left stick, 1 right stick | 0 passthrough, 1 mouse, 2 scroll, 3 keyboard, 4 flick stick, 5 controller buttons, 6 disabled |
| 2 motion | 0 passthrough, 1 mouse, 2 left stick, 3 right stick, 4 both sticks, 5 keyboard, 6 controller buttons, 7 disabled |
| 3 touchpad | 0 passthrough, 1 mouse, 2 touchpad plus, 3 disabled |

### How long changes last

Mod changes sit on top of the user's profile and are never saved. Every valid packet, including `GetDSXStatus`, keeps all of them alive. DSX drops them about 60 seconds after the last valid packet, when the transport is turned off, or on `ResetToUserSettings`. A `ToMode` remap survives `ResetToUserSettings` and ends with that 60-second lease. Send a packet at least every few seconds while your changes should last.

## 4. Trigger modes (`TriggerUpdate`)

Values are `Parameters[3]` onward. Values outside the listed ranges turn the trigger off and are reported in `Diagnostics`. Zones count from 0 (start of travel) to 9.

| Mode | Name | Values |
|---|---|---|
| 0, 20 | OFF | none |
| 1-7, 9-11 | GAMECUBE, VERY_SOFT, SOFT, HARD, VERY_HARD, HARDEST, RIGID, CHOPPY, MEDIUM, VIBRATE_TRIGGER_PULSE | none (presets) |
| 8 | VIBRATE_TRIGGER | frequency 1-255 Hz |
| 19 | VIBRATE_TRIGGER_10Hz | none |
| 12 | CUSTOM_TRIGGER_VALUES | custom mode 0-16 (1-4 RIGID, RIGID_A, _B, _AB; 5-8 PULSE...; 9-12 VIB_RESISTANCE...; 13-16 VIB_PULSE...; other OFF), then 7 raw bytes |
| 13, 21 | RESISTANCE, FEEDBACK | start zone 0-9, strength 0-8 |
| 16, 22 | SEMI_AUTOMATIC_GUN, WEAPON | start zone 2-7, end zone (start+1)-8, strength 0-8 |
| 17, 23 | AUTOMATIC_GUN, VIBRATION | start zone 0-9, amplitude 0-8, frequency 1-255 |
| 14 | BOW | start zone 0-8, end zone (start+1)-8, strength 0-8, snap 0-8 |
| 15 | GALLOPING | start zone 0-8, end zone (start+1)-9, first foot 0-6, second foot (first+1)-7, frequency 1-255 |
| 18 | MACHINE | start zone 0-8, end zone (start+1)-9, amplitude A 0-7, amplitude B 0-7, frequency 1-255, period 0-255 |
| 24 | SLOPE_FEEDBACK | start zone 0-8, end zone (start+1)-9, start strength 1-8, end strength 1-8 |
| 25 | MULTIPLE_POSITION_FEEDBACK | 10 strengths 0-8, zone 0 first |
| 26 | MULTIPLE_POSITION_VIBRATION | 10 amplitudes 0-8, zone 0 first, then frequency (0 = 10 Hz) |

Strength, amplitude or frequency 0 turns the effect off without a diagnostic. Older DSX documentation put the frequency of mode 26 first; DSX reads it last.

## 5. Reply

```json
{
  "Status": "DSX Received UDP Instructions",
  "TimeReceived": "2026-10-09T23:41:07.1234567+02:00",
  "isControllerConnected": true,
  "BatteryLevel": 80,
  "Devices": [{"Index": 0, "MacAddress": "A0:B1:C2:D3:E4:F5", "DeviceType": 0, "ConnectionType": 1, "BatteryLevel": 80,
               "IsSupportAT": true, "IsSupportLightBar": true, "IsSupportPlayerLED": true,
               "IsSupportLegacyPlayerLED": true, "IsSupportMicLED": true, "IsSupportRumble": true,
               "IsSupportHaptics": true, "IsSupportSpeaker": true}],
  "Diagnostics": [{"Instruction": 1, "Code": "NoController", "Message": "No controller at index 3. ..."}]
}
```

- `Status` is `DSX Received UDP Instructions` (UDP) or `DSX Received Instructions` (pipe).
- `isControllerConnected` and `BatteryLevel` (0-100) describe the controller targeted by the first non-status instruction, or the controller selected in DSX.
- `Devices` lists connected controllers in Engine admission order, starting at index 0. Disconnecting a controller compacts the surviving indices; reconnecting appends it after the survivors. A descriptor/capability refresh does not reorder it. Match on `MacAddress` or use `-1` rather than retaining an index across connection changes.
- `IsSupportLegacyPlayerLED` retains the Beta 2 meaning: true only for an identified **new-revision DualSense**, not every controller with player LEDs. Edge, DualShock 4 and old-revision DualSense report false. An unknown revision reports false until the Engine's existing firmware read succeeds; a later status reply reflects that refresh without opening a UI page. `IsSupportPlayerLED` remains the generic player-LED output capability.
- `DeviceType` / `ConnectionType` are numbers over UDP and names over the pipe. UDP device types: 0 DualSense, 1 DualSense Edge, 2 DualShock 4 v1, 3 DualShock 4 v2, 4 DualShock 4 wireless adapter, 5 PS VR2 Sense left, 6 PS VR2 Sense right, 7 Access controller, 8-11 Razer Wolverine V2 Pro / Raiju V3 Pro (wired, dongle), 12 Xbox 360, 13 Xbox One S, -1 other. UDP connection types: 0 USB, 1 Bluetooth, 2 wireless receiver.
- Ignore fields you do not know; new fields may be added.

### Diagnostics

`Diagnostics` explains anything DSX did not apply as written. Pipe replies always include it. UDP replies include it only when the request has `"Diagnostics": true`, so replies to existing mods keep their size. It is empty when the whole packet was accepted and holds at most 32 entries of at most 512 characters. `Instruction` is the index in your `Instructions` array; it is absent for problems with the whole packet. Read `Code` in code and show `Message` to developers. Messages use the mode names in section 4.

| Code | Meaning | Effect |
|---|---|---|
| `InvalidPacket` | Not JSON, no `Instructions` array, or a limit exceeded. The message includes the parser position. | Nothing applied |
| `InvalidInstruction` | Not an object, or missing/unknown `Type` | Instruction skipped |
| `InvalidParameter` | Missing, non-integer or out-of-range value, or trigger values outside the mode's ranges | Types 1-8: applied the legacy way (bytes wrap, unknown modes fall back, invalid trigger values turn the trigger off); fix the value. `Rumble`: not applied |
| `NoController` | Index not connected, `-1` with nothing selected in DSX, or index not an integer | Not applied |
| `NotActivated` | DSX is not licensed for controller output right now, or `Audio` over Bluetooth without DSX+ | Not applied |
| `Unsupported` | The controller has no such output (for example adaptive triggers on a DualShock 4), or for `Haptics`: no haptics stream, or audio routing without `AppId` or with an `AppId` that is not in the user's DSX game library; for `Audio`: no speaker, or the controller's audio output is off | No visible effect; `Rumble`, `Haptics`, `Audio`: not applied |
| `RateLimited` | A `Rumble` motor change arrived within 20 ms of the previous change for that controller; a `Haptics` change within 20 ms for that mod, or a waveform, frequency, routing or stop change within 1 s for that controller; an `Audio` play within 50 ms for that mod and controller | Not applied; the current effect continues |
| `DisabledByUser` | The user turned off what this instruction drives (adaptive triggers, LEDs, haptics or audio) in Settings > Networking | Not applied |
| `InvalidIdentity` | `ModId` or `AppId` present but invalid | Identity ignored; the rest of the packet applies |

DSX checks values before it looks for a controller, so you can validate packets with no controller connected.

## 6. Troubleshooting

| Symptom | Check |
|---|---|
| No reply (timeout) | DSX is running; the transport is on in **Settings > Networking**; you send to `127.0.0.1` and the port in `DSX_UDP_PortNumber.txt`; no other program uses that port (change the port in DSX if it does). |
| Reply, but nothing changes | Read `Diagnostics` (over UDP, send `"Diagnostics": true`). |
| Works, then stops after a minute | Keep sending packets, even just `GetDSXStatus`, while the effect should last (section 3). |
| Unsure what DSX received | Settings > Networking live feed. |

## 7. Versioning

This document is protocol v1, shared by UDP and `DSX.Mod.v1`. Changes are additive: new instruction types get the next ordinal, replies gain fields. Detect features from the reply (for example `Diagnostics` or a device's `IsSupport*` flag), not from the DSX version.
