# Testing the Plate Scanner on iPhone over the LAN

The app needs **HTTPS** (iOS only allows camera access in a secure context).
A local HTTPS server with a locally-trusted certificate is already set up in this folder.

## Every time: start the server

```powershell
cd "c:\Users\PeterVokrot\OneDrive - Philips\Temp\Plate"
python serve_https.py
```

Then on the phone open:

| Phone is on… | URL |
|---|---|
| Ethernet LAN (192.168.0.x) | `https://192.168.0.11:8443/index.html` |
| Wi-Fi (172.16.x.x) | `https://172.16.17.37:8443/index.html` |

Confirm the running version: the status line at the bottom shows e.g. `(v2.5)`,
also visible in the ⚙︎ Settings header.

**Stick to ONE URL.** The sightings database (IndexedDB) is tied to the exact
origin — `192.168.0.11:8443` and `172.16.17.37:8443` are two separate, empty-at-first
databases. The installed Home-Screen app and a Safari tab are separate too.

## One-time setup (already done — redo only if noted)

1. **Certificate** (done; expires **Oct 2028**): created with mkcert, lives in `certs/`
   (`cert.pem` + `key.pem`), valid for `192.168.0.11`, `192.168.0.5`, `172.16.17.37`,
   `localhost`, `127.0.0.1`.
   *Redo if the PC's IP changes* (DHCP) — in PowerShell:
   ```powershell
   # mkcert was installed via winget; if "mkcert" is not found use the full path under
   # %LOCALAPPDATA%\Microsoft\WinGet\Packages\FiloSottile.mkcert_*\mkcert.exe
   cd "c:\Users\PeterVokrot\OneDrive - Philips\Temp\Plate"
   mkcert -cert-file certs\cert.pem -key-file certs\key.pem <NEW-IP> 192.168.0.11 172.16.17.37 localhost 127.0.0.1
   ```
   then restart `serve_https.py`. (The root CA is unchanged, so the phone does NOT
   need re-trusting.)

2. **Windows firewall** (done, persists): inbound rule "ALPR HTTPS 8443". If it's ever
   missing, from an **elevated** PowerShell:
   ```powershell
   New-NetFirewallRule -DisplayName "ALPR HTTPS 8443" -Direction Inbound -Action Allow -Protocol TCP -LocalPort 8443 -Profile Any
   ```

3. **Trust the CA on the phone** (done for your iPhone; repeat for any new device):
   1. In the phone's Safari, download `https://<PC-IP>:8443/certs/mkcert-rootCA.pem`
      (accept the one-time warning) → "Profile Downloaded".
   2. Settings → General → **VPN & Device Management** → install the mkcert profile.
   3. Settings → General → About → **Certificate Trust Settings** → enable full trust
      for the mkcert root. *(Easy to miss; nothing works without it.)*

4. **Install as app**: open the URL in Safari → Share → **Add to Home Screen**.
   Installed-app storage is exempt from Safari's 7-day eviction — do real scanning
   in the installed app. **Deleting the Home-Screen app deletes its database** —
   Export CSV first if you reinstall.

## Performance & zoom (v3.1)

- **Multi-threaded wasm**: `serve_https.py` sends the COOP/COEP headers that turn on
  cross-origin isolation, which lets the wasm inference backend use multiple CPU
  cores. On iOS the detector is CPU-only (no JSPI for GPU readback), so this is the
  main speed lever. Confirm it's active: ⚙︎ Settings diagnostics line ends with
  `threads ON/<N> cores`. If it says `threads off`, isolation didn't take — check the
  server is `serve_https.py` (not a plain `http.server`) and you fully relaunched the
  app. All app resources are same-origin, so the headers don't block anything.
- **Zoom** (read plates from farther away): pinch the camera preview, or use the Zoom
  slider in ⚙︎ Settings (1–8×). This is digital zoom — it scans a center crop of the
  frame, so the plate is larger to the detector *without* slowing inference. A dashed
  outline shows the scanned region when zoomed.
- **Detector cadence**: "Run detector every N camera frames" in Settings trades box
  latency for lower heat/battery. Higher N keeps the phone cooler on long drives (and
  can raise the effective rate of the frames that do run, since the phone throttles
  less).

## Updating the app on the phone

- Page/CSS/JS changes: close and relaunch the app (the service worker fetches pages
  network-first). Check the version number in the status line.
- Manifest changes (colors, icons, orientation): iOS snapshots these at install —
  remove and re-add the Home-Screen app (Export CSV first!).

## Troubleshooting

- **Black bar in portrait (installed app)**: the iOS 26 web-app container cannot
  render true full-bleed portrait — "black-translucent" (full-screen) mode sizes
  the view 59px short and clips an unpaintable strip at the BOTTOM (verified on
  iOS 26.1 and 26.5.2; WebKit #301994 was the 26.1 variant, supposedly fixed in
  26.2 but the same geometry measured on 26.5.2). No CSS/JS can cover the strip —
  it is outside the drawing surface. The app therefore ships with the opaque
  `black` status-bar style: view below a black system status bar, flush to the
  screen bottom, zero dead pixels. Re-test translucent after iOS updates by
  flipping the meta in `index.html` (see comment there) + reinstall.
  Diagnostics line (⚙︎ Settings) shows the symptom: `viewport` height 59px less
  than `screen` height.

- **Page won't load from the phone**: is `serve_https.py` running? Right IP for the
  phone's network? On corporate Wi-Fi, client-to-client traffic may be blocked by the
  access point — use the home LAN or a personal hotspot.
- **Certificate warning on the phone**: Certificate Trust Settings toggle (step 3.3)
  not enabled, or the PC's IP changed (regenerate cert, step 1).
- **Camera prompt never appears**: you're on plain HTTP, or the cert isn't trusted —
  iOS silently refuses camera on insecure origins.
- **Sightings look missing**: you're probably on the other origin (different IP) or
  in Safari instead of the installed app — same app, different database.
- **Quick server health check from the PC**: `curl.exe -sk https://localhost:8443/index.html -o NUL -w "%{http_code}"` → expect `200`.

## Related files

- `serve_https.py` — the HTTPS static server (port 8443; edit or pass a port argument).
- `certs/` — certificate, key, and the root CA the phone trusts.
- `tools/README.md` — dev tooling (model conversion, regression tests, tuning harnesses).
