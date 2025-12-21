#!/usr/bin/env python3
import time
import random
import logging
import requests
import subprocess
from flask import Flask, Response, render_template_string, abort, stream_with_context, request

# ============================================================
# BASIC SETUP
# ============================================================
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
app = Flask(__name__)

REFRESH_INTERVAL = 1800

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

    r = requests.get(PLAYLISTS[name], timeout=25)
    ch = parse_m3u(r.text)
    CACHE[name] = {"time": now, "channels": ch}
    return ch

# ============================================================
# VIDEO-ONLY TRANSCODER (NO AUDIO, 144p ~40kbps)
# ============================================================
def proxy_video_no_audio(url):

    cmd = [
        "ffmpeg",
        "-loglevel", "quiet",
        "-i", url,

        # CLEAR 240p
        "-vf", "scale=426:240:flags=lanczos",
        "-r", "18",
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-profile:v", "baseline",
        "-level", "3.0",
        "-pix_fmt", "yuv420p",
        "-b:v", "150k",
        "-maxrate", "170k",
        "-bufsize", "400k",
        "-g", "36",

        # Low but clean audio
        "-c:a", "aac",
        "-b:a", "24k",
        "-ac", "1",
        "-ar", "22050",

        "-f", "mpegts",
        "pipe:1"
    ]

    def generate():
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE)
        try:
            while True:
                chunk = proc.stdout.read(1024)
                if not chunk:
                    break
                yield chunk
        finally:
            proc.kill()

    return Response(
        stream_with_context(generate()),
        mimetype="video/mp2t"
    )

@app.route("/search")
def search():
    q = request.args.get("q","").lower().strip()
    if not q:
        return []

    results = []
    for g in PLAYLISTS:
        for c in get_channels(g):
            if q in c["title"].lower():
                results.append({
                    "title": c["title"],
                    "url": c["url"]
                })
            if len(results) >= 50:
                break
    return results
# ============================================================
# HTML
# ============================================================
HOME_HTML = """<!doctype html>
<html>
<head>
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{{ title }}</title>

<style>
body{
    background:#000;
    color:#0f0;
    margin:0;
    font-family:Arial;
    padding:10px;
    text-align:center;
}
video{
    width:100%;
    height:auto;
    max-height:85vh;
    border:2px solid #0f0;
    margin-top:10px;
}
.btn{
    display:inline-block;
    padding:10px 16px;
    border:2px solid #0f0;
    color:#0f0;
    border-radius:8px;
    text-decoration:none;
    cursor:pointer;
    margin:6px;
    font-size:16px;
}
.btn:hover{
    background:#0f0;
    color:#000;
}
#urlBox{
    width:92%;
    padding:10px;
    font-size:14px;
    border-radius:6px;
    border:2px solid #0f0;
    background:#111;
    color:#0f0;
    margin-top:12px;
}
.copy-btn{
    padding:10px 16px;
    border:2px solid #0f0;
    border-radius:6px;
    color:#0f0;
    background:#111;
    margin-top:8px;
}
.copy-btn:hover{
    background:#0f0;
    color:#000;
}
</style>
</head>

<body>

<h3>{{ title }}</h3>

<!-- ACTION BUTTONS -->
<div>
  <button class="btn" onclick="reloadVideo()">🔄 Reload</button>
  <button class="btn" style="border-color:yellow;color:yellow;" onclick="addFav()">⭐ Favourite</button>
  <a class="btn" href="/">🏠 Home</a>
</div>

<!-- STREAM URL -->
<div>
  <input id="urlBox" value="{{ stream }}" readonly>
  <br>
  <button class="copy-btn" onclick="copyURL()">📋 Copy Stream URL</button>
</div>

<!-- VIDEO PLAYER -->
<video id="vid" controls autoplay playsinline>
  <source src="{{ stream }}" type="video/mp2t">
  Your browser does not support video playback.
</video>

<script>
function reloadVideo(){
    const v = document.getElementById("vid");
    v.pause();
    v.load();
    v.play();
}

function addFav(){
    let f = JSON.parse(localStorage.getItem('favs') || '[]');
    const t = "{{ title }}";
    const u = "{{ stream }}";

    if (!f.find(x => x.url === u)) {
        f.push({title:t, url:u});
        localStorage.setItem('favs', JSON.stringify(f));
        alert("Added to favourites");
    } else {
        alert("Already in favourites");
    }
}

function copyURL(){
    const box = document.getElementById("urlBox");
    box.select();
    box.setSelectionRange(0, 99999); // mobile
    navigator.clipboard.writeText(box.value);
    alert("Stream URL copied");
}
</script>

</body>
</html>"""


