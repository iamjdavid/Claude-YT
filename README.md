# GTA 6 Shorts — canal automatizado

Cada día, este proyecto:

1. **Investiga** qué Shorts de GTA 6 están funcionando (YouTube Data API: vídeos de las últimas 72 h ordenados por *visitas por hora*).
2. **Escribe** un guion original en inglés con Claude (Opus 5.5), que además busca en la web las noticias de GTA 6 de los últimos días y evita repetir temas que ya hayas cubierto.
3. **Genera la voz** (voz neuronal de Microsoft Edge, gratis) con tiempos por palabra.
4. **Crea las imágenes** de cada escena (o usa tus propios clips de gameplay).
5. **Monta** un Short vertical 1080×1920 con zoom/paneo, subtítulos animados palabra a palabra, texto gancho, música opcional con *ducking* y volumen normalizado a −14 LUFS.
6. **Empaqueta** todo listo para subir: `short_FECHA.mp4`, `metadata.json`, `description.txt`, `thumbnail.jpg`, `script.md` (guion + fuentes) y `UPLOAD.md` (checklist).
7. *(Opcional)* **Lo sube** a YouTube como privado/programado.

## Puesta en marcha (10 minutos)

La automatización diaria funciona con GitHub Actions (`.github/workflows/daily-short.yml`). GitHub solo ejecuta los workflows programados desde la rama por defecto, así que fusiona esta rama en `main`.

En GitHub → *Settings → Secrets and variables → Actions*, añade:

| Secret | ¿Obligatorio? | Para qué |
|---|---|---|
| `ANTHROPIC_API_KEY` | Sí | Investigación + guion (console.anthropic.com) |
| `YOUTUBE_API_KEY` | Muy recomendado | Ver qué vídeos funcionan (Google Cloud → habilitar *YouTube Data API v3* → crear clave de API). Gratis. Sin ella se usa yt-dlp, que YouTube suele bloquear desde servidores. |
| `OPENAI_API_KEY` | Opcional | Imágenes de más calidad (`gpt-image-1`). Sin ella se usa Pollinations.ai (gratis). |
| `YT_CLIENT_ID`, `YT_CLIENT_SECRET`, `YT_REFRESH_TOKEN` | Solo para subir automáticamente | Ejecuta en tu ordenador `python scripts/get_youtube_token.py client_secret.json` |

Variables (pestaña *Variables*): `AUTO_UPLOAD=1` para subir cada día, `YT_PRIVACY` = `private` (por defecto), `unlisted` o `public`.

**Cada día** a las 12:23 UTC se genera el vídeo. Descárgalo en *Actions → Daily GTA 6 Short → (ejecución) → Artifacts*. Para generar uno ahora mismo: *Actions → Daily GTA 6 Short → Run workflow*.

## Uso local

```bash
sudo apt install ffmpeg          # o brew install ffmpeg
pip install -r requirements.txt
export ANTHROPIC_API_KEY=... YOUTUBE_API_KEY=...
python -m gta6shorts             # resultado en output/AAAA-MM-DD/
python -m gta6shorts --dry-run   # prueba sin APIs (voz muda, imágenes generadas localmente)
python -m gta6shorts --upload    # además lo sube a YouTube
```

## Clips de directos

Pega el enlace de un directo **ya terminado** (VOD de Twitch o YouTube) y obtén Shorts verticales de sus mejores momentos.

**En GitHub:** *Actions → Clip a stream → Run workflow*, pega el enlace, elige cuántos clips y el formato:
- `blur`: imagen completa sobre un fondo desenfocado (no se corta nada).
- `crop`: pantalla completa (recorta los lados).

Los clips aparecen en *Artifacts* (`stream-clips-N`): `clip_01.mp4`, `clip_01.json` (título, descripción, tags) y `UPLOAD.md`.

**Cómo encuentra los momentos** (en ventanas de 5 s a lo largo de todo el directo):
1. Velocidad del chat (mensajes por minuto, ajustando unos 8 s de retraso).
2. "Hype" en el chat: KEKW, LUL, OMG, W, "clip it", JAJAJA, 💀, "!!!"…
3. Picos de volumen (gritos, explosiones).

Solo descarga esos minutos (no el directo entero), los transcribe con Whisper y Claude elige los mejores, los recorta para que empiecen justo antes de la acción y terminen en la reacción, y escribe títulos en el idioma del clip.

**Local:** `python -m gta6shorts.clips "https://www.twitch.tv/videos/..." --clips 5 --layout blur`

Notas:
- Twitch funciona mejor desde GitHub. YouTube a veces bloquea las descargas desde servidores; si pasa, exporta tus cookies de YouTube (extensión "Get cookies.txt LOCALLY") y guárdalas como secret `YTDLP_COOKIES`.
- **Solo publica clips de tus propios directos o de streamers que te den permiso** (muchos tienen programas de clippers). La descripción incluye siempre el crédito y el enlace al directo original.

## Personalización

- `assets/clips/` — pon aquí **tus propias grabaciones de gameplay** (mp4/mov). Si hay clips, se usan en lugar de imágenes IA: es lo que mejor funciona en el nicho de *clipping*.
- `assets/music/` — música sin copyright (p. ej. de la Biblioteca de audio de YouTube). Se elige una al azar y baja de volumen cuando habla la voz.
- `assets/fonts/` — fuente de los subtítulos (el workflow descarga Anton automáticamente).
- `gta6shorts/config.py` — voz (`TTS_VOICE`), velocidad, búsquedas, estilo visual, modelo de Claude… todo se puede cambiar también con variables de entorno.

## Costes aproximados por vídeo

Claude Opus 5.5 con búsqueda web: unos 0,15–0,40 $. Voz: gratis. Imágenes: gratis con Pollinations, ~0,25–1 $ con OpenAI. GitHub Actions: gratis en repos públicos y dentro de los 2.000 min/mes de los privados (cada ejecución tarda ~3–6 min).

## Importante antes de publicar

- **Revisa `script.md`** (30 segundos): Claude separa lo oficial de los rumores y cita fuentes, pero las noticias de GTA 6 cambian rápido.
- **No resubas clips de otros canales ni del tráiler de Rockstar**: YouTube penaliza el contenido reutilizado y puedes recibir reclamaciones de copyright. El pipeline crea contenido original (guion propio + imágenes generadas o tu gameplay).
- Las imágenes IA están pensadas para evocar la estética "Florida neón" sin copiar arte oficial ni logotipos. Marca *Contenido alterado o sintético: Sí* al subir (la subida automática ya lo hace).
- Empieza con `YT_PRIVACY=private` unos días para revisar la calidad antes de publicar en automático.

## Estructura

```
gta6shorts/
  research.py   # qué está funcionando (YouTube API / yt-dlp)
  script.py     # Claude: investigación con búsqueda web + guion estructurado
  voice.py      # voz Edge TTS + tiempos por palabra
  visuals.py    # clips propios → OpenAI → Pollinations → arte procedural
  montage.py    # ffmpeg: Ken Burns, subtítulos ASS animados, mezcla de audio
  package.py    # metadata, miniatura, checklist de subida
  upload.py     # subida opcional con YouTube Data API
  main.py       # orquestador (python -m gta6shorts)
  clips.py      # clips de directos (python -m gta6shorts.clips URL)
state/history.json  # temas ya publicados (para no repetir)
```
