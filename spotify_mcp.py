#!/usr/bin/env python3
"""
Spotify MCP server for Hermes Agent.

Thin MCP (stdio) wrapper around spotipy. All auth, caching, scope handling, and
device-wake logic lives here so the agent (especially smaller models) only sees
12 simple tools.

Run:
    ~/.hermes/hermes-agent/venv/bin/python /path/to/spotify_mcp.py

Register in ~/.hermes/config.yaml:
    mcp_servers:
      spotify:
        command: "/home/USER/.hermes/hermes-agent/venv/bin/python"
        args: ["/home/USER/.hermes/skills/spotify/spotify_mcp.py"]

Prerequisites: auth.py has been run once and ~/.hermes/.spotify_cache exists.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Config / constants
# ---------------------------------------------------------------------------

HERMES_DIR = Path.home() / ".hermes"
ENV_PATH = HERMES_DIR / ".env"
CACHE_PATH = HERMES_DIR / ".spotify_cache"
LEGACY_CREDS_PATH = HERMES_DIR / ".spotify_credentials"
LEGACY_DEVICE_PATH = HERMES_DIR / ".spotify_device"
REDIRECT_URI = "http://127.0.0.1:8888/callback"


# ---------------------------------------------------------------------------
# Env loader (same pattern as auth.py / old SKILL.md init block)
# ---------------------------------------------------------------------------

def _load_env() -> None:
    if not ENV_PATH.exists():
        return
    for line in ENV_PATH.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())


def _get_credentials() -> tuple[str, str]:
    cid = os.environ.get("SPOTIFY_CLIENT_ID", "").strip()
    csec = os.environ.get("SPOTIFY_CLIENT_SECRET", "").strip()
    if cid and csec:
        return cid, csec
    if LEGACY_CREDS_PATH.exists():
        lines = LEGACY_CREDS_PATH.read_text().strip().splitlines()
        if len(lines) >= 2:
            return lines[0].strip(), lines[1].strip()
    raise RuntimeError(
        "Spotify credentials not found. Expected SPOTIFY_CLIENT_ID and "
        "SPOTIFY_CLIENT_SECRET in ~/.hermes/.env (run auth.py once)."
    )


def _get_cached_scope() -> str:
    if not CACHE_PATH.exists():
        raise RuntimeError(
            "OAuth cache not found at ~/.hermes/.spotify_cache. "
            "Run auth.py interactively once to create it."
        )
    try:
        data = json.loads(CACHE_PATH.read_text())
        scope = data.get("scope")
        if not scope:
            raise RuntimeError("Cached token is missing 'scope' field.")
        return scope
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Corrupt OAuth cache: {e}") from e


def _get_default_device_name() -> Optional[str]:
    name = os.environ.get("SPOTIFY_DEFAULT_DEVICE", "").strip()
    if name:
        return name
    if LEGACY_DEVICE_PATH.exists():
        txt = LEGACY_DEVICE_PATH.read_text().strip()
        if txt:
            return txt
    return None


# ---------------------------------------------------------------------------
# Spotify client (lazily initialized, reused across tool calls)
# ---------------------------------------------------------------------------

_sp = None


def _client():
    """Return a cached spotipy.Spotify client, creating it on first use."""
    global _sp
    if _sp is not None:
        return _sp

    _load_env()
    import spotipy
    from spotipy.oauth2 import SpotifyOAuth

    client_id, client_secret = _get_credentials()
    scope = _get_cached_scope()

    auth = SpotifyOAuth(
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=REDIRECT_URI,
        scope=scope,
        cache_path=str(CACHE_PATH),
        open_browser=False,
    )
    _sp = spotipy.Spotify(auth_manager=auth)
    return _sp


# ---------------------------------------------------------------------------
# Device resolution + wake
# ---------------------------------------------------------------------------

def _resolve_device(hint: str = "") -> dict:
    """Find a device by (caller hint) > (default from env) > (active) > first.

    Returns the device dict. Raises RuntimeError if no devices exist.
    """
    sp = _client()
    devices = sp.devices().get("devices", [])
    if not devices:
        raise RuntimeError(
            "No Spotify Connect devices visible. Open Spotify on a phone/"
            "laptop and tap the device picker to wake discovery, or check "
            "that raspotify is running (sudo systemctl status raspotify)."
        )

    # 1. explicit hint from caller
    if hint:
        for d in devices:
            if hint.lower() in d["name"].lower():
                return d

    # 2. configured default
    default = _get_default_device_name()
    if default:
        for d in devices:
            if default.lower() in d["name"].lower():
                return d

    # 3. any active device
    for d in devices:
        if d.get("is_active"):
            return d

    # 4. first one
    return devices[0]


def _wake_if_dormant(device: dict, force_play: bool = False) -> None:
    """Transfer playback to wake a dormant device. No-op if already active."""
    if device.get("is_active") and not force_play:
        return
    sp = _client()
    try:
        sp.transfer_playback(device_id=device["id"], force_play=force_play)
    except Exception as e:  # noqa: BLE001
        # Wake failed but let the caller's operation decide if that's fatal.
        # start_playback will throw a clearer error if the device is truly gone.
        sys.stderr.write(f"[spotify-mcp] wake failed for {device['name']}: {e}\n")


# ---------------------------------------------------------------------------
# Tool implementations — each returns a plain dict
# ---------------------------------------------------------------------------

def tool_play(query: str, kind: str = "track", device: str = "") -> dict:
    """Search Spotify and start playback of the top result."""
    sp = _client()
    kind = (kind or "track").lower()
    if kind not in ("track", "album", "artist", "playlist"):
        return {"error": f"kind must be one of track|album|artist|playlist, got {kind!r}"}

    dev = _resolve_device(device)
    _wake_if_dormant(dev, force_play=True)
    device_id = dev["id"]

    if kind == "playlist":
        # Search user's own playlists first (substring match), then public search.
        playlists = sp.current_user_playlists(limit=50).get("items", [])
        match = next(
            (p for p in playlists if query.lower() in (p.get("name") or "").lower()),
            None,
        )
        if match:
            sp.start_playback(device_id=device_id, context_uri=match["uri"])
            return {
                "status": "playing",
                "kind": "playlist",
                "name": match["name"],
                "device": dev["name"],
            }
        # Fall through to public search
        results = sp.search(q=query, type="playlist", limit=1).get("playlists", {}).get("items", [])
        if not results:
            return {"error": f"No playlist found for {query!r}"}
        pl = results[0]
        sp.start_playback(device_id=device_id, context_uri=pl["uri"])
        return {"status": "playing", "kind": "playlist", "name": pl["name"], "device": dev["name"]}

    if kind == "track":
        items = sp.search(q=query, type="track", limit=1).get("tracks", {}).get("items", [])
        if not items:
            return {"error": f"No track found for {query!r}"}
        t = items[0]
        sp.start_playback(device_id=device_id, uris=[t["uri"]])
        return {
            "status": "playing",
            "kind": "track",
            "name": t["name"],
            "artist": t["artists"][0]["name"] if t.get("artists") else "",
            "device": dev["name"],
        }

    if kind == "album":
        items = sp.search(q=query, type="album", limit=1).get("albums", {}).get("items", [])
        if not items:
            return {"error": f"No album found for {query!r}"}
        a = items[0]
        sp.start_playback(device_id=device_id, context_uri=a["uri"])
        return {
            "status": "playing",
            "kind": "album",
            "name": a["name"],
            "artist": a["artists"][0]["name"] if a.get("artists") else "",
            "device": dev["name"],
        }

    # kind == "artist" → top tracks
    items = sp.search(q=query, type="artist", limit=1).get("artists", {}).get("items", [])
    if not items:
        return {"error": f"No artist found for {query!r}"}
    artist = items[0]
    try:
        top = sp.artist_top_tracks(artist["id"]).get("tracks", [])
    except Exception as e:  # noqa: BLE001
        # Fallback: search for a track by this artist
        return {"error": f"artist_top_tracks failed ({e}); try kind='track' with '{query}'"}
    if not top:
        return {"error": f"No top tracks for artist {artist['name']!r}"}
    sp.start_playback(device_id=device_id, uris=[t["uri"] for t in top])
    return {
        "status": "playing",
        "kind": "artist_top_tracks",
        "artist": artist["name"],
        "track_count": len(top),
        "device": dev["name"],
    }


def tool_pause() -> dict:
    sp = _client()
    try:
        dev = _resolve_device()
        sp.pause_playback(device_id=dev["id"])
        return {"status": "paused", "device": dev["name"]}
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)}


def tool_resume() -> dict:
    sp = _client()
    try:
        dev = _resolve_device()
        _wake_if_dormant(dev)
        sp.start_playback(device_id=dev["id"])
        return {"status": "resumed", "device": dev["name"]}
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)}


def tool_next_track() -> dict:
    sp = _client()
    try:
        dev = _resolve_device()
        sp.next_track(device_id=dev["id"])
        return {"status": "skipped", "device": dev["name"]}
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)}


def tool_previous_track() -> dict:
    sp = _client()
    try:
        dev = _resolve_device()
        sp.previous_track(device_id=dev["id"])
        return {"status": "previous", "device": dev["name"]}
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)}


def tool_volume(level: int) -> dict:
    try:
        level = int(level)
    except (TypeError, ValueError):
        return {"error": f"level must be an int 0-100, got {level!r}"}
    level = max(0, min(100, level))
    sp = _client()
    try:
        dev = _resolve_device()
        sp.volume(level, device_id=dev["id"])
        return {"status": "volume_set", "level": level, "device": dev["name"]}
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)}


def tool_volume_adjust(delta: int) -> dict:
    try:
        delta = int(delta)
    except (TypeError, ValueError):
        return {"error": f"delta must be an int, got {delta!r}"}
    sp = _client()
    try:
        cur = sp.current_playback()
        current_level = 50
        if cur and cur.get("device"):
            current_level = int(cur["device"].get("volume_percent") or 50)
        new_level = max(0, min(100, current_level + delta))
        dev = _resolve_device()
        sp.volume(new_level, device_id=dev["id"])
        return {
            "status": "volume_adjusted",
            "from": current_level,
            "to": new_level,
            "delta": delta,
            "device": dev["name"],
        }
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)}


def tool_shuffle(on: bool) -> dict:
    sp = _client()
    try:
        dev = _resolve_device()
        sp.shuffle(bool(on), device_id=dev["id"])
        return {"status": "shuffle_set", "on": bool(on), "device": dev["name"]}
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)}


def tool_repeat(mode: str) -> dict:
    mode = (mode or "").lower()
    if mode not in ("off", "track", "context"):
        return {"error": f"mode must be off|track|context, got {mode!r}"}
    sp = _client()
    try:
        dev = _resolve_device()
        sp.repeat(mode, device_id=dev["id"])
        return {"status": "repeat_set", "mode": mode, "device": dev["name"]}
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)}


def tool_queue(query: str) -> dict:
    sp = _client()
    try:
        items = sp.search(q=query, type="track", limit=1).get("tracks", {}).get("items", [])
        if not items:
            return {"error": f"No track found for {query!r}"}
        t = items[0]
        dev = _resolve_device()
        sp.add_to_queue(uri=t["uri"], device_id=dev["id"])
        return {
            "status": "queued",
            "name": t["name"],
            "artist": t["artists"][0]["name"] if t.get("artists") else "",
            "device": dev["name"],
        }
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)}


def tool_now_playing() -> dict:
    sp = _client()
    try:
        cur = sp.current_playback()
        if not cur or not cur.get("item"):
            return {"is_playing": False}
        item = cur["item"]
        return {
            "is_playing": bool(cur.get("is_playing")),
            "name": item.get("name"),
            "artist": item["artists"][0]["name"] if item.get("artists") else "",
            "album": (item.get("album") or {}).get("name", ""),
            "device": (cur.get("device") or {}).get("name", ""),
            "volume_percent": (cur.get("device") or {}).get("volume_percent"),
            "progress_ms": cur.get("progress_ms"),
            "duration_ms": item.get("duration_ms"),
        }
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)}


def tool_list_devices() -> dict:
    sp = _client()
    try:
        devices = sp.devices().get("devices", [])
        return {
            "devices": [
                {
                    "name": d.get("name"),
                    "type": d.get("type"),
                    "is_active": d.get("is_active"),
                    "volume_percent": d.get("volume_percent"),
                }
                for d in devices
            ],
            "default_configured": _get_default_device_name(),
        }
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)}


# ---------------------------------------------------------------------------
# MCP wiring
# ---------------------------------------------------------------------------

TOOLS: dict[str, dict[str, Any]] = {
    "play": {
        "description": (
            "Search Spotify and start playback on the default device. "
            "Set kind='track' for a song, 'album' for an album, 'artist' for "
            "an artist's top tracks, 'playlist' for a playlist. Device wake is "
            "handled automatically."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search text, e.g. 'bohemian rhapsody queen'"},
                "kind": {
                    "type": "string",
                    "enum": ["track", "album", "artist", "playlist"],
                    "default": "track",
                },
                "device": {
                    "type": "string",
                    "description": "Optional device name substring; omit to use default.",
                    "default": "",
                },
            },
            "required": ["query"],
        },
        "fn": tool_play,
    },
    "pause": {
        "description": "Pause playback on the current/default device.",
        "schema": {"type": "object", "properties": {}},
        "fn": tool_pause,
    },
    "resume": {
        "description": "Resume playback on the current/default device.",
        "schema": {"type": "object", "properties": {}},
        "fn": tool_resume,
    },
    "next_track": {
        "description": "Skip to the next track.",
        "schema": {"type": "object", "properties": {}},
        "fn": tool_next_track,
    },
    "previous_track": {
        "description": "Go back to the previous track.",
        "schema": {"type": "object", "properties": {}},
        "fn": tool_previous_track,
    },
    "volume": {
        "description": "Set absolute volume (0-100).",
        "schema": {
            "type": "object",
            "properties": {"level": {"type": "integer", "minimum": 0, "maximum": 100}},
            "required": ["level"],
        },
        "fn": tool_volume,
    },
    "volume_adjust": {
        "description": "Adjust volume by a relative delta. Use +10 for louder, -10 for quieter.",
        "schema": {
            "type": "object",
            "properties": {"delta": {"type": "integer"}},
            "required": ["delta"],
        },
        "fn": tool_volume_adjust,
    },
    "shuffle": {
        "description": "Turn shuffle on or off.",
        "schema": {
            "type": "object",
            "properties": {"on": {"type": "boolean"}},
            "required": ["on"],
        },
        "fn": tool_shuffle,
    },
    "repeat": {
        "description": "Set repeat mode: 'off', 'track' (repeat this song), or 'context' (repeat album/playlist).",
        "schema": {
            "type": "object",
            "properties": {
                "mode": {"type": "string", "enum": ["off", "track", "context"]},
            },
            "required": ["mode"],
        },
        "fn": tool_repeat,
    },
    "queue": {
        "description": "Search for a track and add it to the playback queue.",
        "schema": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
        "fn": tool_queue,
    },
    "now_playing": {
        "description": "Return the currently playing track and device, or is_playing=false if idle.",
        "schema": {"type": "object", "properties": {}},
        "fn": tool_now_playing,
    },
    "list_devices": {
        "description": "List all Spotify Connect devices visible on the account.",
        "schema": {"type": "object", "properties": {}},
        "fn": tool_list_devices,
    },
}


def _build_server():
    """Construct the MCP server. Imports mcp lazily so --list-tools works without it."""
    from mcp.server import Server
    from mcp.types import Tool, TextContent

    server = Server("spotify")

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(name=name, description=spec["description"], inputSchema=spec["schema"])
            for name, spec in TOOLS.items()
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[TextContent]:
        spec = TOOLS.get(name)
        if spec is None:
            payload = {"error": f"Unknown tool: {name}"}
        else:
            try:
                payload = spec["fn"](**(arguments or {}))
            except TypeError as e:
                payload = {"error": f"bad arguments for {name}: {e}"}
            except Exception as e:  # noqa: BLE001
                payload = {"error": f"{type(e).__name__}: {e}"}
        return [TextContent(type="text", text=json.dumps(payload, ensure_ascii=False))]

    return server


async def _run_stdio() -> None:
    from mcp.server.stdio import stdio_server

    server = _build_server()
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


def _print_tools_and_exit() -> None:
    """Debug helper: `python spotify_mcp.py --list-tools` prints the tool surface."""
    for name, spec in TOOLS.items():
        req = spec["schema"].get("required", [])
        props = spec["schema"].get("properties", {})
        params = ", ".join(
            f"{p}{'*' if p in req else ''}"
            for p in props
        )
        print(f"{name}({params})")
        print(f"  {spec['description']}")
    sys.exit(0)


def main() -> None:
    if "--list-tools" in sys.argv:
        _print_tools_and_exit()
    import asyncio

    asyncio.run(_run_stdio())


if __name__ == "__main__":
    main()
