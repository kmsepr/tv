#!/usr/bin/env python3
import time
import logging
import subprocess
import requests
from flask import Flask, Response, render_template_string, abort, request, redirect, url_for

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

# -------------------------------------------------
# IPTV PLAYLIST
# -------------------------------------------------
PLAYLIST_URL = "https://iptv-org.github.io/iptv/countries/in.m3u"
CACHE = []
CACHE_TIME = 0
CACHE_TTL = 1800
FAVOURITES = set()  # store favourite indexes

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
# UI TEMPLATE
# -------------------------------------------------
HOME_HTML = """
<!doctype html>
<html>
<head>
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>IPTV</title>
<style>
body{background:#000;color:#0f0;font-family:Arial;padding:10px}
form{display:flex;margin-bottom:10px}
input{flex:1;padding:8px;border-radius:6px;border:1px solid #0f0;background:#111;color:#0f0}
button{padding:0 12px;margin-left:4px;border-radius:6px;border:1px solid #0f0;background:#111;color:#0f0;font-size:20px;cursor:pointer}
button:hover{background:#0f0;color:#000}
a.button{margin-left:6px;padding:6px 12px;border:1px solid #0f0;border-radius:6px;color:#0f0;text-decoration:none;text-align:center}
a.button:hover{background:#0f0;color:#000}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:12px}
.card{border:1px solid #0f0;border-radius:10px;padding:10px;background:#111}
.card h4{margin:0 0 10px 0;font-size:14px}
a{display:block;margin:6px 0;padding:6px 8px;border:1px solid #0f0;border-radius:6px;color:#0f0;text-decoration:none;text-align:center}
a:hover{background:#0f0;color:#000}
.fav-btn{font-size:12px;padding:2px 4px;margin-top:4px}
.back-btn{margin-bottom:10px;display:inline-block;padding:6px 8px;border:1px solid #0f0;border-radius:6px;color:#0f0;text-decoration:none}
</style>
</head>
<body>
<h3>📺 IPTV Streaming</h3>

<form method="get" action="/search">
<input type="text" name="q" placeholder="Search channels..." value="{{ query|default('') }}">
<button type="submit">🔍</button>
<a href="/favourites" class="button">⭐ Favourites</a>
</form>

{% if favourites %}
<h4>⭐ Favourites</h4>
<div class="grid">
{% for c in favourites %}
<div class="card">
<h4>{{ c.title }}</h4>
<a href="/watch/{{ c.idx }}">▶ Watch (Original)</a>
<a href="/watch-low/{{ c.idx }}">🔇 Watch 144p</a>
<a class="fav-btn" href="/toggle_fav/{{ c.idx }}">❌ Remove from fav</a>
</div>
{% endfor %}
</div>
{% endif %}

{% if query is defined %}
<a class="back-btn" href="/">⬅ Back to all channels</a>
{% endif %}

{% if channels %}
<h4>{{ query|default('All Channels') }}</h4>
<div class="grid">
{% for c in channels %}
<div class="card">
<h4>{{ c.title }}</h4>
<a href="/watch/{{ c.idx }}">▶ Watch (Original)</a>
<a href="/watch-low/{{ c.idx }}">🔇 Watch 144p</a>
{% if c.idx not in fav_ids %}
<a class="fav-btn" href="/toggle_fav/{{ c.idx }}">⭐ Add to fav</a>
{% else %}
<a class="fav-btn" href="/toggle_fav/{{ c.idx }}">❌ Remove from fav</a>
{% endif %}
</div>
{% endfor %}
</div>
{% else %}
{% if query is defined %}
<p>No results found for "{{ query }}"</p>
{% endif %}
{% endif %}

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
    channels = load_channels()
    channels_with_idx = [{"idx": i, "title": c["title"], "url": c["url"]} 
                         for i, c in enumerate(channels)]

    fav_list = [{"idx": i, "title": channels[i]["title"], "url": channels[i]["url"]}
                for i in FAVOURITES if i < len(channels)]

    return render_template_string(
        HOME_HTML,
        channels=channels_with_idx,
        fav_ids=FAVOURITES,
        favourites=fav_list
    )

@app.route("/search")
def search():
    query = request.args.get("q", "").strip().lower()
    if not query:
        return redirect("/")

    channels = load_channels()
    matched = [{"idx": i, "title": c["title"], "url": c["url"]} 
               for i, c in enumerate(channels) if query in c["title"].lower()]

    return render_template_string(HOME_HTML,
                                  channels=matched,
                                  fav_ids=FAVOURITES,
                                  favourites=[],
                                  query=query)

@app.route("/favourites")
def favourites():
    channels = load_channels()
    fav_list = [{"idx": i, "title": channels[i]["title"], "url": channels[i]["url"]}
                for i in FAVOURITES if i < len(channels)]
    return render_template_string(HOME_HTML,
                                  channels=fav_list,
                                  fav_ids=FAVOURITES,
                                  favourites=[],
                                  query="Favourites")

@app.route("/toggle_fav/<int:idx>")
def toggle_fav(idx):
    if idx in FAVOURITES:
        FAVOURITES.remove(idx)
    else:
        FAVOURITES.add(idx)
    return redirect(request.referrer or "/")

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

@app.route("/stream/<int:idx>")
def stream(idx):
    ch = load_channels()
    if idx >= len(ch):
        abort(404)
    url = ch[idx]["url"]
    cmd = [
        "ffmpeg", "-loglevel", "error", "-i", url, "-an",
        "-vf", "scale=256:144", "-r", "15", "-c:v", "libx264",
        "-preset", "ultrafast", "-tune", "zerolatency",
        "-b:v", "40k", "-maxrate", "40k", "-bufsize", "240k",
        "-g", "30", "-f", "mpegts", "pipe:1"
    ]
    def generate():
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0)
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