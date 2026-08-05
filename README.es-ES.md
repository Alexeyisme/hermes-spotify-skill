

# hermes-spotify-skill

Control de reproducción de Spotify para [Hermes Agent](https://github.com/NousResearch/hermes-agent) en Linux / Raspberry Pi.

Desde la **v1.0.0** esta habilidad se distribuye como un servidor MCP ligero (`spotify_mcp.py`) junto con un `SKILL.md` de ~1.5 KB. El servidor MCP expone 12 herramientas — `play`, `pause`, `resume`, `next_track`, `previous_track`, `volume`, `volume_adjust`, `shuffle`, `repeat`, `queue`, `now_playing`, `list_devices` — y oculta todos los componentes frágiles (caché de OAuth, gestión de ámbitos, activación de dispositivos, mapeo de errores) dentro de Python. El agente solo elige una herramienta y rellena 0–2 argumentos, lo cual es exactamente en lo que son buenos los modelos pequeños/locales.

> **Nota sobre la cantidad de herramientas:** `spotify_mcp.py --list-tools` informa **12** (las herramientas reales de Spotify). Cuando Hermes las registre vía MCP, verás **16** nombres `mcp_spotify_*` en el registro — las 4 adicionales (`list_prompts`, `get_prompt`, `list_resources`, `read_resource`) son asistentes genéricos del protocolo MCP autoexpuestos por el SDK `mcp[cli]`, no características de esta habilidad. Ignóralas.

Verificado que funciona con **qwen3.6:35b-a3b-nvfp4 (local)** y **Claude Opus 4.7 (OpenRouter)** — las herramientas son agnósticas al modelo.

**Cómo funciona:** `spotify_mcp.py` es un servidor MCP de stdio que envuelve [spotipy](https://github.com/spotipy-dev/spotipy). El cliente MCP integrado de Hermes (ver la [habilidad `native-mcp`](https://github.com/NousResearch/hermes-agent)) lo inicia al arrancar, descubre las herramientas y las registra como `mcp_spotify_*`. Sin demonios, sin HTTP, sin servicio separado.

Las dos habilidades existentes para Spotify en el centro de la comunidad de Hermes son exclusivas para macOS. Esta funciona en cualquier máquina Linux sin interfaz gráfica, probada en Raspberry Pi OS Lite Bookworm de 64 bits.

---

## Instrucciones de configuración

> **Para el agente:** sigue estos pasos en orden. Haz todo lo que puedas de forma autónoma. Cuando un paso diga **ASK THE USER**, detente y guíalos a través de él — necesitarán interactuar con un navegador o un sitio web de terceros.

### Paso 1: Instalar dependencias de Python

Ejecuta esto en una sesión de **terminal**:

```bash
~/.hermes/hermes-agent/venv/bin/python -m pip install spotipy "mcp[cli]"
```

- `spotipy` — Cliente de la API Web de Spotify utilizado por el servidor MCP
- `mcp[cli]` — SDK de Python para el Protocolo de Contexto de Modelo (MCP)

Si el entorno virtual de Hermes está en una ruta diferente, busca `~/.hermes/hermes-agent/venv/bin/python` o `~/.hermes/venv/bin/python`.

### Paso 2: Instalar la habilidad

```bash
# Clona el repositorio en una ubicación temporal
git clone https://github.com/Alexeyisme/hermes-spotify-skill.git /tmp/hermes-spotify-skill

# Copia los archivos de la habilidad a Hermes
mkdir -p ~/.hermes/skills/spotify
cp /tmp/hermes-spotify-skill/SKILL.md       ~/.hermes/skills/spotify/
cp /tmp/hermes-spotify-skill/spotify_mcp.py ~/.hermes/skills/spotify/
cp /tmp/hermes-spotify-skill/auth.py        ~/.hermes/skills/spotify/

# Limpia
rm -rf /tmp/hermes-spotify-skill
```

Verifica que los archivos de la habilidad existan:

```bash
ls -l ~/.hermes/skills/spotify/
```

Deberías ver `SKILL.md`, `spotify_mcp.py` y `auth.py`.

### Paso 3: Crear una aplicación de desarrollador en Spotify

**ASK THE USER** que realice lo siguiente. Guíalos paso a paso y espera a que proporcionen el Client ID y Client Secret antes de continuar.

Indica al usuario:

1. Ve a [developer.spotify.com/dashboard](https://developer.spotify.com/dashboard) e inicia sesión con tu cuenta de Spotify
2. Haz clic en **Create app**
3. Completa:
   - **App name**: cualquier nombre (ej. "Hermes Spotify")
   - **App description**: cualquier descripción (ej. "Control por voz vía Hermes")
   - **Redirect URI**: ingresa **exactamente** `http://127.0.0.1:8888/callback` y haz clic en **Add**
   - Marca **Web API** bajo "¿Qué API/SDKs planeas usar?"
4. Haz clic en **Save**
5. En la página de la app, haz clic en **Settings**
6. Copia el **Client ID** y el **Client Secret** y pégamelos aquí

> **Detalles importantes que debes informar al usuario:**
> - Spotify rechaza `localhost` — debe usar `127.0.0.1`
> - El puerto (`8888`) y la ruta (`/callback`) deben coincidir exactamente
> - Se requiere una cuenta Spotify Premium para controlar la reproducción

### Paso 4: Guardar credenciales

Una vez que el usuario proporcione el Client ID y Client Secret, guárdalos en `~/.hermes/.env`.

> **Nota de seguridad para agentes:** recibe las credenciales del usuario y escríbelas directamente en `.env` usando el código de abajo. No repitas, imprimas ni registres los valores crudos de las credenciales en tu salida — solo deben aparecer en el archivo `.env`.

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

### Paso 5: Ejecutar el flujo de OAuth

**ASK THE USER** que complete la autorización basada en navegador. Guíalos a través del proceso.

Ejecuta el script de autenticación en una sesión de **terminal** (no `execute_code` — el script requiere entrada interactiva por teclado):

```bash
~/.hermes/hermes-agent/venv/bin/python ~/.hermes/skills/spotify/auth.py
```

El script hará lo siguiente:
1. Detectará las credenciales guardadas (o las solicitará si faltan)
2. Imprimirá una URL de autorización larga

Indica al usuario:

1. **Copia la URL** y ábrela en un navegador desde cualquier dispositivo (teléfono, portátil, etc.)
2. **Inicia sesión en Spotify** y haz clic en **Agree**
3. El navegador redirigirá a una URL `http://127.0.0.1:8888/callback?code=...` que **fallará al cargar** — esto es esperado y correcto
4. **Copia la URL completa** de la barra de direcciones del navegador y pégala de nuevo en la terminal

Después de que el usuario pegue la URL, el script intercambia el código por tokens, los almacena en caché y lista los dispositivos de Spotify disponibles.

Si el script informa éxito, la habilidad está lista para usar.

### Paso 6: Configurar dispositivo de reproducción predeterminado (opcional)

Si el usuario tiene un dispositivo Spotify Connect preferido (ej. un Raspberry Pi ejecutando raspotify), establécelo como predeterminado:

```bash
echo "SPOTIFY_DEFAULT_DEVICE=device-name-here" >> ~/.hermes/.env
```

El nombre se coincide sin distinción entre mayúsculas y minúsculas como una subcadena. Si no se configura, se usará el primer dispositivo disponible.

### Paso 7: Registrar el servidor MCP con Hermes

Edita `~/.hermes/config.yaml` y agrega el servidor de Spotify bajo `mcp_servers`. Sustituye `USER` con el usuario real (ej. `bb` o `homunculus`):

```yaml
mcp_servers:
  spotify:
    command: "/home/USER/.hermes/hermes-agent/venv/bin/python"
    args: ["/home/USER/.hermes/skills/spotify/spotify_mcp.py"]
    timeout: 30
```

### Paso 7.5: Habilitar el conjunto de herramientas MCP por plataforma ⚠️ **obligatorio, fácil de pasar por alto**

Registrar el servidor es solo la mitad del proceso. El conjunto de herramientas generado automáticamente — llamado **`mcp-spotify`** (con un GUION, no `spotify`) — también debe estar listado bajo cada plataforma en la que quieras usar las herramientas:

```yaml
platform_toolsets:
  cli:
    - browser
    - ...existing entries...
    - mcp-spotify         # ← agrega esto
    - ...
  telegram:               # y cualquier otra plataforma que uses (discord, slack, signal, homeassistant, ...)
    - ...
    - mcp-spotify
    - ...
```

> ⚠️ **NO ejecutes `hermes tools enable spotify`.** Informa éxito pero habilita un plugin empaquetado no relacionado (`plugins/spotify/`) — herramientas completamente diferentes, no esta habilidad MCP. La CLI `hermes tools enable` también rechaza `mcp-spotify` como "Unknown toolset". **Debes editar `config.yaml` manualmente.**

Luego, **reinicia Hermes** (`/restart` en una plataforma de mensajería, o sal y relanza la CLI). Al arrancar deberías ver las 12 herramientas descubiertas y registradas como `mcp_spotify_play`, `mcp_spotify_pause`, etc. (El registro puede mostrar 16 — ver la nota sobre la cantidad de herramientas al inicio de este README.)

Comprobaciones rápidas desde la línea de comandos:

```bash
# Estado del servidor — debería mostrar "✓ Tools discovered: 12"
hermes mcp test spotify

# Confirma que el conjunto de herramientas mcp-spotify está habilitado para tu plataforma
grep -A 60 '^platform_toolsets:' ~/.hermes/config.yaml | grep mcp-spotify

# Firmas de herramientas (sin necesidad de Hermes)
~/.hermes/hermes-agent/venv/bin/python ~/.hermes/skills/spotify/spotify_mcp.py --list-tools
```

Si las herramientas aún no aparecen en el esquema del agente tras reiniciar, consulta [`references/mcp-tool-injection-debug.md`](references/mcp-tool-injection-debug.md) para la secuencia de diagnóstico completa.

### Paso 8: Verificar

Indica al usuario que la habilidad está instalada y lista. Ofrécete a probarla reproduciendo una canción. Usa los patrones de SKILL.md para buscar una pista e iniciar la reproducción.

Si no se encuentran dispositivos activos, indica al usuario que abra la app de Spotify en su teléfono brevemente (solo toca el ícono del selector de dispositivos) para activar el descubrimiento de Spotify Connect.

---

## Opcional: Configurar raspotify

[raspotify](https://github.com/dtcooper/raspotify) convierte un Raspberry Pi en un altavoz compatible con Spotify Connect. Si el usuario lo desea, guíalos a través del proceso:

```bash
curl -sL https://dtcooper.github.io/raspotify/install.sh | sh
```

Luego edita `/etc/raspotify/conf`:

```ini
LIBRESPOT_NAME="YourPiName"
LIBRESPOT_DEVICE_TYPE="speaker"
LIBRESPOT_BITRATE="320"
LIBRESPOT_INITIAL_VOLUME="40"
```

Reinicia:

```bash
sudo systemctl restart raspotify
```

Después de esto, establece el dispositivo predeterminado para que coincida:

```bash
echo "SPOTIFY_DEFAULT_DEVICE=YourPiName" >> ~/.hermes/.env
```

---

## Solución de problemas

| Problema | Causa | Solución |
|---------|-------|-----|
| `INVALID_CLIENT: Invalid redirect URI` | El URI de redireccionamiento en la app de desarrollador de Spotify no coincide | Debe ser exactamente `http://127.0.0.1:8888/callback` — sin barra final, sin https, sin localhost |
| `No active device found` / `No Spotify Connect devices visible` | No hay ningún dispositivo Spotify Connect activo | Abre Spotify en el teléfono y toca el selector de dispositivos, o verifica `sudo systemctl status raspotify` |
| `401 Unauthorized` | Token expirado o revocado | Vuelve a ejecutar `auth.py` |
| Las herramientas `mcp_spotify_*` no aparecen en el esquema del agente | Más común: `mcp-spotify` (con guion) falta en `platform_toolsets.<platform>` dentro de `~/.hermes/config.yaml`. También posible: paquete `mcp[cli]` faltante en el venv, o `mcp_servers.spotify` no registrado. | 1) Verifica servidor: `hermes mcp test spotify` → "✓ Tools discovered: 12". 2) Verifica habilitación: `grep mcp-spotify ~/.hermes/config.yaml` bajo la lista de tu plataforma. 3) Si falta, edita config.yaml manualmente (NO `hermes tools enable`). 4) Reinicia gateway / sesión limpia. Diagnóstico completo: [`references/mcp-tool-injection-debug.md`](references/mcp-tool-injection-debug.md) |
| `Spotify credentials not found` en la primera llamada de herramienta | `auth.py` nunca ejecutado, o `.env` falta `SPOTIFY_CLIENT_ID` / `SPOTIFY_CLIENT_SECRET` | Ejecuta el Paso 4 + Paso 5 de la configuración |
| Hermes no reconoce la habilidad | Archivos de la habilidad no en la ubicación correcta | Verifica que `~/.hermes/skills/spotify/{SKILL.md,spotify_mcp.py,auth.py}` existan; reinicia Hermes |

