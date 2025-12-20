#!/usr/bin/env python3
import time
import logging
import subprocess
import requests
from flask import Flask, Response, render_template_string, abort

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

# -------------------------------------------------
# IPTV PLAYLIST
# -------------------------------------------------
PLAYLIST_URL = "https://iptv-org.github.io/iptv/countries/in.m3u"
CACHE = []
CACHE_TIME = 0
CACHE_TTL = 1800

def load_channels():
    global CACHE, CACHE_TIME
    if time.time() - CACHE_TIME < CACHE_TTL and CACHE:
        return CACHE

    txt = requests.get(PLAYLIST_URL, timeout=20).text
    lines = [l.strip() for l in txt.splitlines() if l.strip()]

    channels = []
    for i in range(len(lines)):
        if lines[i].startswith("#EXTINF") and i + 1 < len(lines):
            title = lines[i].split(",", 1)[-1]
            url = lines[i + 1]
            channels.append({"title": title, "url": url})

    CACHE = channels
    CACHE_TIME = time.time()
    return channels

# -------------------------------------------------
# UI
# -------------------------------------------------
HOME_HTML = """
<!doctype html>
<html>
<head>
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>IPTV</title>
<style>
body{background:#000;color:#0f0;font-family:Arial;padding:10px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:12px}
.card{border:1px solid #0f0;border-radius:10px;padding:10px;background:#111}
.card h4{margin:0 0 10px 0;font-size:14px}
a{display:block;margin:6px 0;padding:6px 8px;
border:1px solid #0f0;border-radius:6px;color:#0f0;text-decoration:none;text-align:center}
a:hover{background:#0f0;color:#000}
</style>
</head>
<body>
<h3>📺 IPTV Streaming</h3>
<div class="grid">
{% for c in channels %}
<div class="card">
<h4>{{ c.title }}</h4>
<a href="/watch/{{ loop.index0 }}">▶ Watch (Original)</a>
<a href="/watch-low/{{ loop.index0 }}">🔇 Watch 144p</a>
</div>
{% endfor %}
</div>
</body>
</html>
"""

WATCH_HTML = """
<!doctype html>
<html>
<head>
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{{ title }}</title>
<style>
body{margin:0;background:#000}
video{width:100%;height:100vh;background:#000}
</style>
</head>
<body>
<video controls autoplay playsinline>
  <source src="{{ src }}" type="{{ mime }}">
</video>
</body>
</html>
"""

# -------------------------------------------------
# ROUTES
# -------------------------------------------------
@app.route("/")
def home():
    return render_template_string(HOME_HTML, channels=load_channels())

# ---- ORIGINAL STREAM (WORKING WATCH) ----
@app.route("/watch/<int:idx>")
def watch(idx):
    ch = load_channels()
    if idx >= len(ch):
        abort(404)

    return render_template_string(
        WATCH_HTML,
        title=ch[idx]["title"],
        src=ch[idx]["url"],
        mime="application/x-mpegURL"
    )

# ---- LOW RES NO AUDIO WATCH (STREAMS) ----
@app.route("/watch-low/<int:idx>")
def watch_low(idx):
    ch = load_channels()
    if idx >= len(ch):
        abort(404)

    return render_template_string(
        WATCH_HTML,
        title=ch[idx]["title"] + " (144p No Audio)",
        src=f"/stream/{idx}",
        mime="video/mp2t"
    )

# ---- ACTUAL STREAM (NEVER OPEN DIRECTLY) ----
@app.route("/stream/<int:idx>")
def stream(idx):
    ch = load_channels()
    if idx >= len(ch):
        abort(404)

    url = ch[idx]["url"]

    cmd = [
        "ffmpeg",
        "-loglevel", "error",
        "-i", url,
        "-an",                         # ❌ remove audio
        "-vf", "scale=256:144",        # 144p
        "-r", "15",
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-tune", "zerolatency",
        "-b:v", "40k",
        "-maxrate", "40k",
        "-bufsize", "240k",
        "-g", "30",
        "-f", "mpegts",
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

    return Response(generate(), mimetype="video/mp2t")

# -------------------------------------------------
# START
# -------------------------------------------------
if __name__ == "__main__":
    print("▶ http://0.0.0.0:8000")
    app.run(host="0.0.0.0", port=8000, threaded=True)