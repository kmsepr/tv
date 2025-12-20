#!/usr/bin/env python3
import time
import logging
import subprocess
import requests
from flask import Flask, Response, render_template_string, abort

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

# -------------------------------------------------
# ORIGINAL PLAYLIST CATEGORIES (AS YOU GAVE)
# -------------------------------------------------
PLAYLISTS = {
    "all": "https://iptv-org.github.io/iptv/index.m3u",

    "india": "https://iptv-org.github.io/iptv/countries/in.m3u",
    "usa": "https://iptv-org.github.io/iptv/countries/us.m3u",
    "uk": "https://iptv-org.github.io/iptv/countries/uk.m3u",
    "uae": "https://iptv-org.github.io/iptv/countries/ae.m3u",
    "saudi": "https://iptv-org.github.io/iptv/countries/sa.m3u",
    "pakistan": "https://iptv-org.github.io/iptv/countries/pk.m3u",

    "news": "https://iptv-org.github.io/iptv/categories/news.m3u",
    "sports": "https://iptv-org.github.io/iptv/categories/sports.m3u",
    "movies": "https://iptv-org.github.io/iptv/categories/movies.m3u",
    "music": "https://iptv-org.github.io/iptv/categories/music.m3u",
    "kids": "https://iptv-org.github.io/iptv/categories/kids.m3u",
    "entertainment": "https://iptv-org.github.io/iptv/categories/entertainment.m3u",

    "english": "https://iptv-org.github.io/iptv/languages/eng.m3u",
    "hindi": "https://iptv-org.github.io/iptv/languages/hin.m3u",
    "tamil": "https://iptv-org.github.io/iptv/languages/tam.m3u",
    "telugu": "https://iptv-org.github.io/iptv/languages/tel.m3u",
    "malayalam": "https://iptv-org.github.io/iptv/languages/mal.m3u",
    "kannada": "https://iptv-org.github.io/iptv/languages/kan.m3u",

    "arabic": "https://iptv-org.github.io/iptv/languages/ara.m3u",
    "urdu": "https://iptv-org.github.io/iptv/languages/urd.m3u",
}

CACHE = {}
CACHE_TTL = 1800

# -------------------------------------------------
# LOAD CHANNELS FOR A CATEGORY
# -------------------------------------------------
def load_channels(cat):
    now = time.time()
    if cat in CACHE and now - CACHE[cat]["time"] < CACHE_TTL:
        return CACHE[cat]["channels"]

    url = PLAYLISTS.get(cat)
    if not url:
        return []

    txt = requests.get(url, timeout=20).text
    lines = [l.strip() for l in txt.splitlines() if l.strip()]

    channels = []
    for i in range(len(lines)):
        if lines[i].startswith("#EXTINF") and i + 1 < len(lines):
            title = lines[i].split(",", 1)[-1]
            stream = lines[i + 1]
            channels.append({"title": title, "url": stream})

    CACHE[cat] = {"time": now, "channels": channels}
    return channels

# -------------------------------------------------
# UI TEMPLATES
# -------------------------------------------------
HOME_HTML = """
<!doctype html>
<html>
<head>
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>IPTV Categories</title>
<style>
body{background:#000;color:#0f0;font-family:Arial;padding:10px}
a{display:inline-block;margin:6px;padding:10px 14px;
border:1px solid #0f0;border-radius:10px;
color:#0f0;text-decoration:none}
a:hover{background:#0f0;color:#000}
</style>
</head>
<body>
<h3>📂 Categories</h3>
{% for k in playlists %}
<a href="/list/{{ k }}">{{ k.replace('_',' ').title() }}</a>
{% endfor %}
</body>
</html>
"""

LIST_HTML = """
<!doctype html>
<html>
<head>
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{{ cat }}</title>
<style>
body{background:#000;color:#0f0;font-family:Arial;padding:10px}
.card{border:1px solid #0f0;border-radius:10px;padding:10px;margin:8px 0;background:#111}
a{display:inline-block;margin:4px;padding:6px 10px;
border:1px solid #0f0;border-radius:6px;color:#0f0;text-decoration:none}
</style>
</head>
<body>
<a href="/">⬅ Back</a>
<h3>{{ cat.replace('_',' ').title() }}</h3>

{% for c in channels %}
<div class="card">
<b>{{ c.title }}</b><br>
<a href="/watch/{{ cat }}/{{ loop.index0 }}">▶ Watch</a>
<a href="/watch-low/{{ cat }}/{{ loop.index0 }}">🔇 144p</a>
</div>
{% endfor %}
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
    return render_template_string(HOME_HTML, playlists=PLAYLISTS.keys())

@app.route("/list/<cat>")
def list_cat(cat):
    if cat not in PLAYLISTS:
        abort(404)
    return render_template_string(
        LIST_HTML,
        cat=cat,
        channels=load_channels(cat)
    )

@app.route("/watch/<cat>/<int:idx>")
def watch(cat, idx):
    ch = load_channels(cat)
    if idx >= len(ch):
        abort(404)
    return render_template_string(
        WATCH_HTML,
        title=ch[idx]["title"],
        src=ch[idx]["url"],
        mime="application/x-mpegURL"
    )

@app.route("/watch-low/<cat>/<int:idx>")
def watch_low(cat, idx):
    return render_template_string(
        WATCH_HTML,
        title="Low Stream",
        src=f"/stream/{cat}/{idx}",
        mime="video/mp2t"
    )

@app.route("/stream/<cat>/<int:idx>")
def stream(cat, idx):
    ch = load_channels(cat)
    if idx >= len(ch):
        abort(404)

    cmd = [
        "ffmpeg",
        "-loglevel", "error",
        "-i", ch[idx]["url"],
        "-an",
        "-vf", "scale=256:144",
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

    def gen():
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        try:
            while True:
                d = p.stdout.read(4096)
                if not d:
                    break
                yield d
        finally:
            p.terminate()

    return Response(gen(), mimetype="video/mp2t")

# -------------------------------------------------
if __name__ == "__main__":
    print("▶ http://0.0.0.0:8000")
    app.run(host="0.0.0.0", port=8000, threaded=True)