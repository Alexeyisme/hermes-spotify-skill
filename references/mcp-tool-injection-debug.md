# Debugging: Spotify MCP tools not appearing in agent schema

Use this when the skill's trigger→tool map says you should call e.g.
`mcp_spotify_list_devices`, but that function is not in your tool schema, and
`execute_code`/`terminal` fallbacks feel like the only option. **They aren't.**
The cause is almost always a config-layer mismatch, not a runtime failure.

## Symptom

- User asks a music / playback question.
- You scan your available tools — no `mcp_spotify_*` functions.
- Tempted to fall back to `execute_code` with `spotipy`, or to pipe raw
  JSON-RPC into `spotify_mcp.py` via `terminal`.
- Both fallbacks are brittle (sandbox cache isolation, OAuth EOF prompts,
  missing MCP `initialize` handshake, approval gates on stdin pipes).

## Root cause

Two independent config layers must agree, AND the toolset name uses a
HYPHEN that most people get wrong on first try:

1. **Server registration** — `mcp_servers.spotify` in `~/.hermes/config.yaml`
   (the server process and its transport).
2. **Platform toolset enablement** — `platform_toolsets.<platform>` must
   include **`mcp-spotify`** (the auto-generated toolset name with a HYPHEN,
   *not* the bare server name `spotify`). This is the gate that decides
   which toolsets are injected into the agent's function schema per platform
   (`cli`, `telegram`, `discord`, `slack`, `signal`, `homeassistant`, ...).

### Three different name spaces — don't confuse them

| What | Name pattern | Example |
|---|---|---|
| MCP server config key | `<server>` | `spotify` |
| MCP-generated toolset | `mcp-<server>` (hyphen) | `mcp-spotify` |
| MCP tool schema names | `mcp_<server>_<tool>` (underscores) | `mcp_spotify_list_devices` |
| Unrelated bundled plugin (*trap*) | `<server>` | `spotify` (from `plugins/spotify/`) |

If only layer 1 is configured, `hermes mcp test spotify` and
`hermes mcp list` both look perfectly healthy, but the agent never receives
the tools. `known_plugin_toolsets` listing `spotify` is *not* enablement —
that just means Hermes recognizes the bundled plugin of the same name.

## The two traps that will bite you

### Trap A — `hermes tools enable spotify`

Looks like the obvious fix. Accepts and reports success. **It's wrong.**
It enables the bundled `plugins/spotify/` plugin (tools named
`spotify_playback`, `spotify_devices`, etc.) — a completely different
integration, not this MCP skill. Your `mcp_spotify_*` tools still won't
appear.

### Trap B — `hermes tools enable mcp-spotify`

Rejected with `✗ Unknown toolset 'mcp-spotify'`. The `hermes tools enable`
CLI only knows about hard-coded built-in toolsets; it doesn't see
MCP-generated toolsets in the runtime registry.

## The correct fix — edit config.yaml directly

Open `~/.hermes/config.yaml` and add `mcp-spotify` to each platform's list
under `platform_toolsets`, alphabetical order:

```yaml
platform_toolsets:
  cli:
    - browser
    - clarify
    - code_execution
    - ...
    - mcp-spotify        # ← add this
    - memory
    - ...
  telegram:              # and every other platform where you want spotify
    - ...
    - mcp-spotify
    - ...
  discord:
    - ...
    - mcp-spotify
    - ...
```

Then restart the gateway (`/restart` in messaging platforms) or exit and
relaunch the CLI. **Enabling mid-session does NOT retrofit the currently
running conversation** — the tool schema is baked at session start.

## Diagnostic sequence

Run these in order. Stop at the first failure — that's your actual bug.

```bash
# 1. Server process and stdio transport healthy?
hermes mcp list                 # expect: spotify  ✓ enabled
hermes mcp test spotify         # expect: ✓ Connected, ✓ Tools discovered: 16

# 2. Does the registry actually have an 'mcp-spotify' toolset?
cd ~/.hermes/hermes-agent && venv/bin/python -c "
from tools.mcp_tool import discover_mcp_tools
discover_mcp_tools()
from tools.registry import registry
print('Toolsets:', sorted(registry.get_registered_toolset_names()))
print('Spotify tools:', len([t for t in registry.get_all_tool_names() if 'spotify' in t.lower()]))
"
# Expect: 'mcp-spotify' in the toolset list, 16 spotify tools registered.

# 3. Is 'mcp-spotify' (with hyphen) enabled for the platform you're on?
grep -A 60 '^platform_toolsets:' ~/.hermes/config.yaml | grep -B1 -A1 'mcp-spotify'
# If 'mcp-spotify' is missing under your platform's list, THIS is the bug.
# WARNING: if you see bare 'spotify' (no 'mcp-' prefix), that's Trap A — the
#          built-in plugin, not the MCP skill. Replace it with 'mcp-spotify'.

# 4. Fix: edit ~/.hermes/config.yaml directly — do NOT use `hermes tools enable`.
#    Add 'mcp-spotify' to platform_toolsets.<platform> for every platform you need.

# 5. Restart the gateway (/restart) or exit + relaunch CLI.

# 6. Verify in a fresh session: ask "list tools containing spotify"
#    Expect: all 16 mcp_spotify_* names.
```

