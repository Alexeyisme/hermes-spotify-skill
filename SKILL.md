---
name: spotify
description: Control Spotify playback (play, pause, skip, volume, queue, now-playing) via the bundled MCP server. Use for any music request — song, album, artist, playlist — on the user's default Spotify Connect device (e.g. a raspotify Pi or Echo). All auth, device-wake, and scope handling happen inside the MCP server; the agent just calls the tools.
version: 1.0.0
author: Alexey Kislitsin
license: MIT
metadata:
  platform: linux
  requires:
    - ~/.hermes/.spotify_cache (created once via auth.py)
    - SPOTIFY_CLIENT_ID + SPOTIFY_CLIENT_SECRET in ~/.hermes/.env
    - spotify MCP server registered in ~/.hermes/config.yaml
---

# Spotify (MCP)

Control Spotify playback through the `spotify` MCP server. The server wraps
spotipy and hides every fragile bit (env loading, cached scope, device wake,
error mapping). Your only job is to pick the right tool and fill 0–2 args.

## When to Use

Any user request about music playback:

- "play X" / "put on some Y" / "queue Z"
- "pause" / "resume" / "next" / "previous"
- "louder" / "quieter" / "volume 30"
- "shuffle on" / "repeat this song"
- "what's playing?"
- "where's it playing?" (device info)

## Tools

All tools are registered as `mcp_spotify_<name>` and are **first-class native tools** — call them directly like you call `terminal` or `read_file`. Do NOT wrap them in shell commands, do NOT run `hermes tools ...`, do NOT pipe JSON-RPC to the MCP server. Just call the tool.

Example (correct): call `mcp_spotify_list_devices` with `{}`.
Example (wrong): `terminal("hermes tools mcp_spotify_list_devices")`.

| Tool | Args | What it does |
|---|---|---|
| `play` | `query` (str, required), `kind` ("track"/"album"/"artist"/"playlist", default "track"), `device` (str, optional) | Search and play the top result. Wakes dormant devices automatically. |
| `pause` | — | Pause current playback. |
| `resume` | — | Resume current playback. |
| `next_track` | — | Skip forward. |
| `previous_track` | — | Skip back. |
| `volume` | `level` (int 0–100) | Set absolute volume. |
| `volume_adjust` | `delta` (int, e.g. +10, -10) | Relative volume change. |
| `shuffle` | `on` (bool) | Turn shuffle on/off. |
| `repeat` | `mode` ("off"/"track"/"context") | Set repeat mode. |
| `queue` | `query` (str) | Search and queue a track. |
| `now_playing` | — | Get current track, artist, device, progress. |
| `list_devices` | — | List all Spotify Connect devices on the account. |

## Trigger → Tool map

- "play Bohemian Rhapsody" → `play(query="Bohemian Rhapsody")`
- "play Dark Side of the Moon album" → `play(query="Dark Side of the Moon", kind="album")`
- "play some Adele" → `play(query="Adele", kind="artist")`
- "play my chill playlist" → `play(query="chill", kind="playlist")`
- "play on the kitchen speaker" → `play(query=..., device="kitchen")`
- "louder" / "turn it up" → `volume_adjust(delta=10)`
- "quieter" / "turn it down" → `volume_adjust(delta=-10)`
- "volume 40" → `volume(level=40)`
- "pause" → `pause()`
- "resume" / "continue" → `resume()`
- "next" / "skip" → `next_track()`
- "previous" / "back" → `previous_track()`
- "queue X" / "play X next" → `queue(query="X")`
- "shuffle on" → `shuffle(on=true)`
- "repeat this song" → `repeat(mode="track")`
- "what's playing?" → `now_playing()`
- "what devices are there?" → `list_devices()`

## After Playing

Always confirm with the track name and artist from the tool's response, not
a generic "OK done". The tool returns `{"status": "playing", "name": ..., "artist": ..., "device": ...}` — read those fields and tell the user what's actually on.

## Error Handling

Every tool returns a dict. On success it has a `status` field; on failure it
has an `error` field. Common errors:

- `"No Spotify Connect devices visible"` — user needs to open Spotify on
  their phone and tap the device picker to wake discovery, or check that
  raspotify is running on the Pi.
- `"No track found for ..."` — try a simpler/shorter query; Spotify search
  is fuzzy ("adele hello" > "Adele - Hello (Official Music Video)").