LIST_HTML = """
<!doctype html>
<html>
<head>
<meta name="viewport" content="width=device-width,initial-scale=1">
</head>

<body style="background:#000;color:#0f0;font-family:Arial;font-size:22px;padding:14px">

<h2>{{group|upper}}</h2>

<a href="/" style="display:inline-block;padding:14px 18px;border:3px solid #0f0;margin-bottom:14px;font-size:22px">
← Home
</a>

<!-- SEARCH BAR -->
<div style="display:flex;gap:10px;margin:16px 0">
  <input id="search"
         placeholder="Search channel name..."
         style="flex:1;padding:16px;font-size:22px;
                background:#000;color:#0f0;border:3px solid #0f0">

  <button onclick="doSearch()"
          style="padding:16px 22px;
                 font-size:24px;
                 border:3px solid #0f0;
                 background:#000;color:#0f0">
    🔍
  </button>
</div>

<div id="list">
{% for c in channels %}
<div class="item"
     data-title="{{c.title|lower}}"
     style="border:3px solid #0f0;padding:16px;margin:14px 0">

  <div style="font-size:24px;margin-bottom:10px">
    {{loop.index}}. {{c.title}}
  </div>

  <a href="/watch/{{group}}/{{loop.index0}}"
     style="display:inline-block;padding:14px 18px;
            border:3px solid #0f0;font-size:22px">
    ▶ Watch
  </a>

  <button onclick='addFav("{{c.title}}","{{c.url}}")'
          style="padding:14px 18px;
                 border:3px solid yellow;
                 background:#000;color:yellow;
                 font-size:22px;margin-left:10px">
    ⭐ Fav
  </button>
</div>
{% endfor %}
</div>

<script>
function addFav(title,url){
  let f = JSON.parse(localStorage.getItem('favs')||'[]');
  if(!f.find(x=>x.url===url)){
    f.push({title:title,url:url});
    localStorage.setItem('favs',JSON.stringify(f));
    alert("Added to favourites");
  } else {
    alert("Already added");
  }
}

function doSearch(){
  let q = document.getElementById("search").value.toLowerCase().trim();
  let items = document.querySelectorAll(".item");

  items.forEach(el=>{
    if(!q || el.dataset.title.includes(q)){
      el.style.display = "";
    } else {
      el.style.display = "none";
    }
  });
}

// ENTER key triggers search
document.getElementById("search").addEventListener("keydown", function(e){
  if(e.key === "Enter"){
    doSearch();
  }
});
</script>

</body>
</html>
"""

