#!/usr/bin/env python3
"""
One-time Spotify OAuth setup for Hermes.

Run this manually once. It will:
  1. Check for an existing valid token (and offer to skip if found)
  2. Prompt you for Client ID and Client Secret
  3. Print an authorization URL
  4. Wait for you to paste the redirect URL (with retries on bad input)
  5. Cache the access + refresh tokens to ~/.hermes/.spotify_cache
  6. Save client credentials to ~/.hermes/.env
  7. Test the token by listing your devices

After this, spotipy will auto-refresh tokens forever and Hermes can
use the cached credentials without ever doing the OAuth flow again.
"""

import os
import sys
from pathlib import Path

HERMES_DIR = Path.home() / ".hermes"
CACHE_PATH = str(HERMES_DIR / ".spotify_cache")
ENV_PATH = HERMES_DIR / ".env"
LEGACY_CREDS_PATH = HERMES_DIR / ".spotify_credentials"
REDIRECT_URI = "http://127.0.0.1:8888/callback"
SCOPE = " ".join([
    "user-read-playback-state",
    "user-modify-playback-state",
    "user-read-currently-playing",
    "playlist-read-private",
    "playlist-read-collaborative",
    "user-library-read",
    "user-top-read",
    "user-read-recently-played",
    "streaming",
])

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _find_hermes_python():
    """Return the path to the Hermes venv Python, or None if not found."""
    candidates = [
        HERMES_DIR / "hermes-agent" / "venv" / "bin" / "python",
        HERMES_DIR / "hermes-agent" / "venv" / "bin" / "python3",
        HERMES_DIR / "venv" / "bin" / "python",
    ]
    for p in candidates:
        if p.exists():
            return p
    return None


def _check_spotipy():
    """Import spotipy or exit with a helpful install message."""
    try:
        import spotipy  # noqa: F811
        from spotipy.oauth2 import SpotifyOAuth  # noqa: F811
        return spotipy, SpotifyOAuth
    except ImportError:
        hermes_py = _find_hermes_python()
        print("ERROR: spotipy is not installed in this Python environment.")
        print()
        if hermes_py:
            print("Install it with:")
            print(f"  {hermes_py} -m pip install spotipy")
            print()
            print("Then re-run this script with:")
            print(f"  {hermes_py} {__file__}")
        else:
            print("Could not find the Hermes venv. Install spotipy with:")
            print("  pip install spotipy")
            print()
            print("If Hermes is installed, try:")
            print("  ~/.hermes/hermes-agent/venv/bin/python -m pip install spotipy")
        sys.exit(1)


spotipy, SpotifyOAuth = _check_spotipy()


def _update_env_file(env_path, variables):
    """Add or update KEY=VALUE pairs in a .env file without disturbing other lines."""
    existing_lines = []
    if env_path.exists():
        existing_lines = env_path.read_text().splitlines()

    updated_keys = set()
    new_lines = []
    for line in existing_lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            if key in variables:
                new_lines.append(f"{key}={variables[key]}")
                updated_keys.add(key)
                continue
        new_lines.append(line)

    for key, value in variables.items():
        if key not in updated_keys:
            new_lines.append(f"{key}={value}")

    env_path.write_text("\n".join(new_lines) + "\n")
    env_path.chmod(0o600)


def _load_existing_credentials():
    """Try to load client_id and client_secret from .env or legacy file."""
    # Try .env first
    if ENV_PATH.exists():
        env_vars = {}
        for line in ENV_PATH.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                env_vars[k.strip()] = v.strip()
        cid = env_vars.get("SPOTIFY_CLIENT_ID", "")
        csec = env_vars.get("SPOTIFY_CLIENT_SECRET", "")
        if cid and csec:
            return cid, csec

    # Fall back to legacy credentials file
    if LEGACY_CREDS_PATH.exists():
        lines = LEGACY_CREDS_PATH.read_text().strip().split("\n")
        if len(lines) >= 2 and lines[0].strip() and lines[1].strip():
            return lines[0].strip(), lines[1].strip()

    return None, None


def _print_devices(sp):
    """Print the user's Spotify Connect devices."""
    devices = sp.devices().get("devices", [])
    if not devices:
        print("No active devices found. That's OK — it means no Spotify")
        print("client is currently 'awake' on your account. To wake one,")
        print("open the Spotify app on your phone and tap the device picker")
        print("(you don't have to switch — just opening the picker triggers")
        print("Spotify Connect discovery).")
    else:
        print(f"Found {len(devices)} device(s):")
        for d in devices:
            active = " (ACTIVE)" if d.get("is_active") else ""
            print(f"  - {d['name']:20s} type={d['type']:10s} id={d['id']}{active}")


def _check_existing_token():
    """If a valid cached token exists, show status and ask whether to re-auth."""
    cache_file = Path(CACHE_PATH)
    if not cache_file.exists():
        return False  # no existing token, proceed with auth

    client_id, client_secret = _load_existing_credentials()
    if not client_id or not client_secret:
        return False  # can't validate without credentials

    try:
        auth = SpotifyOAuth(
            client_id=client_id,
            client_secret=client_secret,
            redirect_uri=REDIRECT_URI,
            scope=SCOPE,
            cache_path=CACHE_PATH,
            open_browser=False,
        )
        token_info = auth.get_cached_token()
        if not token_info or "access_token" not in token_info:
            return False

        sp = spotipy.Spotify(auth_manager=auth)
        me = sp.current_user()
        print("=" * 60)
        print("Existing Spotify token found and valid!")
        print("=" * 60)
        print()
        print(f"Logged in as: {me.get('display_name')} ({me.get('id')})")
        print()
        _print_devices(sp)
        print()

        answer = input("Do you want to re-authenticate? [y/N] ").strip().lower()
        if answer not in ("y", "yes"):
            print()
            print("Keeping existing token. No changes made.")
            return True  # skip auth
        print()
        return False  # user wants to re-auth
    except Exception:
        return False  # token is broken, proceed with fresh auth


