# hermes-spotify-skill

Spotify playback control for [Hermes Agent](https://github.com/NousResearch/hermes-agent) on Linux / Raspberry Pi.

Since **v1.0.0** this skill ships as a thin MCP server (`spotify_mcp.py`) plus a ~1.5KB `SKILL.md`. The MCP server exposes 12 tools — `play`, `pause`, `resume`, `next_track`, `previous_track`, `volume`, `volume_adjust`, `shuffle`, `repeat`, `queue`, `now_playing`, `list_devices` — and hides all the fragile bits (OAuth cache, scope handling, device wake, error mapping) inside Python. The agent just picks a tool and fills 0–2 args, which is exactly what smaller/local models are good at.

**How it works:** `spotify_mcp.py` is a stdio MCP server that wraps [spotipy](https://github.com/spotipy-dev/spotipy). Hermes' built-in MCP client (see the [`native-mcp` skill](https://github.com/NousResearch/hermes-agent)) spawns it at startup, discovers the tools, and registers them as `mcp_spotify_*`. No daemon, no HTTP, no separate service.

The two existing Spotify skills in the Hermes community hub are macOS-only. This one works on any headless Linux box, tested on Raspberry Pi OS Lite Bookworm 64-bit.

---

## Setup instructions

> **For the agent:** follow these steps in order. Do everything you can autonomously. When a step says **ASK THE USER**, stop and guide them through it — they will need to interact with a browser or a third-party website.

### Step 1: Install Python dependencies

Run this in a **terminal** session:

```bash
~/.hermes/hermes-agent/venv/bin/python -m pip install spotipy "mcp[cli]"
```

- `spotipy` — Spotify Web API client used by the MCP server
- `mcp[cli]` — Model Context Protocol Python SDK

If the Hermes venv is at a different path, look for `~/.hermes/hermes-agent/venv/bin/python` or `~/.hermes/venv/bin/python`.

### Step 2: Install the skill

```bash
# Clone the repo to a temporary location
git clone https://github.com/Alexeyisme/hermes-spotify-skill.git /tmp/hermes-spotify-skill

# Copy the skill files into Hermes
mkdir -p ~/.hermes/skills/spotify
cp /tmp/hermes-spotify-skill/SKILL.md       ~/.hermes/skills/spotify/
cp /tmp/hermes-spotify-skill/spotify_mcp.py ~/.hermes/skills/spotify/
cp /tmp/hermes-spotify-skill/auth.py        ~/.hermes/skills/spotify/

# Clean up
rm -rf /tmp/hermes-spotify-skill
```

Verify the skill files exist:

```bash
ls -l ~/.hermes/skills/spotify/
```

You should see `SKILL.md`, `spotify_mcp.py`, and `auth.py`.

### Step 3: Create a Spotify Developer App

**ASK THE USER** to do the following. Guide them step by step and wait for them to provide the Client ID and Client Secret before continuing.

Tell the user:

1. Go to [developer.spotify.com/dashboard](https://developer.spotify.com/dashboard) and log in with your Spotify account
2. Click **Create app**
3. Fill in:
   - **App name**: anything (e.g. "Hermes Spotify")
   - **App description**: anything (e.g. "Voice control via Hermes")
   - **Redirect URI**: enter **exactly** `http://127.0.0.1:8888/callback` and click **Add**
   - Check **Web API** under "Which API/SDKs are you planning to use?"
4. Click **Save**
5. On the app page, click **Settings**
6. Copy the **Client ID** and **Client Secret** and paste them here

> **Important details to tell the user:**
> - Spotify rejects `localhost` — must use `127.0.0.1`
> - The port (`8888`) and path (`/callback`) must match exactly
> - A Spotify Premium account is required for playback control

### Step 4: Save credentials

Once the user provides Client ID and Client Secret, save them to `~/.hermes/.env`.

> **Security note for agents:** receive the credentials from the user and write them directly to `.env` using the code below. Do not echo, print, or log the raw credential values in your output — they should only appear in the `.env` file.

```python
from pathlib import Path

env_path = Path.home() / ".hermes" / ".env"
existing = env_path.read_text() if env_path.exists() else ""

# Update or append SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET
new_vars = {
    "SPOTIFY_CLIENT_ID": "THE_CLIENT_ID_FROM_USER",
    "SPOTIFY_CLIENT_SECRET": "THE_CLIENT_SECRET_FROM_USER",
}
lines = existing.splitlines() if existing else []
updated_keys = set()
new_lines = []
for line in lines:
    stripped = line.strip()
    if stripped and not stripped.startswith("#") and "=" in stripped:
        key = stripped.split("=", 1)[0].strip()
        if key in new_vars:
            new_lines.append(f"{key}={new_vars[key]}")
            updated_keys.add(key)
            continue
    new_lines.append(line)
for key, value in new_vars.items():
    if key not in updated_keys:
        new_lines.append(f"{key}={value}")

env_path.write_text("\n".join(new_lines) + "\n")
env_path.chmod(0o600)
print("Credentials saved to ~/.hermes/.env")
```

### Step 5: Run the OAuth flow

**ASK THE USER** to complete the browser-based authorization. Guide them through it.

Run the auth script in a **terminal** session (not `execute_code` — the script requires interactive keyboard input):

```bash
~/.hermes/hermes-agent/venv/bin/python ~/.hermes/skills/spotify/auth.py
```

The script will:
1. Detect the saved credentials (or prompt for them if missing)
2. Print a long authorization URL

Tell the user:

1. **Copy the URL** and open it in a browser on any device (phone, laptop, etc.)
2. **Log in to Spotify** and click **Agree**
3. The browser will redirect to a `http://127.0.0.1:8888/callback?code=...` URL that **fails to load** — this is expected and correct
4. **Copy the entire URL** from the browser address bar and paste it back into the terminal

After the user pastes the URL, the script exchanges the code for tokens, caches them, and lists available Spotify devices.

If the script reports success, the skill is ready to use.

### Step 6: Configure default playback device (optional)

If the user has a preferred Spotify Connect device (e.g. a Raspberry Pi running raspotify), set it as the default:

```bash
echo "SPOTIFY_DEFAULT_DEVICE=device-name-here" >> ~/.hermes/.env
```

The name is matched case-insensitively as a substring. If not configured, the first available device is used.

### Step 7: Register the MCP server with Hermes

Edit `~/.hermes/config.yaml` and add the Spotify server under `mcp_servers`. Substitute `USER` with the actual user (e.g. `bb` or `homunculus`):

```yaml
mcp_servers:
  spotify:
    command: "/home/USER/.hermes/hermes-agent/venv/bin/python"
    args: ["/home/USER/.hermes/skills/spotify/spotify_mcp.py"]
    timeout: 30
```

Then **restart Hermes**. On startup you should see the 12 tools discovered and registered as `mcp_spotify_play`, `mcp_spotify_pause`, etc.

Quick check from the command line (no Hermes needed):

```bash
~/.hermes/hermes-agent/venv/bin/python ~/.hermes/skills/spotify/spotify_mcp.py --list-tools
```

This prints the 12 tool signatures without starting the server — useful for sanity-checking after an upgrade.

### Step 8: Verify

Tell the user the skill is installed and ready. Offer to test it by playing a song. Use the patterns from the SKILL.md to search for a track and start playback.

If no active devices are found, tell the user to open the Spotify app on their phone briefly (just tap the device picker icon) to wake up Spotify Connect discovery.

---

## Optional: Setting up raspotify

[raspotify](https://github.com/dtcooper/raspotify) turns a Raspberry Pi into a Spotify Connect speaker. If the user wants this, guide them through it:

```bash
curl -sL https://dtcooper.github.io/raspotify/install.sh | sh
```

Then edit `/etc/raspotify/conf`:

```ini
LIBRESPOT_NAME="YourPiName"
LIBRESPOT_DEVICE_TYPE="speaker"
LIBRESPOT_BITRATE="320"
LIBRESPOT_INITIAL_VOLUME="40"
```

Restart:

```bash
sudo systemctl restart raspotify
```

After this, set the default device to match:

```bash
echo "SPOTIFY_DEFAULT_DEVICE=YourPiName" >> ~/.hermes/.env
```

---

## Troubleshooting

| Problem | Cause | Fix |
|---------|-------|-----|
| `INVALID_CLIENT: Invalid redirect URI` | Redirect URI in Spotify dev app doesn't match | Must be exactly `http://127.0.0.1:8888/callback` — no trailing slash, no https, no localhost |
| `No active device found` / `No Spotify Connect devices visible` | No Spotify Connect device is warm | Open Spotify on phone and tap device picker, or check `sudo systemctl status raspotify` |
| `401 Unauthorized` | Token expired or revoked | Re-run `auth.py` |
| `mcp_spotify_*` tools not registered in Hermes | MCP server not configured or mcp package missing | Verify `mcp_servers.spotify` in `~/.hermes/config.yaml` and that `mcp[cli]` is installed in the venv; check Hermes startup logs |
| `Spotify credentials not found` on first tool call | `auth.py` never run, or `.env` missing `SPOTIFY_CLIENT_ID` / `SPOTIFY_CLIENT_SECRET` | Run Step 4 + Step 5 of setup |
| Hermes doesn't recognize the skill | Skill files not in the right place | Check `~/.hermes/skills/spotify/{SKILL.md,spotify_mcp.py,auth.py}` all exist; restart Hermes |

---

## What the skill can do

Once installed and registered as an MCP server, the user can ask Hermes things like:

- "Play Bohemian Rhapsody" → `mcp_spotify_play(query="Bohemian Rhapsody")`
- "Play Dark Side of the Moon album" → `mcp_spotify_play(query="Dark Side of the Moon", kind="album")`
- "Put on some Queen" → `mcp_spotify_play(query="Queen", kind="artist")`
- "Play my chill playlist" → `mcp_spotify_play(query="chill", kind="playlist")`
- "Pause" / "Resume" / "Next" / "Previous"
- "Louder" / "Quieter" / "Set volume to 30"
- "What's currently playing?" → `mcp_spotify_now_playing()`
- "What devices are available?" → `mcp_spotify_list_devices()`
- "Turn on shuffle" / "Repeat this song"
- "Queue this song next"

See `SKILL.md` for the full trigger → tool map.

---

## Revoking access

If the user wants to disconnect Hermes from their Spotify account:

1. Go to [spotify.com/account/apps](https://www.spotify.com/account/apps/)
2. Find the app (e.g. "Hermes Spotify") and click **Remove Access**
3. Delete the local token cache: `rm ~/.hermes/.spotify_cache`
4. Optionally remove the credentials from `~/.hermes/.env` (delete the `SPOTIFY_CLIENT_ID` and `SPOTIFY_CLIENT_SECRET` lines)

---

## Tested environment

- Raspberry Pi 4B, 4 GB RAM, Pi OS Lite Bookworm 64-bit
- Hermes Agent v0.8.0, Python 3.11, spotipy 2.24+
- Claude Haiku 4.5 via OpenRouter
- raspotify for Pi-as-speaker

## License

MIT — see [LICENSE](LICENSE).

## Credits

- [Hermes Agent](https://github.com/NousResearch/hermes-agent) by NousResearch
- [spotipy](https://github.com/spotipy-dev/spotipy) by Paul Lamere and contributors
- [raspotify](https://github.com/dtcooper/raspotify) by dtcooper