WATCH_HTML = """<!doctype html>
<html>
<head>
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{{ channel.title }}</title>
<style>
body{
    background:#000;
    color:#0f0;
    margin:0;
    font-family:Arial;
    padding:10px;
    text-align:center;
}
video{
    width:100%;
    height:auto;
    max-height:85vh;
    border:2px solid #0f0;
    margin-top:10px;
}
.btn{
    display:inline-block;
    padding:8px 14px;
    border:1px solid #0f0;
    color:#0f0;
    border-radius:6px;
    text-decoration:none;
    cursor:pointer;
    margin:6px;
}
.btn:hover{
    background:#0f0;
    color:#000;
}
#urlBox{
    width:90%;
    padding:8px;
    font-size:14px;
    border-radius:6px;
    border:1px solid #0f0;
    background:#111;
    color:#0f0;
    margin-top:12px;
}
.copy-btn{
    padding:8px 14px;
    border:1px solid #0f0;
    border-radius:6px;
    color:#0f0;
    background:#111;
    margin-left:6px;
}
.copy-btn:hover{
    background:#0f0;
    color:#000;
}
</style>
</head>
<body>

<h3>{{ channel.title }}</h3>

<!-- Buttons -->
<div style="margin-top:5px;">
  <button class="btn" onclick="reloadVideo()">🔄 Reload</button>
  <button class="btn" style="border-color:yellow;color:yellow;" onclick="addFavWatch()">⭐ Favourite</button>
</div>

<!-- Copy URL box -->
<div style="margin-top:15px;">
  <input id="urlBox" value="{{ channel.url }}" readonly>
  <button class="copy-btn" onclick="copyURL()">📋 Copy</button>
</div>

<!-- Video Player -->
<video id="vid" controls autoplay playsinline>
  <source src="{{ channel.url }}" type="{{ mime_type }}">
</video>

<script>
function reloadVideo(){
    const v = document.getElementById("vid");
    v.src = v.src;  // simple reload
    v.play();
}

function addFavWatch(){
    let f = JSON.parse(localStorage.getItem('favs') || '[]');
    const t = "{{ channel.title }}";
    const u = "{{ channel.url }}";
    const l = "{{ channel.logo }}";

    if (!f.find(x => x.url === u)) {
        f.push({title:t, url:u, logo:l});
        localStorage.setItem('favs', JSON.stringify(f));
        alert("Added to favourites");
    } else {
        alert("Already in favourites");
    }
}

function copyURL(){
    const box = document.getElementById("urlBox");
    box.select();
    box.setSelectionRange(0, 99999); // mobile compatibility
    navigator.clipboard.writeText(box.value);
    alert("M3U8 URL copied!");
}
</script>

</body>
</html>"""

FAV_HTML = """
<!doctype html>
<html>
<body style="background:#000;color:#0f0;font-family:Arial;font-size:20px;padding:12px">
<h2>⭐ Favourites</h2>
<a href="/" style="padding:10px;border:2px solid #0f0;display:inline-block;margin-bottom:12px">← Home</a>
<div id="list"></div>

<script>
function load(){
  let f = JSON.parse(localStorage.getItem('favs')||'[]');
  let h='';
  if(!f.length) h='<p>No favourites</p>';
  f.forEach((c,i)=>{
    h+=`
    <div style="border:2px solid yellow;padding:12px;margin:10px 0">
      <div>${i+1}. ${c.title}</div>
      <a href="/watch-direct?title=${encodeURIComponent(c.title)}&url=${encodeURIComponent(c.url)}"
         style="display:inline-block;padding:10px;border:2px solid yellow;color:yellow;margin-top:8px">▶ Watch</a>
      <button onclick="del(${i})"
              style="padding:10px;border:2px solid red;background:#000;color:red;margin-left:10px">✖ Remove</button>
    </div>`;
  });
  document.getElementById('list').innerHTML=h;
}
function del(i){
  let f=JSON.parse(localStorage.getItem('favs')||'[]');
  f.splice(i,1);
  localStorage.setItem('favs',JSON.stringify(f));
  load();
}
load();
</script>
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
    if group not in PLAYLISTS:
        abort(404)
    return render_template_string(LIST_HTML, group=group, channels=get_channels(group))

@app.route("/watch/<group>/<int:idx>")
def watch(group, idx):
    ch = get_channels(group)[idx]
    return render_template_string(WATCH_HTML, title=ch["title"], stream="/stream?u=" + ch["url"])

@app.route("/watch-direct")
def watch_direct():
    return render_template_string(
        WATCH_HTML,
        title=request.args.get("title","Channel"),
        stream="/stream?u=" + request.args.get("url")
    )

@app.route("/stream")
def stream():
    u = request.args.get("u")
    if not u:
        abort(404)
    return proxy_video_no_audio(u)

@app.route("/random")
def random_watch():
    ch = random.choice(get_channels("all"))
    return render_template_string(WATCH_HTML, title=ch["title"], stream="/stream?u=" + ch["url"])

@app.route("/favourites")
def favourites():
    return render_template_string(FAV_HTML)

# ============================================================
# ENTRY
# ============================================================
if __name__ == "__main__":
    print("Running on http://0.0.0.0:8000")
    app.run(host="0.0.0.0", port=8000, threaded=True)