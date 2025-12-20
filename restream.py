#!/usr/bin/env python3
import time
import logging
import random
import requests
import subprocess

from flask import (
    Flask, Response, render_template_string,
    abort, stream_with_context
)

# ============================================================
# BASIC SETUP
# ============================================================
logging.basicConfig(level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s")

app = Flask(__name__)
REFRESH_INTERVAL = 1800
LOGO_FALLBACK = "https://iptv-org.github.io/assets/logo.png"

# ============================================================
# PLAYLISTS
# ============================================================
PLAYLISTS = {
    "all": "https://iptv-org.github.io/iptv/index.m3u",

    # Countries
    "india": "https://iptv-org.github.io/iptv/countries/in.m3u",
    "usa": "https://iptv-org.github.io/iptv/countries/us.m3u",
    "uk": "https://iptv-org.github.io/iptv/countries/uk.m3u",
    "uae": "https://iptv-org.github.io/iptv/countries/ae.m3u",
    "saudi": "https://iptv-org.github.io/iptv/countries/sa.m3u",
    "pakistan": "https://iptv-org.github.io/iptv/countries/pk.m3u",

    # Categories
    "news": "https://iptv-org.github.io/iptv/categories/news.m3u",
    "sports": "https://iptv-org.github.io/iptv/categories/sports.m3u",
    "movies": "https://iptv-org.github.io/iptv/categories/movies.m3u",
    "music": "https://iptv-org.github.io/iptv/categories/music.m3u",
    "kids": "https://iptv-org.github.io/iptv/categories/kids.m3u",
    "entertainment": "https://iptv-org.github.io/iptv/categories/entertainment.m3u",

    # Languages (extended list)
    "english":   "https://iptv-org.github.io/iptv/languages/eng.m3u",
    "hindi":     "https://iptv-org.github.io/iptv/languages/hin.m3u",
    "tamil":     "https://iptv-org.github.io/iptv/languages/tam.m3u",
    "telugu":    "https://iptv-org.github.io/iptv/languages/tel.m3u",
    "malayalam": "https://iptv-org.github.io/iptv/languages/mal.m3u",
    "kannada":   "https://iptv-org.github.io/iptv/languages/kan.m3u",
    "marathi":   "https://iptv-org.github.io/iptv/languages/mar.m3u",
    "gujarati":  "https://iptv-org.github.io/iptv/languages/guj.m3u",
    "bengali":   "https://iptv-org.github.io/iptv/languages/ben.m3u",
    "punjabi":   "https://iptv-org.github.io/iptv/languages/pan.m3u",

    # International languages
    "arabic":  "https://iptv-org.github.io/iptv/languages/ara.m3u",
    "urdu":    "https://iptv-org.github.io/iptv/languages/urd.m3u",
    "french":  "https://iptv-org.github.io/iptv/languages/fra.m3u",
    "spanish": "https://iptv-org.github.io/iptv/languages/spa.m3u",
    "german":  "https://iptv-org.github.io/iptv/languages/deu.m3u",
    "turkish": "https://iptv-org.github.io/iptv/languages/tur.m3u",
    "russian": "https://iptv-org.github.io/iptv/languages/rus.m3u",
    "chinese": "https://iptv-org.github.io/iptv/languages/zho.m3u",
    "japanese":"https://iptv-org.github.io/iptv/languages/jpn.m3u",
    "korean":  "https://iptv-org.github.io/iptv/languages/kor.m3u",
}

CACHE = {}

# ============================================================
# M3U PARSER (FAST & SAFE)
# ============================================================
def parse_m3u(text):
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    out, i = [], 0
    while i < len(lines) - 1:
        if lines[i].startswith("#EXTINF"):
            title = lines[i].split(",", 1)[-1]
            url = lines[i + 1]
            out.append({
                "title": title or "Unknown",
                "url": url,
                "logo": ""
            })
            i += 2
        else:
            i += 1
    return out

def get_channels(name):
    now = time.time()
    cached = CACHE.get(name)
    if cached and now - cached["time"] < REFRESH_INTERVAL:
        return cached["channels"]

    r = requests.get(PLAYLISTS[name], timeout=20)
    channels = parse_m3u(r.text)
    CACHE[name] = {"time": now, "channels": channels}
    logging.info("[%s] %d channels loaded", name, len(channels))
    return channels

# ============================================================
# HTML
# ============================================================
HOME_HTML = """
<!doctype html><html><head>
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>IPTV</title>
<style>
body{background:#000;color:#0f0;font-family:Arial;padding:16px}
a{border:1px solid #0f0;color:#0f0;padding:10px;margin:6px;
   border-radius:8px;display:inline-block;text-decoration:none}
a:hover{background:#0f0;color:#000}
</style></head><body>
<h3>IPTV Categories</h3>
{% for k in playlists %}
<a href="/list/{{k}}">{{k|capitalize}}</a>
{% endfor %}
</body></html>
"""

LIST_HTML = """
<!doctype html><html><head>
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{{group}}</title>
<style>
body{background:#000;color:#0f0;font-family:Arial;padding:12px}
.card{border:1px solid #0f0;border-radius:8px;padding:8px;margin:8px}
a{border:1px solid #0f0;color:#0f0;padding:6px 10px;
   border-radius:6px;text-decoration:none}
a:hover{background:#0f0;color:#000}
</style></head><body>

<h3>{{group|capitalize}} Channels</h3>
<a href="/">← Back</a>

{% for ch in channels %}
<div class="card">
<b>{{loop.index}}. {{ch.title}}</b><br><br>
<a href="/watch/{{group}}/{{loop.index0}}" target="_blank">▶ Watch</a>
<a href="/stream/{{group}}/{{loop.index0}}" target="_blank">🔇 144p</a>
</div>
{% endfor %}
</body></html>
"""

WATCH_HTML = """
<!doctype html><html><head>
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{{channel.title}}</title>
<style>
body{background:#000;color:#0f0;font-family:Arial;text-align:center;margin:0}
video{width:100%;max-height:92vh;border:2px solid #0f0}
</style></head><body>

<h3>{{channel.title}}</h3>

<video autoplay muted playsinline controls>
  <source src="{{channel.url}}" type="video/mp4">
</video>

</body></html>
"""

# ============================================================
# ROUTES
# ============================================================
@app.route("/")
def home():
    return render_template_string(HOME_HTML, playlists=PLAYLISTS)

@app.route("/list/<group>")
def list_group(group):
    if group not in PLAYLISTS:
        abort(404)
    return render_template_string(
        LIST_HTML,
        group=group,
        channels=get_channels(group)
    )

@app.route("/watch/<group>/<int:idx>")
def watch(group, idx):
    ch = get_channels(group)[idx]
    return render_template_string(WATCH_HTML, channel=ch)

# ============================================================
# 🔥 TRUE LOW-BITRATE STREAM (NO AUDIO)
# ============================================================
@app.route("/stream/<group>/<int:idx>")
def stream_noaudio(group, idx):
    ch = get_channels(group)[idx]
    url = ch["url"]

    cmd = [
        "ffmpeg",
        "-loglevel", "error",

        # IPTV stability
        "-fflags", "+nobuffer",
        "-flags", "low_delay",

        "-reconnect", "1",
        "-reconnect_streamed", "1",
        "-reconnect_delay_max", "5",

        "-i", url,

        # NO AUDIO
        "-an",

        # LOW VIDEO
        "-vf", "scale=256:144",
        "-r", "15",

        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-tune", "zerolatency",

        "-b:v", "40k",
        "-maxrate", "40k",
        "-bufsize", "200k",
        "-g", "30",

        # REAL STREAMING (NO DOWNLOAD)
        "-movflags", "frag_keyframe+empty_moov+faststart",
        "-f", "mp4",
        "pipe:1"
    ]

    def generate():
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            bufsize=0
        )
        try:
            while True:
                chunk = proc.stdout.read(4096)
                if not chunk:
                    break
                yield chunk
        finally:
            proc.terminate()
            proc.wait()

    return Response(
        stream_with_context(generate()),
        mimetype="video/mp4",
        headers={"Cache-Control": "no-cache"}
    )

# ============================================================
# ENTRY
# ============================================================
if __name__ == "__main__":
    print("Running IPTV on http://0.0.0.0:8000")
    app.run(host="0.0.0.0", port=8000, threaded=True)