---

## Qué puede hacer la habilidad

Una vez instalada y registrada como servidor MCP, el usuario puede pedirle a Hermes cosas como:

- "Reproduce Bohemian Rhapsody" → `mcp_spotify_play(query="Bohemian Rhapsody")`
- "Reproduce el álbum Dark Side of the Moon" → `mcp_spotify_play(query="Dark Side of the Moon", kind="album")`
- "Pon algo de Queen" → `mcp_spotify_play(query="Queen", kind="artist")`
- "Reproduce mi playlist chill" → `mcp_spotify_play(query="chill", kind="playlist")`
- "Pausar" / "Reanudar" / "Siguiente" / "Anterior"
- "Más alto" / "Más bajo" / "Establecer volumen en 30"
- "¿Qué se está reproduciendo actualmente?" → `mcp_spotify_now_playing()`
- "¿Qué dispositivos hay disponibles?" → `mcp_spotify_list_devices()`
- "Activar aleatorio" / "Repetir esta canción"
- "Poner esta canción en cola a continuación"

Consulta `SKILL.md` para ver el mapa completo de disparador → herramienta.

---

## Revocar el acceso

Si el usuario desea desconectar Hermes de su cuenta de Spotify:

1. Ve a [spotify.com/account/apps](https://www.spotify.com/account/apps/)
2. Busca la app (ej. "Hermes Spotify") y haz clic en **Remove Access**
3. Elimina la caché local de tokens: `rm ~/.hermes/.spotify_cache`
4. Opcionalmente, elimina las credenciales de `~/.hermes/.env` (borra las líneas `SPOTIFY_CLIENT_ID` y `SPOTIFY_CLIENT_SECRET`)

---

## Entorno probado

- Raspberry Pi 4B, 4 GB RAM, Pi OS Lite Bookworm de 64 bits
- Hermes Agent v0.8.0, Python 3.11, spotipy 2.24+
- Modelos: qwen3.6:35b-a3b-nvfp4 (local vía Ollama) y Claude Opus 4.7 (OpenRouter)
- raspotify para Pi-como-altavoz

## Licencia

MIT, ver [LICENSE](LICENSE).

## Créditos

- [Hermes Agent](https://github.com/NousResearch/hermes-agent) por NousResearch
- [spotipy](https://github.com/spotipy-dev/spotipy) por Paul Lamere y colaboradores
- [raspotify](https://github.com/dtcooper/raspotify) por dtcooper