## Why the common fallbacks fail

Documenting these so a future agent recognizes the failure modes quickly and
doesn't spend multiple turns reinventing them.

### Fallback A — `execute_code` with spotipy directly

```python
import spotipy
from spotipy.oauth2 import SpotifyOAuth
sp = spotipy.Spotify(auth_manager=SpotifyOAuth(
    client_id=..., client_secret=...,
    cache_path=os.path.expanduser("~/.hermes/.spotify_cache"),
    scope="user-read-playback-state,...",
    open_browser=False,
))
sp.devices()
```

Fails in the sandbox with:

```
EOFError: EOF when reading a line
  File ".../spotipy/oauth2.py", line 90, in _get_user_input
    return input(prompt)
```

The `execute_code` sandbox may be isolated from `~/.hermes/.spotify_cache`,
so spotipy decides the token is unknown and drops into an interactive OAuth
prompt — which has no stdin. Even when it *does* see the cache, this path
bypasses the skill's canonical device-wake / error-mapping logic and will
silently diverge from the tools' behavior.

### Fallback B — `terminal` piping a bare string into the MCP server

```bash
echo "list_devices" | python spotify_mcp.py     # WRONG
```

MCP servers speak JSON-RPC, not bare method names. Produces an empty
response or validation error and zero useful output.

### Fallback C — `terminal` piping a single JSON-RPC request

```bash
cat <<EOF | python spotify_mcp.py
{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"list_devices","arguments":{}}}
EOF
```

Two problems:

1. MCP requires a handshake *before* any `tools/call`: `initialize`
   (request/response) → `notifications/initialized` (one-way) → then
   `tools/call`. A single-message stdin stream gets no response.
2. The here-doc pipe pattern frequently trips approval gates (exit code -1,
   "user denied") when security policy disallows feeding unvetted data into
   an external interpreter.

### What a working JSON-RPC probe looks like (debug-only)

Only useful when you're debugging the *server itself* and the proper
toolset-injection fix is not yet available. Never use this as a normal tool
invocation path.

```python
import subprocess, json

msgs = [
    {"jsonrpc":"2.0","id":1,"method":"initialize","params":{
        "protocolVersion":"2024-11-05","capabilities":{},
        "clientInfo":{"name":"debug","version":"1.0"}}},
    {"jsonrpc":"2.0","method":"notifications/initialized","params":{}},
    {"jsonrpc":"2.0","id":2,"method":"tools/call","params":{
        "name":"list_devices","arguments":{}}},
]
stdin = "\n".join(json.dumps(m) for m in msgs) + "\n"
p = subprocess.run(
    ["/home/USER/.hermes/hermes-agent/venv/bin/python",
     "/home/USER/.hermes/skills/spotify/spotify_mcp.py"],
    input=stdin, capture_output=True, text=True, timeout=20,
)
for line in p.stdout.splitlines():
    try:    print(json.dumps(json.loads(line), indent=2))
    except: print(line)
```

## Decision rule

If `mcp_spotify_*` tools are missing:

1. Don't reach for `execute_code` or `terminal` first.
2. Check `platform_toolsets.<current_platform>` in `~/.hermes/config.yaml`
   for the literal string **`mcp-spotify`** (with hyphen).
3. If missing (or you see bare `spotify` which is the wrong plugin), edit
   the YAML directly. Do NOT use `hermes tools enable`.
4. Restart the gateway / CLI and verify in a fresh session. Tell the user
   the fix requires a new session and offer to continue via the subprocess
   JSON-RPC probe *only* if they need an answer right now and accept the
   debug-path caveat.

## Field notes (May 2026)

Verified end-to-end on this stack:
- Fresh `hermes chat -Q --query "list tools with 'spotify'"` returned `NONE`
  until `mcp-spotify` was added to `platform_toolsets.cli`.
- After the edit + gateway `/restart`, the same query returned all 16
  `mcp_spotify_*` tools and subsequent tool calls succeeded in ~0.6s with
  no subprocess fallback.
- Both qwen (via custom provider) and Claude Opus (via OpenRouter) saw the
  tools identically — the issue is model-agnostic, config-driven.
- `hermes tools enable spotify --platform cli` reported `✓ Enabled: spotify`
  but enabled the bundled `plugins/spotify/` plugin instead. The interactive
  UI's `hermes tools --summary` showed `✓ 🎵 Spotify` — same emoji and label
  as the built-in plugin, reinforcing the confusion.
