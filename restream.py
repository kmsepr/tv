#!/usr/bin/env python3
import time
import logging
import subprocess
import requests
from flask import Flask, Response, render_template_string, abort, stream_with_context

logging.basicConfig(level=logging.INFO)
app = Flask(__name__)

CACHE = {}
CACHE_TTL = 1800

# -------------------------------------------------
# PLAYLISTS
# -------------------------------------------------
PLAYLISTS = {
    "all": "https://iptv-org.github.io/iptv/index.m3u",
    "india": "https://iptv-org.github.io/iptv/countries/in.m3u",
    "news": "https://iptv-org.github.io/iptv/categories/news.m3u",
    "sports": "https://iptv-org.github.io/iptv/categories/sports.m3u",
    "malayalam": "https://iptv-org.github.io/iptv/languages/mal.m3u",
    "hindi": "https://iptv-org.github.io/iptv/languages/hin.m3u",
    "arabic": "https://iptv-org.github.io/iptv/languages/ara.m3u",
}

# -------------------------------------------------
# LOAD CHANNELS
# -------------------------------------------------
def load_channels(cat):
    now = time.time()
    if cat in CACHE and now - CACHE[cat]["time"] < CACHE_TTL:
        return CACHE[cat]["channels"]

    url = PLAYLISTS.get(cat)
    if not url:
        return []

    txt = requests.get(url, timeout=25).text
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
# HTML
# -------------------------------------------------
HOME_HTML = """
<!doctype html>
<html>
<head>
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>IPTV</title>
<style>
body{background:#000;color:#0f0;font-family:Arial;padding:12px}
a{display:inline-block;margin:6px;padding:10px 14px;
border:1px solid #0f0;border-radius:10px;
color:#0f0;text-decoration:none}
a:hover{background:#0f0;color:#000}
</style>
</head>
<body>
<h3>📂 Categories</h3>
{% for k in playlists %}
<a href="/list/{{ k }}">{{ k }}</a>
{% endfor %}
<br><br>
<a href="/favourites" style="border-color:yellow;color:yellow">⭐ Favourites</a>
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
body{background:#000;color:#0f0;font-family:Arial;padding:12px}
.card{border:1px solid #0f0;border-radius:10px;padding:10px;margin:8px 0;background:#111}
a,button{display:inline-block;margin:4px;padding:6px 10px;
border:1px solid #0f0;border-radius:6px;color:#0f0;
background:#111;text-decoration:none}
button{cursor:pointer}
</style>
</head>
<body>
<a href="/">⬅ Back</a>
<h3>{{ cat }}</h3>

{% for c in channels %}
<div class="card">
<b>{{ c.title }}</b><br>
<a href="/watch/{{ cat }}/{{ loop.index0 }}">▶ Watch</a>
<a href="/low/{{ cat }}/{{ loop.index0 }}">🔇 Low</a>
<button onclick='addFav("{{ c.title|replace('"','&#34;') }}","{{ c.url }}")'>⭐</button>
</div>
{% endfor %}

<script>
function addFav(title, url){
  let f = JSON.parse(localStorage.getItem("favs") || "[]");
  if(!f.find(x => x.url === url)){
    f.push({title:title, url:url});
    localStorage.setItem("favs", JSON.stringify(f));
    alert("Added to favourites");
  } else {
    alert("Already added");
  }
}
</script>
</body>
</html>
"""

WATCH_HTML = """
<!doctype html>
<html>
<head>
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{{ channel.title }}</title>
<style>
body{margin:0;background:#000}
video{width:100%;height:100vh;background:#000}
</style>
</head>
<body>
<video controls autoplay playsinline>
  <source src="{{ channel.url }}" type="{{ mime }}">
</video>
</body>
</html>
"""

FAV_HTML = """
<!doctype html>
<html>
<head>
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Favourites</title>
<style>
body{background:#000;color:yellow;font-family:Arial;padding:12px}
.card{border:1px solid yellow;border-radius:10px;padding:10px;margin:8px 0;background:#111}
a,button{margin:4px;padding:6px 10px;
border:1px solid yellow;border-radius:6px;
color:yellow;background:#111;text-decoration:none}
button{cursor:pointer}
</style>
</head>
<body>
<a href="/">⬅ Back</a>
<h3>⭐ Favourites</h3>

<div id="list"></div>

<script>
function loadFavs(){
  let f = JSON.parse(localStorage.getItem("favs") || "[]");
  let html = "";
  f.forEach((c,i)=>{
    html += `
      <div class="card">
        <b>${c.title}</b><br>
        <a href="/watch-direct?u=${encodeURIComponent(c.url)}">▶ Watch</a>
        <a href="/low-direct?u=${encodeURIComponent(c.url)}">🔇 Low</a>
        <button onclick="del(${i})">❌</button>
      </div>`;
  });
  document.getElementById("list").innerHTML = html;
}
function del(i){
  let f = JSON.parse(localStorage.getItem("favs"));
  f.splice(i,1);
  localStorage.setItem("favs",JSON.stringify(f));
  loadFavs();
}
loadFavs();
</script>
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

@app.route("/favourites")
def favourites():
    return render_template_string(FAV_HTML)

# -------- RAW M3U8 --------
@app.route("/watch/<cat>/<int:idx>")
def watch(cat, idx):
    ch = load_channels(cat)
    if idx >= len(ch):
        abort(404)
    return render_template_string(
        WATCH_HTML,
        channel=ch[idx],
        mime="application/vnd.apple.mpegurl"
    )

# -------- LOW (NO AUDIO) --------
@app.route("/low/<cat>/<int:idx>")
def low(cat, idx):
    ch = load_channels(cat)
    if idx >= len(ch):
        abort(404)

    channel = {
        "title": ch[idx]["title"] + " (Low)",
        "url": f"/stream-low/{cat}/{idx}"
    }

    return render_template_string(
        WATCH_HTML,
        channel=channel,
        mime="video/mp2t"
    )

@app.route("/stream-low/<cat>/<int:idx>")
def stream_low(cat, idx):
    ch = load_channels(cat)
    if idx >= len(ch):
        abort(404)

    cmd = [
        "ffmpeg","-loglevel","error",
        "-reconnect","1","-reconnect_streamed","1","-reconnect_delay_max","5",
        "-i", ch[idx]["url"],
        "-an",
        "-vf","scale=256:144",
        "-r","12",
        "-c:v","libx264",
        "-profile:v","baseline",
        "-preset","ultrafast",
        "-tune","zerolatency",
        "-b:v","40k","-maxrate","40k","-bufsize","80k",
        "-g","12",
        "-f","mpegts","pipe:1"
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
            p.kill()

    return Response(stream_with_context(gen()), mimetype="video/mp2t")

# -------- DIRECT FAV PLAY --------
@app.route("/watch-direct")
def watch_direct():
    u = requests.utils.unquote(request.args.get("u",""))
    return render_template_string(
        WATCH_HTML,
        channel={"title":"Favourite","url":u},
        mime="application/vnd.apple.mpegurl"
    )

@app.route("/low-direct")
def low_direct():
    u = requests.utils.unquote(request.args.get("u",""))
    cmd = [
        "ffmpeg","-loglevel","error",
        "-i",u,"-an","-vf","scale=256:144","-r","12",
        "-c:v","libx264","-b:v","40k",
        "-f","mpegts","pipe:1"
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
            p.kill()
    return Response(stream_with_context(gen()), mimetype="video/mp2t")

# -------------------------------------------------
if __name__ == "__main__":
    print("▶ http://0.0.0.0:8000")
    app.run(host="0.0.0.0", port=8000, threaded=True)