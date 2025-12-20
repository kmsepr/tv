#!/usr/bin/env python3
import time
import logging
import subprocess
import requests
from flask import Flask, Response, render_template_string, abort, request, redirect

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
            channels.append({"idx": i, "title": title, "url": url})

    CACHE = channels
    CACHE_TIME = time.time()
    return channels

# -------------------------------------------------
# UI TEMPLATE (keypad + localStorage favourites)
# -------------------------------------------------
HTML = """
<!doctype html>
<html>
<head>
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>IPTV</title>
<style>
body{background:#000;color:#0f0;font-family:Arial;padding:10px}
form{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:10px}
input{flex:1;padding:12px;font-size:16px;border-radius:8px;border:1px solid #0f0;background:#111;color:#0f0}
button,a.btn{padding:12px 16px;font-size:18px;border-radius:8px;border:1px solid #0f0;background:#111;color:#0f0;text-decoration:none}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:12px}
.card{border:1px solid #0f0;border-radius:10px;padding:10px;background:#111}
.card h4{margin:0 0 10px 0;font-size:14px}
a.link{display:block;margin:6px 0;padding:6px;border:1px solid #0f0;border-radius:6px;text-align:center}
.fav{font-size:12px;padding:4px;margin-top:6px}
</style>

<script>
function getFavs(){
  return JSON.parse(localStorage.getItem("iptv_favs") || "[]");
}

function saveFavs(favs){
  localStorage.setItem("iptv_favs", JSON.stringify(favs));
}

function toggleFav(idx){
  let favs = getFavs();
  if(favs.includes(idx)){
    favs = favs.filter(i => i !== idx);
  } else {
    favs.push(idx);
  }
  saveFavs(favs);
  location.reload();
}

function isFav(idx){
  return getFavs().includes(idx);
}

function renderFavs(){
  const favs = getFavs();
  const container = document.getElementById("fav-container");
  if(!container) return;

  if(favs.length === 0){
    container.innerHTML = "<p>No favourites</p>";
    return;
  }

  let html = "";
  favs.forEach(i=>{
    html += `
    <div class="card">
      <h4>${channels[i].title}</h4>
      <a class="link" href="/watch/${i}">▶ Watch</a>
      <a class="link" href="/watch-low/${i}">🔇 144p</a>
      <button class="fav" onclick="toggleFav(${i})">❌ Remove</button>
    </div>`;
  });
  container.innerHTML = html;
}
</script>
</head>

<body>
<h3>📺 IPTV Streaming</h3>

<form method="get" action="/search">
<input name="q" placeholder="Search channels">
<button type="submit">🔍</button>
<a href="/favourites" class="btn">⭐</a>
</form>

{% if page == "favourites" %}
<div id="fav-container" class="grid"></div>
<script>
const channels = {{ channels|tojson }};
renderFavs();
</script>

{% else %}
<div class="grid">
{% for c in channels %}
<div class="card">
<h4>{{ c.title }}</h4>
<a class="link" href="/watch/{{ c.idx }}">▶ Watch</a>
<a class="link" href="/watch-low/{{ c.idx }}">🔇 144p</a>
<button class="fav" onclick="toggleFav({{ c.idx }})">
<script>document.write(isFav({{ c.idx }}) ? "❌ Remove" : "⭐ Favourite");</script>
</button>
</div>
{% endfor %}
</div>
<script>
const channels = {{ channels|tojson }};
</script>
{% endif %}
</body>
</html>
"""

# -------------------------------------------------
# ROUTES
# -------------------------------------------------
@app.route("/")
def home():
    return render_template_string(HTML, channels=load_channels(), page="home")

@app.route("/search")
def search():
    q = request.args.get("q","").lower()
    results = [c for c in load_channels() if q in c["title"].lower()]
    return render_template_string(HTML, channels=results, page="search")

@app.route("/favourites")
def favourites():
    return render_template_string(HTML, channels=load_channels(), page="favourites")

@app.route("/watch/<int:idx>")
def watch(idx):
    ch = load_channels()
    if idx >= len(ch): abort(404)
    return f"<video controls autoplay src='{ch[idx]['url']}' style='width:100%;height:100vh'></video>"

@app.route("/watch-low/<int:idx>")
def watch_low(idx):
    return f"<video controls autoplay src='/stream/{idx}' style='width:100%;height:100vh'></video>"

@app.route("/stream/<int:idx>")
def stream(idx):
    url = load_channels()[idx]["url"]
    cmd = [
        "ffmpeg","-loglevel","error","-i",url,"-an",
        "-vf","scale=256:144","-r","15",
        "-c:v","libx264","-preset","ultrafast",
        "-b:v","40k","-f","mpegts","pipe:1"
    ]
    def gen():
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE)
        while True:
            data = p.stdout.read(4096)
            if not data: break
            yield data
    return Response(gen(), mimetype="video/mp2t")

# -------------------------------------------------
# START
# -------------------------------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, threaded=True)