# LG webOS PIP for Home Assistant

Show a Home Assistant camera, or any video feed, as a **small picture-in-picture box on your LG TV**, on top of whatever you're watching: live TV, HDMI, Netflix, the home screen. Typical use: someone rings the doorbell and the door camera appears in the corner of the TV for 30 seconds.

```
┌──────────────────────────────────────────┐
│ live TV / HDMI / any app   ┌───────────┐ │
│                            │  camera   │ │
│                            │ Doorbell  │ │
│                            └───────────┘ │
└──────────────────────────────────────────┘
```

The repository has two parts that work together:

| Part | Where | What it does |
|---|---|---|
| **HA PIP** TV app | [`webos-app/`](webos-app) | A webOS app that opens as a transparent overlay window and draws the PIP box. It has its own setup screen for the HA connection and defaults. |
| **LG webOS PIP** integration | [`custom_components/lg_webos_pip/`](custom_components/lg_webos_pip) | A Home Assistant integration with a UI for choosing *what* to show, *when* (triggers), *where* and *for how long*. It launches the TV app through HA's built-in LG webOS TV integration. |

Verified on an LG OLED G4 (webOS 24, firmware 43.21.73) in Developer Mode, without rooting.

## How it works

1. A trigger fires in Home Assistant, e.g. the doorbell's binary sensor turns `on`.
2. The integration calls `webostv.command` → `system.launcher/launch` with the HA PIP app ID and parameters: camera, position, size, timeout.
3. The app opens as an **overlay window** (`"defaultWindowType": "overlay"`, `"transparent": true`). Only the PIP box is visible over the current picture.
4. The app connects to Home Assistant's WebSocket API with a long-lived token and asks HA for a signed stream URL. MJPEG by default; HLS, WebRTC and snapshots are also available.
5. After the timeout, or when you press **Back** / **OK**, the app closes and the TV is exactly as before.

## Requirements

