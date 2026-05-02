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

If the MCP tools aren't registered, fall back to the legacy spotipy patterns
in `SKILL.md.legacy` (kept for reference only — prefer the MCP tools).

## Tools

All tools are registered as `mcp_spotify_<name>`.

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
5. Restart Hermes.
