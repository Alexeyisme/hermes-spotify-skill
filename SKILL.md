---
name: spotify
description: Control Spotify playback via spotipy on a Linux machine (tested on Raspberry Pi). Use for any music playback request — play a song/album/artist, pause, skip, change device, get current track, browse playlists. Plays on the user's configured default device (typically a local raspotify speaker), but commands can target any Spotify Connect device on the user's account.
version: 0.2.0
license: MIT
metadata:
  platform: raspberry-pi
  requires:
    - spotipy installed in ~/.hermes/hermes-agent/venv
    - cached oauth token at ~/.hermes/.spotify_cache
    - client credentials in ~/.hermes/.env (SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET)
---

# Spotify control via spotipy

This skill controls a Spotify Premium account using the spotipy Python library and a cached OAuth token. Use the code_execution tool to write and run small Python snippets that follow the patterns below.

## Critical setup info

- Python interpreter to use: ~/.hermes/hermes-agent/venv/bin/python (this is where spotipy is installed). When using code_execution, this is the default Python and you do not need to do anything special — just import spotipy.
- Credentials: `SPOTIFY_CLIENT_ID` and `SPOTIFY_CLIENT_SECRET` environment variables, loaded from `~/.hermes/.env`. Legacy fallback: if env vars are missing, reads `~/.hermes/.spotify_credentials` (two lines, client_id then client_secret).
- Token cache: ~/.hermes/.spotify_cache — managed by spotipy SpotifyOAuth, auto-refreshes. Never modify this file manually.
- Default playback device: determined by the `SPOTIFY_DEFAULT_DEVICE` environment variable, or the contents of `~/.hermes/.spotify_device` (a single-line file with the device name). If neither is set, the skill falls back to the first available device. Typically this is the local machine running raspotify. When a user says "play X" without specifying a device, target the default device.
- Other devices on this account may include the user's iPhone, MacBook, Amazon Echo, etc. Always call sp.devices() first if you need to confirm what's available.

### Configuring the default device

Set your preferred Spotify Connect device name in one of two ways:

1. **Environment variable** (recommended): add `SPOTIFY_DEFAULT_DEVICE=your-device-name` to `~/.hermes/.env`
2. **Config file**: write the device name to `~/.hermes/.spotify_device` (one line, just the name)

The device name is matched case-insensitively as a substring, so `"raspberrypi"` will match a device called `"RaspberryPi-Living-Room"`. If no default is configured, the first available device is used.

## The standard initialization snippet

Every spotipy operation starts with this. Use it as the prelude to any action:

```python
import os
import spotipy
from spotipy.oauth2 import SpotifyOAuth
from pathlib import Path

# Load ~/.hermes/.env into environment (if it exists)
env_file = Path.home() / ".hermes" / ".env"
if env_file.exists():
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())

# Read credentials: prefer env vars, fall back to legacy credentials file
client_id = os.environ.get("SPOTIFY_CLIENT_ID", "").strip()
client_secret = os.environ.get("SPOTIFY_CLIENT_SECRET", "").strip()
if not client_id or not client_secret:
    creds_file = Path.home() / ".hermes" / ".spotify_credentials"
    if creds_file.exists():
        lines = creds_file.read_text().strip().split("\n")
        client_id, client_secret = lines[0], lines[1]

auth = SpotifyOAuth(
    client_id=client_id,
    client_secret=client_secret,
    redirect_uri="http://127.0.0.1:8888/callback",
    scope="user-read-playback-state user-modify-playback-state user-read-currently-playing playlist-read-private playlist-read-collaborative user-library-read user-top-read user-read-recently-played streaming",
    cache_path=str(Path.home() / ".hermes" / ".spotify_cache"),
    open_browser=False,
)
sp = spotipy.Spotify(auth_manager=auth)
```

## Finding the right device

Before issuing playback commands, you usually want to target a specific device. Use the default device name from config, falling back to the first available device.

```python
import os
from pathlib import Path

def get_default_device_name():
    """Read the user's preferred device name from env var or config file."""
    name = os.environ.get("SPOTIFY_DEFAULT_DEVICE", "").strip()
    if name:
        return name
    device_file = Path.home() / ".hermes" / ".spotify_device"
    if device_file.exists():
        name = device_file.read_text().strip()
        if name:
            return name
    return None

def find_device(sp, name_hint=None):
    devices = sp.devices()["devices"]
    if not devices:
        return None
    if name_hint:
        for d in devices:
            if name_hint.lower() in d["name"].lower():
                return d
    return devices[0]

default_name = get_default_device_name()
device = find_device(sp, default_name)
device_id = device["id"] if device else None
```

If no devices appear at all, the user needs to wake one. Spotify Connect devices only show up while they are warm. raspotify on the Pi is usually always warm. If iPhone or MacBook are needed, the user has to open the Spotify app on those briefly.

## Common operations

### Search and play a track

```python
results = sp.search(q="Bohemian Rhapsody Queen", type="track", limit=1)
items = results["tracks"]["items"]
if not items:
    print("No track found")
else:
    track = items[0]
    sp.start_playback(device_id=device_id, uris=[track["uri"]])
    print(f"Playing: {track['name']} by {track['artists'][0]['name']}")
```

