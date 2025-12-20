#!/usr/bin/env python3
import time, logging, subprocess, requests
from flask import Flask, Response, render_template_string, abort, request

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

# -------------------------------------------------
# PLAYLISTS (CATEGORIES)
# -------------------------------------------------
PLAYLISTS = {
    "All Channels": "https://iptv-org.github.io/iptv/index.m3u",

    "India": "https://iptv-org.github.io/iptv/countries/in.m3u",
    "USA": "https://iptv-org.github.io/iptv/countries/us.m3u",
    "UK": "https://iptv-org.github.io/iptv/countries/uk.m3u",
    "UAE": "https://iptv-org.github.io/iptv/countries/ae.m3u",
    "Saudi": "https://iptv-org.github.io/iptv/countries/sa.m3u",
    "Pakistan": "https://iptv-org.github.io/iptv/countries/pk.m3u",

    "News": "https://iptv-org.github.io/iptv/categories/news.m3u",
    "Sports": "https://iptv-org.github.io/iptv/categories/sports.m3u",
    "Movies": "https://iptv-org.github.io/iptv/categories/movies.m3u",
    "Music": "https://iptv-org.github.io/iptv/categories/music.m3u",
    "Kids": "https://iptv-org.github.io/iptv/categories/kids.m3u",
    "Entertainment": "https://iptv-org.github.io/iptv/categories/entertainment.m3u",

    "Malayalam": "https://iptv-org.github.io/iptv/languages/mal.m3u",
    "Hindi": "https://iptv-org.github.io/iptv/languages/hin.m3u",
    "Tamil": "https://iptv-org.github.io/iptv/languages/tam.m3u",
    "Telugu": "https://iptv-org.github.io/iptv/languages/tel.m3u",
    "Arabic": "https://iptv-org.github.io/iptv/languages/ara.m3u",
    "Urdu": "https://iptv-org.github.io/iptv/languages/urd.m3u",
}

CACHE = {}
CACHE_TTL = 1800

def load_playlist(url):
    now = time.time()
    if url in CACHE and now - CACHE[url]["time"] < CACHE_TTL:
        return CACHE[url]["data"]

    txt = requests.get(url, timeout=20).text
    lines = [l.strip() for l in txt.splitlines() if l.strip()]
    channels = []

    for i in range(len(lines)):
        if lines[i].startswith("#EXTINF") and i + 1 < len(lines):
            channels.append({
                "idx": i,
                "title": lines[i].split(",", 1)[-1],
                "url": lines[i + 1]
            })

    CACHE[url] = {"time": now, "data": channels}
    return channels

# -------------------------------------------------
# UI (KEYPAD FRIENDLY)
# -------------------------------------------------
HTML = """
<!doctype html>
<html>
<head>
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>IPTV</title>
<style>
body{background:#000;color:#0f0;font-family:Arial;padding:10px}
h3{margin-top:0}
form{display:flex;gap:6px;margin-bottom:10px}
input{flex:1;padding:12px;font-size:16px;border-radius:8px;border:1px solid #0f0;background:#111;color:#0f0}
button{padding:12px 16px;font-size:18px;border-radius:8px;border:1px solid #0f0;background:#111;color:#0f0}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:12px}
.card{border:1px solid #0f0;border-radius:10px;padding:12px;background:#111;text-align:center}
a{display:block;padding:10px;margin:6px 0;border:1px solid #0f0;border-radius:6px;color:#0f0;text-decoration:none}
a:hover{background:#0f0;color:#000}
</style>
</head>
<body>

<h3>📺 IPTV</h3>

<form method="get" action="/search">
<input name="q" placeholder="Search channels">
<button>🔍</button>
</form>

<div class="grid">
{% for item in items %}
<div class="card">
{% if page == "home" %}
<a href="/category/{{ item.key }}">{{ item.name }}</a>
{% else %}
<b>{{ item.title }}</b>
<a href="/watch/{{ cat }}/{{ item.idx }}">▶ Watch</a>
<a href="/watch-low/{{ cat }}/{{ item.idx }}">🔇 144p</a>
{% endif %}
</div>
{% endfor %}
</div>

</body>
</html>
"""

# -------------------------------------------------
# ROUTES
# -------------------------------------------------
@app.route("/")
def home():
    items = [{"name": k, "key": k} for k in PLAYLISTS]
    return render_template_string(HTML, items=items, page="home")

@app.route("/category/<name>")
def category(name):
    if name not in PLAYLISTS:
        abort(404)
    ch = load_playlist(PLAYLISTS[name])
    return render_template_string(HTML, items=ch, page="list", cat=name)

@app.route("/search")
def search():
    q = request.args.get("q","").lower()
    results = []
    for name,url in PLAYLISTS.items():
        for c in load_playlist(url):
            if q in c["title"].lower():
                c2 = c.copy()
                c2["cat"] = name
                results.append(c2)
    return render_template_string(HTML, items=results, page="list", cat="All")

@app.route("/watch/<cat>/<int:i>")
def watch(cat,i):
    ch = load_playlist(PLAYLISTS[cat])
    if i >= len(ch): abort(404)
    return f"<video controls autoplay src='{ch[i]['url']}' style='width:100%;height:100vh'></video>"

@app.route("/watch-low/<cat>/<int:i>")
def watch_low(cat,i):
    return f"<video controls autoplay src='/stream/{cat}/{i}' style='width:100%;height:100vh'></video>"

@app.route("/stream/<cat>/<int:i>")
def stream(cat,i):
    url = load_playlist(PLAYLISTS[cat])[i]["url"]
    cmd = [
        "ffmpeg","-loglevel","error","-i",url,"-an",
        "-vf","scale=256:144","-r","15",
        "-c:v","libx264","-preset","ultrafast",
        "-b:v","40k","-f","mpegts","pipe:1"
    ]
    def gen():
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE)
        while True:
            d = p.stdout.read(4096)
            if not d: break
            yield d
    return Response(gen(), mimetype="video/mp2t")

# -------------------------------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, threaded=True)