- An LG webOS TV with the **LG webOS TV** integration set up in Home Assistant. Tested: G4 / webOS 24. Older webOS versions may work, untested.
- Home Assistant **2025.3** or newer.
- To install the TV app: the free **Developer Mode** app on the TV and an LG developer account. See [Install the TV app](#1-install-the-tv-app).
- A computer with Node.js 18+ for the webOS CLI.

## Setup

### 1. Install the TV app

The TV app isn't in the LG Content Store, so it's installed through Developer Mode.

1. **Enable Developer Mode on the TV**
   1. Create a free account at [webostv.developer.lge.com](https://webostv.developer.lge.com) and sign in.
   2. On the TV, install **Developer Mode** from the LG Content Store and sign in with that account.
   3. Turn on **Dev Mode Status** (the TV reboots), then open the app again and turn on **Key Server**.
   4. Note the **IP address** and **passphrase** shown in the app.

2. **Install the webOS CLI** on your computer:

   ```bash
   npm install -g @webos-tools/cli
   ```

3. **Register the TV and get its key.** Replace `192.168.1.50` with the TV's IP. Enter the passphrase when asked:

   ```bash
   ares-setup-device -a tv -i "host=192.168.1.50" -i "port=9922" -i "username=prisoner" -i "default=true"
   ares-novacom --device tv --getkey
   ```

   If `--getkey` fails, the Key Server toggle is off. It turns itself off again after a reboot.

4. **Install the app.** Download `io.github.idaddycz.lgwebospip_*.ipk` from the [latest release](https://github.com/iDaddyCz/ha-lg-webos-pip/releases/latest), then:

   ```bash
   ares-install -d tv io.github.idaddycz.lgwebospip_1.0.0_all.ipk
   ```

   Or build it from source: `cd webos-app && npm install && npm run install-tv`.

> **Developer Mode sessions last ~50 hours.** Open the Developer Mode app and press **Extend** now and then, or the TV removes the app when the session expires. A rooted TV with [Homebrew Channel](https://github.com/webosbrew/webos-homebrew-channel) doesn't have this limit.

### 2. Connect the TV app to Home Assistant

The app needs your HA URL and a long-lived access token. Create the token in HA under **your profile → Security → Long-lived access tokens**. A dedicated non-admin HA user for the TV is a good idea. Then do **one** of the following:

- **From Home Assistant (easiest):** enter the URL and token in the integration (step 3). HA sends them to the TV app, and you never type the token with the remote.
- **On the TV:** open **HA PIP** from the TV's app list. The setup screen appears:

  | Setting | |
  |---|---|
  | Home Assistant URL | e.g. `http://192.168.1.10:8123` (use an IP if the TV can't resolve `homeassistant.local`) |
  | Long-lived access token | Type it with the on-screen keyboard. The **LG ThinQ** phone app's keyboard can paste it from your phone. |
  | Test connection | Shows the HA version, the user and how many cameras were found |
  | Camera, Stream, Position, Size, Close after | Defaults, used when HA doesn't say otherwise |
  | Preview | Shows the PIP with the current (unsaved) settings. **OK** or **Back** returns to setup. |

  Navigate with **▲▼**, change choices with **◀▶**, press **OK** to type in a field or press a button. The Magic Remote pointer also works. Press **Save** before exiting.

### 3. Install the Home Assistant integration

**HACS (recommended):** HACS → ⋮ → **Custom repositories** → add `https://github.com/iDaddyCz/ha-lg-webos-pip` as type **Integration**. Install **LG webOS PIP**, then restart Home Assistant.

**Manual:** copy `custom_components/lg_webos_pip` to `/config/custom_components/lg_webos_pip`, then restart Home Assistant.

Then go to **Settings → Devices & services → Add integration → LG webOS PIP**:

| Field | |
|---|---|
| TV | your LG TV's media player (from the LG webOS TV integration) |
| Home Assistant URL as seen from the TV | prefilled with your internal URL |
| Long-lived access token for the TV app | optional; when set, it's sent to the TV app with every launch |
| Default stream type / position / size / close after | defaults for this TV |
| TV app ID | leave as is unless you built the app with another ID |

Everything except the TV can be changed later with **Configure**.

### 4. Add PIP triggers

On the integration page, click **Add PIP trigger**. Each trigger says *when X happens, show Y*:

| Field | |
|---|---|
| Name | e.g. `Doorbell` |
| Trigger entities | one or more entities, e.g. `binary_sensor.doorbell` or `event.doorbell_ring` |
| Trigger state | optional. Empty means binary sensors, switches and input booleans fire on `on`, and everything else (e.g. **event entities**) fires on every change. Set it to fire on a specific state, like `open`. |
| Camera *or* URL | what to show (see [Sources](#sources)) |
| Label, stream type, position, size, close after | optional per-trigger overrides |

Each trigger gets its own device with:
- **Enabled**, a switch to pause the trigger, e.g. at night.
- **Test**, a button that shows the PIP now.

Edit a trigger later with its **⋮ → Reconfigure** menu.

**Nothing is ever sent to a TV that is off.** Triggers and the `show` / `close` actions skip quietly, so automations don't fail. Buttons report that the TV is off.

**Screen-off mode counts as off** (the TV is on with the picture turned off, e.g. for music). No PIP is shown then, since nobody would see it. Only `close` still goes through, so a PIP left open can be dismissed.

The TV also gets three buttons: **Send connection to TV**, **Open setup on TV** and **Close PIP**.

## Using it from automations and scripts

Beyond triggers, you can call the integration's actions anywhere:

```yaml
# Show the driveway camera bottom-left for 20 s when a car arrives
action: lg_webos_pip.show
data:
  camera: camera.driveway
  position: bottom-left
  size: 25
  timeout: 20

# Close it again, e.g. when the door opens
action: lg_webos_pip.close
```

| Action | Fields |
|---|---|
| `lg_webos_pip.show` | `camera` or `url` (required), `title`, `mode`, `position`, `size`, `timeout`, `muted`, `tv` |
| `lg_webos_pip.close` | `tv` |
| `lg_webos_pip.send_connection` | `tv`: sends the URL and token from the integration options to the TV app |

`tv` is only needed when you've set up more than one TV.

### Sources

- **Camera entity**: any HA camera. HA signs the stream URLs, so the token never appears in a URL.
- **URL**:
  - `.m3u8` plays as HLS.
  - URLs that look like MJPEG (`mjpeg`, `.cgi`, `action=stream`) or images display as an image stream.
  - Anything else plays in a video player, e.g. `.mp4`.
  - HA paths such as `/media/local/doorbell.mp4` are signed automatically.

### Stream types

| Type | Notes |
|---|---|
| `mjpeg` (default) | Drawn as an image, so it works over live TV without a second video decoder. HA converts the stream, which costs some HA CPU. Verified on the G4. |
| `snapshot` | Polls still images (2 per second by default). Works with every camera. |
| `hls` | Real video with audio, a few seconds behind. Needs a second hardware decoder while the TV plays something, which depends on the model and content. |
| `webrtc` | Lowest latency (HA 2024.11+ with go2rtc). Same decoder caveat as HLS. |

## Launch parameters (advanced)

To launch the TV app another way (e.g. `webostv.command` directly, or `ares-launch`), these are its parameters:

```yaml
action: webostv.command
target:
  entity_id: media_player.lg_tv
data:
  command: system.launcher/launch
  payload:
    id: io.github.idaddycz.lgwebospip
    params:
      camera: camera.front_door
      timeout: 30
```

| Param | Meaning |
|---|---|
| `camera` / `url` | what to show (`url` wins) |
| `title` | label in the box (default: camera name) |
| `mode` | `mjpeg`, `snapshot`, `hls`, `webrtc` |
| `position` | `top-right`, `top-left`, `bottom-right`, `bottom-left` |
| `size` | width in % of the screen (10–100) |
| `timeout` | seconds until it closes, `0` = until closed |
| `muted` | `false` to play audio (HLS, WebRTC, video URLs) |
| `refresh` | ms between stills in `snapshot` mode (default 500) |
| `close: true` | close the PIP |
| `connect: {url, token}` | store the HA connection on the TV |
| `settings: true` (or no params) | open the setup screen |

Launching again while the PIP is open swaps the feed and restarts the timer.

## Good to know

- **While the PIP is visible it has the remote's focus.** Arrow keys go to the PIP rather than the app underneath, and **Back** or **OK** close it. Keep timeouts short for popups.
- If HA or the camera doesn't answer, the PIP shows the error and retries every 3 s until it times out.
- The token is stored in the TV app's local storage, and in the integration's options if you entered it there.

## Troubleshooting

| Problem | Fix |
|---|---|
| Nothing happens on a trigger | Check the trigger's **Enabled** switch and that the TV's media player is `on`, then press the trigger's **Test** button. Look in **Settings → System → Logs** for `lg_webos_pip`. |
| "The LG webOS TV integration is not set up" | Set up HA's LG webOS TV integration and make sure the TV is paired. |
| PIP shows "Not set up yet" | Enter the URL and token in the integration and press **Send connection to TV**, or use the TV setup screen. |
| "Authentication failed" | The token was deleted or mistyped. Create a new one. |
| Black box, spinner forever | Try `mode: snapshot`. Check that the TV can reach the HA URL (not `homeassistant.local` unless the TV resolves it). |
| App vanished from the TV | The Developer Mode session expired. Extend it and reinstall the app. |
| `ares-novacom --getkey` fails | Turn **Key Server** on in the Developer Mode app. |

## Development

```bash
# TV app: run against a fake Home Assistant in a desktop browser
cd webos-app && npm install
npm run mock                  # then open http://localhost:8124/tv.html
                              #   ?camera=camera.garden&mode=hls  -> PIP
                              #   (no params)                     -> setup screen
npm run install-tv            # build, package and install on the TV registered as "tv"
npm run inspect               # Chrome DevTools for the app on the TV
cp .env.example .env          # optional: bake defaults into your own build (never publish it)

# Integration
python3 -m venv .venv && .venv/bin/pip install -r requirements_test.txt
.venv/bin/pytest
python3 scripts/gen_translations.py   # after editing strings.json
```

Releases: publishing a GitHub release builds the IPK, with the version taken from the tag, and attaches it to the release.

## License

MIT
