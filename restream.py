#!/usr/bin/env python3
import time
import logging
import random
import requests
import subprocess
from flask import Flask, Response, render_template_string, abort, stream_with_context, request

# ============================================================
# Basic Setup
# ============================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

app = Flask(__name__)

REFRESH_INTERVAL = 1800
LOGO_FALLBACK = "https://iptv-org.github.io/assets/logo.png"

# ============================================================
# PLAYLISTS
# ============================================================
PLAYLISTS = {
    "all": "https://iptv-org.github.io/iptv/index.m3u",
    "india": "https://iptv-org.github.io/iptv/countries/in.m3u",
    "news": "https://iptv-org.github.io/iptv/categories/news.m3u",
    "sports": "https://iptv-org.github.io/iptv/categories/sports.m3u",
    "malayalam": "https://iptv-org.github.io/iptv/languages/mal.m3u",
    "english": "https://iptv-org.github.io/iptv/languages/eng.m3u",
}

CACHE = {}

# ============================================================
# M3U PARSER
# ============================================================
def parse_m3u(text):
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    out = []
    i = 0
    while i < len(lines):
        if lines[i].startswith("#EXTINF"):
            title = lines[i].split(",", 1)[-1]
            url = lines[i + 1] if i + 1 < len(lines) else None
            if url and not url.startswith("#"):
                out.append({"title": title, "url": url})
            i += 2
        else:
            i += 1
    return out

def get_channels(name):
    now = time.time()
    if name in CACHE and now - CACHE[name]["time"] < REFRESH_INTERVAL:
        return CACHE[name]["channels"]

    r = requests.get(PLAYLISTS[name], timeout=20)
    ch = parse_m3u(r.text)
    CACHE[name] = {"time": now, "channels": ch}
    return ch

# ============================================================
# VIDEO-ONLY TRANSCODER (40kbps)
# ============================================================
def proxy_video_no_audio(url):
    cmd = [
        "ffmpeg", "-loglevel", "error",
        "-i", url,
        "-an",
        "-vf", "scale=256:-2",
        "-c:v", "libx264",
        "-b:v", "40k",
        "-preset", "ultrafast",
        "-tune", "zerolatency",
        "-movflags", "frag_keyframe+empty_moov",
        "-f", "mp4",
        "pipe:1"
    ]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE)
    try:
        while True:
            data = p.stdout.read(64 * 1024)
            if not data:
                break
            yield data
    finally:
        p.kill()

# ============================================================
# HTML
# ============================================================
WATCH_HTML = """<!doctype html>
<html>
<head>
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{{ title }}</title>
<style>
body{background:#000;color:#0f0;margin:0;font-family:Arial}
video{width:100%;max-height:92vh;border:2px solid #0f0}
</style>
</head>
<body>
<h3 style="text-align:center">{{ title }}</h3>
<video controls autoplay playsinline>
  <source src="{{ stream_url }}" type="video/mp4">
</video>
</body>
</html>
"""

HOME_HTML = """<!doctype html>
<html>
<body style="background:#000;color:#0f0;font-family:Arial">
<h2>📺 IPTV</h2>
{% for k in playlists %}
<a href="/list/{{k}}" style="display:block;color:#0f0;padding:6px">{{k}}</a>
{% endfor %}
</body>
</html>
"""

LIST_HTML = """<!doctype html>
<html>
<body style="background:#000;color:#0f0;font-family:Arial">
<a href="/">← Back</a>
{% for c in channels %}
<div style="margin:8px 0">
  {{loop.index}}. {{c.title}}
  <a href="/watch/{{group}}/{{loop.index0}}" style="color:#0f0">▶</a>
</div>
{% endfor %}
</body>
</html>
"""

# ============================================================
# ROUTES
# ============================================================
@app.route("/")
def home():
    return render_template_string(HOME_HTML, playlists=PLAYLISTS)

@app.route("/list/<group>")
def list_group(group):
    return render_template_string(
        LIST_HTML,
        group=group,
        channels=get_channels(group)
    )

@app.route("/watch/<group>/<int:idx>")
def watch(group, idx):
    ch = get_channels(group)[idx]
    return render_template_string(
        WATCH_HTML,
        title=ch["title"],
        stream_url=f"/stream?u={ch['url']}"
    )

@app.route("/stream")
def stream():
    url = request.args.get("u")
    if not url:
        abort(404)
    return Response(
        stream_with_context(proxy_video_no_audio(url)),
        mimetype="video/mp4"
    )

@app.route("/random")
def random_watch():
    ch = random.choice(get_channels("all"))
    return render_template_string(
        WATCH_HTML,
        title=ch["title"],
        stream_url=f"/stream?u={ch['url']}"
    )

# ============================================================
# ENTRY
# ============================================================
if __name__ == "__main__":
    print("Running on http://0.0.0.0:8000")
    app.run(host="0.0.0.0", port=8000, threaded=True)