- `"Spotify credentials not found"` — user hasn't run `auth.py` yet; point
  them at the README.

Never retry silently more than once. Surface the error to the user verbatim.

## Pitfalls

1. **Don't pass `device=""`** expecting "no device". Omit the arg entirely,
   or don't include it — the server resolves the default.
2. **`kind="playlist"` searches the user's own playlists first** (substring
   match on name), then falls back to public search. So "play my chill
   playlist" and "play chill playlist" both work.
3. **Volume and volume_adjust are separate tools.** Don't call `volume(level=+10)` — use `volume_adjust(delta=10)`.
4. **Repeat mode is three strings.** `"off"`, `"track"`, `"context"` — never `"true"`, `"on"`, `"all"`.
5. **The MCP server reuses one spotipy client across calls.** First call is
   slightly slower (token refresh), rest are fast. Don't add warm-up calls.
6. **Two layers must agree for tools to appear in the agent schema, AND the toolset name is `mcp-spotify` (hyphen), NOT `spotify`.** Registering the server under `mcp_servers` is only half the story. The MCP-generated toolset (`mcp-spotify`) must *also* be listed under `platform_toolsets.<platform>` in `~/.hermes/config.yaml`. **`hermes tools enable spotify` does NOT work** — it enables the unrelated built-in `plugins/spotify/` plugin (tools named `spotify_playback`, `spotify_devices`, etc.), not the MCP skill. And `hermes tools enable mcp-spotify` is rejected with "Unknown toolset" because the CLI only knows hard-coded built-in toolsets. The MCP toolset must be added by **editing `~/.hermes/config.yaml` directly**. Symptom when this step is skipped: `hermes mcp test spotify` shows all 12 tools ✓ and `hermes mcp list` shows ✓ enabled, but the agent has no `mcp_spotify_*` functions in its schema and falls back to subprocess hacks. See `references/mcp-tool-injection-debug.md` for the full diagnosis path.

   > Note: `hermes mcp test` reports **12** (the real skill tools). In the Hermes registry they appear as **16** `mcp_spotify_*` entries because the `mcp[cli]` SDK auto-exposes 4 generic protocol helpers (`list_prompts`, `get_prompt`, `list_resources`, `read_resource`). Both numbers are expected and correct.
7. **Session-baked schema.** Enabling a toolset mid-session does NOT inject tools into the currently-running conversation — the schema was set at session start. Always verify in a fresh session.
8. **Never fall back to raw JSON-RPC subprocess piping or direct spotipy calls as a "workaround"** when tools appear missing. That masks the config bug instead of fixing it. Diagnose the toolset-enable layer first.

## Install (one-time)

See `README.md` in this skill's repo. Summary:

1. Clone `Alexeyisme/hermes-spotify-skill` into `~/.hermes/skills/spotify/`.
2. `~/.hermes/hermes-agent/venv/bin/python -m pip install spotipy "mcp[cli]"`
3. `~/.hermes/hermes-agent/venv/bin/python ~/.hermes/skills/spotify/auth.py` (once).
4. Add to `~/.hermes/config.yaml`:
   ```yaml
   mcp_servers:
     spotify:
       command: "/home/USER/.hermes/hermes-agent/venv/bin/python"
       args: ["/home/USER/.hermes/skills/spotify/spotify_mcp.py"]
   ```
5. **Enable the MCP toolset per platform** (REQUIRED — see Pitfall 6). The `hermes tools enable` CLI does NOT work for MCP toolsets — you must **edit `~/.hermes/config.yaml` directly**, adding `mcp-spotify` (with hyphen) to each platform's list under `platform_toolsets`:
   ```yaml
   platform_toolsets:
     cli:
       - browser
       - ...existing entries...
       - mcp-spotify      # ← add this, alphabetical order
       - ...
     telegram:            # and any other platforms you use (discord, slack, ...)
       - ...
       - mcp-spotify
       - ...
   ```
   ⚠️ Do NOT run `hermes tools enable spotify` — that enables the unrelated built-in `plugins/spotify/` plugin, not this MCP skill.
6. Verify server: `hermes mcp test spotify` → should show "✓ Tools discovered: 12".
7. Restart the gateway (`/restart` in a messaging platform) or exit and relaunch CLI. Tools appear as `mcp_spotify_*` in the agent's schema. Verify with a fresh session: ask "list tools containing spotify" and expect the 12 real tools plus 4 MCP protocol helpers (16 total registry entries).
