# Room Climate — Deployment Guide

Step-by-step instructions to publish this integration on GitHub and install it
in Home Assistant via HACS.

---

## Prerequisites

- A GitHub account
- Git installed on your machine
- A running Home Assistant instance with HACS installed

---

## Step 1 — Update your identity in the project

Open `custom_components/room_climate/manifest.json` and replace the placeholder
values with your actual GitHub details:

```json
{
  "documentation": "https://github.com/YOUR_GITHUB_USERNAME/room-climate",
  "issue_tracker": "https://github.com/YOUR_GITHUB_USERNAME/room-climate/issues",
  "codeowners": ["@YOUR_GITHUB_USERNAME"]
}
```

Save the file.

---

## Step 2 — Initialize a Git repository

Open a terminal in the project root folder (`room_climate/`) and run:

```powershell
git init
git add .
git commit -m "Room Climate v1.1.0 — virtual climate with calibration, presets, auto mode, fan control, multi-TRV, window detection, diagnostics"
```

---

## Step 3 — Create the GitHub repository

1. Go to **https://github.com/new**
2. Repository name: `room-climate`
3. Description: `Home Assistant integration — unified climate control per room`
4. Visibility: **Public** (required for HACS)
5. **Do NOT** check "Add a README" or "Add .gitignore" — you already have these
6. Click **Create repository**

---

## Step 4 — Push your code

GitHub will show you the "push an existing repository" commands.  Run them:

```powershell
git branch -M main
git remote add origin https://github.com/YOUR_GITHUB_USERNAME/room-climate.git
git push -u origin main
```

If you use SSH instead of HTTPS:

```powershell
git remote add origin git@github.com:YOUR_GITHUB_USERNAME/room-climate.git
git push -u origin main
```

---

## Step 5 — Create a release

HACS requires at least one tagged release.

```powershell
git tag v1.1.0
git push --tags
```

Then on GitHub:

1. Go to your repo → **Releases** (right sidebar)
2. Click **Create a new release**
3. Select the tag: `v1.1.0`
4. Release title: `v1.1.0`
5. Description (optional): paste the feature list from the README
6. Click **Publish release**

---

## Step 6 — Install in Home Assistant via HACS

1. Open Home Assistant in your browser
2. Go to **HACS** in the sidebar
3. Click the **three dots** menu (top right) → **Custom repositories**
4. In the "Repository" field, paste:
   ```
   https://github.com/YOUR_GITHUB_USERNAME/room-climate
   ```
5. Category: **Integration**
6. Click **Add**
7. Close the dialog
8. In the HACS search bar, search for **Room Climate**
9. Click on it → click **Download** → confirm
10. **Restart Home Assistant** (Settings → System → Restart)

---

## Step 7 — Add the integration

1. Go to **Settings → Devices & Services**
2. Click **+ Add Integration** (bottom right)
3. Search for **Room Climate**
4. Follow the guided setup:
   - **Step 1**: Enter a room name and select the primary TRV
   - **Step 2**: Optionally add an AC, temperature sensor, and additional TRVs
   - **Step 3**: Optionally add a window sensor with delay settings
   - **Step 4**: Choose calibration mode (only if temp sensor was added)
   - **Step 5**: Set Eco reduction and Away temperature
5. Done — your entities appear under the new device

---

## Step 8 — Verify everything works

After setup, you should see these entities under your new device:

| Entity | What to check |
|--------|---------------|
| `climate.<room>` | Open the thermostat card. Modes, presets, fan speed (if AC) should all appear. |
| `sensor.<room>_trv_setpoint` | Shows the last setpoint sent to the TRV. Change the target temp and confirm it updates. |
| `sensor.<room>_calibration_offset` | Shows the current offset. Only appears if you added a temp sensor. |
| `binary_sensor.<room>_window_blocked` | Only appears if you added a window sensor. Open/close the window and confirm it toggles. |

Test boost mode:

1. Developer Tools → Services
2. Service: `room_climate.enable_boost`
3. Target: your room climate entity
4. Call the service — confirm the TRV goes to 25 °C and the mode switches to Heat

Test presets:

1. Click the thermostat card
2. Select "Eco" preset — target temperature should drop by 3 °C
3. Select "Comfort" — target returns to the original value
4. Manually adjust temperature — preset clears to "None"

---

## Updating the integration later

When you make code changes:

```powershell
git add .
git commit -m "Description of changes"
git push
```

To release a new version:

1. Update `"version"` in `manifest.json` (e.g., `"1.2.0"`)
2. Commit and push
3. Tag and push:
   ```powershell
   git tag v1.2.0
   git push --tags
   ```
4. Create a new release on GitHub
5. In Home Assistant, HACS will show an update notification

---

## Sharing with others

Once your repo is public with a tagged release, anyone can install it by adding
your repo URL as a custom HACS repository (same as Step 6 above).

To get listed in the **default HACS store** (so users can find it without adding
a custom repo), submit a PR to
[github.com/hacs/default](https://github.com/hacs/default).  Requirements:

- Public GitHub repo with `hacs.json` and `manifest.json`
- At least one tagged release
- `codeowners` filled in `manifest.json`
- A README with install + usage instructions (you already have this)

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| Integration not found after HACS install | Restart HA. HACS downloads files but HA needs a restart to discover them. |
| "This TRV entity is already configured" | The primary TRV is unique per room. You can't use the same TRV in two rooms. |
| Thermostat card shows wrong colors | Make sure `hvac_action` is working: check Developer Tools → States → your climate entity. |
| Calibration offset seems wrong | Check that your external temp sensor and TRV are reporting sensible values in Developer Tools → States. |
| Options changes don't take effect | The integration reloads automatically when you save options. If not, restart HA. |
| Diagnostics | Settings → Devices & Services → Room Climate → your room → 3 dots → Download diagnostics |

---

*That's it. Your integration is live.*