### Search and play an album

```python
results = sp.search(q="Dark Side of the Moon Pink Floyd", type="album", limit=1)
albums = results["albums"]["items"]
if albums:
    album_uri = albums[0]["uri"]
    sp.start_playback(device_id=device_id, context_uri=album_uri)
```

### Search and play an artist's top tracks

```python
results = sp.search(q="Queen", type="artist", limit=1)
artists = results["artists"]["items"]
if artists:
    artist_id = artists[0]["id"]
    top = sp.artist_top_tracks(artist_id)["tracks"]
    sp.start_playback(device_id=device_id, uris=[t["uri"] for t in top])
```

### Pause / resume / skip

```python
sp.pause_playback(device_id=device_id)
sp.start_playback(device_id=device_id)  # resume
sp.next_track(device_id=device_id)
sp.previous_track(device_id=device_id)
```

### Volume

```python
sp.volume(50, device_id=device_id)  # 0-100
```

### Currently playing

```python
current = sp.current_playback()
if current and current.get("item"):
    track = current["item"]
    print(f"Now playing: {track['name']} by {track['artists'][0]['name']}")
    print(f"On device: {current['device']['name']}")
    print(f"Progress: {current['progress_ms'] // 1000}s / {track['duration_ms'] // 1000}s")
else:
    print("Nothing currently playing")
```

### Switch playback to another device

```python
target = find_device(sp, "iphone")
if target:
    sp.transfer_playback(device_id=target["id"], force_play=True)
```

### Wake up an inactive device

If a device is registered in your Spotify account but showing `is_active: false` (dormant/asleep), use `transfer_playback()` with `force_play=True` to forcefully wake it up and start playback:

```python
device_id = "a31aad2b-76b0-4954-bdb8-a164c0a70b4f_amzn_1"  # example Echo device
try:
    sp.transfer_playback(device_id=device_id, force_play=True)
    print("Device woken and playback transferred")
except spotipy.exceptions.SpotifyException as e:
    print(f"Device unreachable: {e.msg}")
```

Unlike `start_playback()`, this method doesn't require specifying what to play. The `force_play=True` parameter tells Spotify to activate the device even if it was dormant. If the device is truly offline or unreachable, it will still fail with a 404, but for asleep/dormant devices, this wakes them and begins playback of whatever is queued.

### List user's playlists

```python
playlists = sp.current_user_playlists(limit=20)["items"]
for p in playlists:
    print(f"{p['name']} ({p['tracks']['total']} tracks)")
```

### Play a specific playlist by name fragment

```python
playlists = sp.current_user_playlists(limit=50)["items"]
match = next((p for p in playlists if "chill" in p["name"].lower()), None)
if match:
    sp.start_playback(device_id=device_id, context_uri=match["uri"])
```

### Add current song to liked tracks

```python
current = sp.current_playback()
if current and current.get("item"):
    sp.current_user_saved_tracks_add([current["item"]["id"]])
```

### Add a track to the queue

```python
results = sp.search(q="Never Gonna Give You Up", type="track", limit=1)
if results["tracks"]["items"]:
    sp.add_to_queue(uri=results["tracks"]["items"][0]["uri"], device_id=device_id)
    print(f"Added to queue: {results['tracks']['items'][0]['name']}")
```

### Toggle shuffle / repeat

```python
sp.shuffle(True, device_id=device_id)   # True = on, False = off
sp.repeat("track", device_id=device_id)  # "track", "context", or "off"
```

## Error handling

The most common spotipy exception is spotipy.exceptions.SpotifyException. Common errors:

- 404 NO_ACTIVE_DEVICE: no Spotify Connect device is currently warm. Tell the user to open Spotify on their phone and tap the device picker, or check that raspotify is running on the Pi (sudo systemctl status raspotify).
- 403 PREMIUM_REQUIRED: the operation needs Premium and the account is not Premium. Should not happen for this user.
- 401: token expired or revoked. The auth_manager should auto-refresh, but if this persists, the user may need to re-run ~/.hermes/skills/spotify/auth.py.

Wrap risky calls in a try/except that surfaces the error message clearly to the user:

```python
try:
    sp.start_playback(device_id=device_id, uris=[track["uri"]])
    print(f"Now playing: {track['name']}")
except spotipy.exceptions.SpotifyException as e:
    print(f"Spotify error: {e.msg}")
```

## Notes for the agent

- Spotify search is fuzzy and forgiving. Do not overthink the query string. "queen bohemian rhapsody" works as well as a structured query.
- For non-English titles, just pass them as-is. Spotify search handles Cyrillic, kanji, etc. natively.
- When the user asks for a mood or vibe that isn't a clear artist/album, prefer searching for an existing playlist that matches, OR get top tracks of a representative artist.
- Always confirm to the user what you played by name and artist, not just "OK done". They want to know it picked the right thing.
- After starting playback, you do not need to do anything else. The music keeps playing in the background. Hermes can return to its prompt.
- Spotify search works in any language — just pass the user's query through unchanged.
- **Security:** never print or echo the user's Client ID or Client Secret in code output. Read them from .env at runtime; do not embed them as string literals in snippets you execute.