def _prompt_redirect_url(auth):
    """Prompt for the redirect URL with up to 3 retries on bad input."""
    max_attempts = 3
    for attempt in range(1, max_attempts + 1):
        redirect_response = input("Paste the redirect URL here: ").strip()

        if not redirect_response:
            print()
            print("ERROR: empty input.")
            if attempt < max_attempts:
                print("The URL should look like:")
                print(f"  {REDIRECT_URI}?code=AQD...long_string...")
                print(f"Try again ({max_attempts - attempt} attempt(s) left).")
                print()
                continue
            print("Out of retries.")
            sys.exit(1)

        code = auth.parse_response_code(redirect_response)
        if code and code != redirect_response:
            return code

        print()
        print("ERROR: could not extract the authorization code from that URL.")
        print("Make sure you copied the ENTIRE URL from the browser address bar.")
        print("It should look like:")
        print(f"  {REDIRECT_URI}?code=AQD...long_string...")
        if attempt < max_attempts:
            print(f"Try again ({max_attempts - attempt} attempt(s) left).")
            print()
        else:
            print("Out of retries.")
            sys.exit(1)


def _exchange_token(auth, code):
    """Exchange the authorization code for tokens, with clear error messages."""
    print()
    print("Exchanging code for tokens...")
    try:
        token_info = auth.get_access_token(code, check_cache=False)
    except spotipy.exceptions.SpotifyOauthError as e:
        msg = str(e).lower()
        print()
        if "invalid_client" in msg:
            print("ERROR: Spotify rejected the Client ID or Client Secret.")
            print("Double-check that you copied them correctly from")
            print("https://developer.spotify.com/dashboard (app Settings).")
        elif "invalid_redirect_uri" in msg or "redirect_uri_mismatch" in msg:
            print("ERROR: Redirect URI mismatch.")
            print(f"Make sure your Spotify app's redirect URI is exactly:")
            print(f"  {REDIRECT_URI}")
            print("(no trailing slash, no https, no 'localhost').")
        elif "authorization_code_expired" in msg or "expired" in msg:
            print("ERROR: The authorization code has expired.")
            print("Codes are only valid for a few minutes. Re-run this script")
            print("and complete the flow promptly.")
        else:
            print(f"ERROR: OAuth token exchange failed: {e}")
        sys.exit(1)
    except Exception as e:
        error_msg = str(e).lower()
        if "connection" in error_msg or "network" in error_msg or "dns" in error_msg:
            print()
            print("ERROR: Network error during token exchange.")
            print("Check your internet connection and try again.")
        else:
            print()
            print(f"ERROR: Unexpected error during token exchange: {e}")
        sys.exit(1)

    if not token_info or "access_token" not in token_info:
        print("ERROR: token exchange returned an empty response.")
        sys.exit(1)

    return token_info


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    if _check_existing_token():
        return

    print("=" * 60)
    print("Spotify OAuth setup for Hermes")
    print("=" * 60)
    print()
    print("You will need your Client ID and Client Secret from")
    print("https://developer.spotify.com/dashboard")
    print()

    # Pre-fill from existing credentials if available
    existing_id, existing_secret = _load_existing_credentials()

    if existing_id:
        client_id = input(f"Client ID [{existing_id[:8]}...]: ").strip() or existing_id
    else:
        client_id = input("Client ID: ").strip()

    if existing_secret:
        client_secret = input(f"Client Secret [{existing_secret[:4]}...]: ").strip() or existing_secret
    else:
        client_secret = input("Client Secret: ").strip()

    if not client_id or not client_secret:
        print("ERROR: both Client ID and Client Secret are required.")
        sys.exit(1)

    auth = SpotifyOAuth(
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=REDIRECT_URI,
        scope=SCOPE,
        cache_path=CACHE_PATH,
        open_browser=False,
    )

    print()
    print("=" * 60)
    print("STEP 1: Open this URL in a browser on your laptop:")
    print("=" * 60)
    print()
    print(auth.get_authorize_url())
    print()
    print("=" * 60)
    print("STEP 2: Log in to Spotify, click 'Agree'")
    print("STEP 3: Your browser will redirect to a 127.0.0.1 URL")
    print("        that fails to load. THAT IS EXPECTED.")
    print("STEP 4: Copy the ENTIRE URL from the address bar and")
    print("        paste it below.")
    print("=" * 60)
    print()

    code = _prompt_redirect_url(auth)
    token_info = _exchange_token(auth, code)

    print(f"Token cached to: {CACHE_PATH}")

    # Save client credentials to ~/.hermes/.env for the skill to read at runtime
    _update_env_file(ENV_PATH, {
        "SPOTIFY_CLIENT_ID": client_id,
        "SPOTIFY_CLIENT_SECRET": client_secret,
    })
    print(f"Client credentials saved to: {ENV_PATH}")

    print()
    print("Testing token: listing your Spotify devices...")
    sp = spotipy.Spotify(auth=token_info["access_token"])
    me = sp.current_user()
    print(f"Logged in as: {me.get('display_name')} ({me.get('id')})")
    print()

    _print_devices(sp)

    print()
    print("=" * 60)
    print("DONE. Hermes can now control Spotify.")
    print("=" * 60)


if __name__ == "__main__":
    main()
