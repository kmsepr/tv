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
            meta = lines[i]
            title = meta.split(",", 1)[-1]
            group = "Other"
            if 'group-title="' in meta:
                group = meta.split('group-title="')[1].split('"')[0]
            url = lines[i + 1]
            channels.append({
                "title": title,
                "url": url,
                "group": group
            })

    CACHE = channels
    CACHE_TIME = time.time()
    return channels

# -------------------------------------------------
# HOME UI
# -------------------------------------------------
HOME_HTML = """
<!doctype html>
<html>
<head>
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>IPTV</title>
<style>
body{background:#000;color:#0f0;font-family:Arial;padding:10px}
input,select,button{
  padding:6px;border-radius:6px;border:1px solid #0f0;
  background:#000;color:#0f0;margin:4px
}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:12px}
.card{border:1px solid #0f0;border-radius:10px;padding:10px;background:#111}
.card h4{margin:0 0 8px 0;font-size:14px}
a{display:block;margin:4px 0;padding:6px;
border:1px solid #0f0;border-radius:6px;color:#0f0;text-decoration:none;text-align:center}
a:hover{background:#0f0;color:#000}
.fav{cursor:pointer;font-size:18px}
</style>

<script>
let channels = {{ channels | safe }};
let favs = JSON.parse(localStorage.getItem("favs") || "[]");

function render(list){
  const g = document.getElementById("grid");
  g.innerHTML = "";
  list.forEach((c,i)=>{
    const fav = favs.includes(i) ? "★" : "☆";
    g.innerHTML += `
    <div class="card">
      <h4>${c.title}</h4>
      <div>${c.group}</div>
      <div class="fav" onclick="toggleFav(${i})">${fav}</div>
      <a href="/watch/${i}">▶ Watch</a>
      <a href="/watch-low/${i}">🔇 144p</a>
    </div>`;
  });
}

function toggleFav(i){
  if(favs.includes(i)) favs = favs.filter(x=>x!==i);
  else favs.push(i);
  localStorage.setItem("favs",JSON.stringify(favs));
  render(currentList);
}

function filter(){
  const q = document.getElementById("q").value.toLowerCase();
  const cat = document.getElementById("cat").value;
  currentList = channels.filter((c,i)=>{
    return (!q || c.title.toLowerCase().includes(q)) &&
           (!cat || c.group===cat);
  });
  render(currentList);
}

function showFavs(){
  currentList = favs.map(i=>channels[i]).filter(Boolean);
  render(currentList);
}

function randomPlay(){
  const i = Math.floor(Math.random()*channels.length);
  location.href="/watch/"+i;
}

let currentList = channels;
window.onload=()=>render(channels);
</script>
</head>
<body>

<h3>📺 IPTV Streaming</h3>

<input id="q" placeholder="Search..." oninput="filter()">
<select id="cat" onchange="filter()">
  <option value="">All Categories</option>
  {% for c in categories %}
  <option>{{ c }}</option>
  {% endfor %}
</select>

<button onclick="randomPlay()">🎲 Random</button>
<button onclick="showFavs()">⭐ Favourites</button>

<div class="grid" id="grid"></div>

</body>
</html>
"""

# -------------------------------------------------
# WATCH PAGE
# -------------------------------------------------
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
    ch = load_channels()
    categories = sorted(set(c["group"] for c in ch))
    return render_template_string(
        HOME_HTML,
        channels=ch,
        categories=categories
    )

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
        title=ch[idx]["title"] + " (144p)",
        src=f"/stream/{idx}",
        mime="video/mp2t"
    )

@app.route("/stream/<int:idx>")
def stream(idx):
    ch = load_channels()
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