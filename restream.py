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
HOME_HTML = """
<!doctype html>
<html>
<head>
<meta name="viewport" content="width=device-width,initial-scale=1">
</head>

<body style="background:#000;color:#0f0;font-family:Arial;font-size:24px;padding:16px">

<h1>📺 IPTV</h1>

<!-- SEARCH BAR -->
<div style="display:flex;gap:10px;margin:16px 0">
  <input id="q"
         placeholder="Search channels..."
         style="flex:1;padding:18px;font-size:24px;
                background:#000;color:#0f0;border:3px solid #0f0">

  <button onclick="doSearch()"
          style="padding:18px 24px;
                 font-size:26px;
                 border:3px solid #0f0;
                 background:#000;color:#0f0">
    🔍
  </button>
</div>

<div id="results"></div>

<hr style="border:2px solid #0f0;margin:20px 0">

<a href="/random" style="display:block;padding:18px;border:3px solid #0f0;margin-bottom:14px">
🎲 Random
</a>

<a href="/favourites" style="display:block;padding:18px;border:3px solid yellow;color:yellow;margin-bottom:18px">
⭐ Favourites
</a>

{% for k in playlists %}
<a href="/list/{{k}}" style="display:block;padding:18px;border:3px solid #0f0;margin-bottom:12px">
{{k|upper}}
</a>
{% endfor %}

<script>
function doSearch(){
  let q = document.getElementById("q").value.trim();
  let box = document.getElementById("results");
  box.innerHTML = "";

  if(!q) return;

  fetch("/search?q="+encodeURIComponent(q))
    .then(r=>r.json())
    .then(res=>{
      if(!res.length){
        box.innerHTML="<p>No results</p>";
        return;
      }
      res.forEach((c,i)=>{
        box.innerHTML += `
        <div style="border:3px solid #0f0;padding:16px;margin:14px 0">
          <div style="font-size:26px;margin-bottom:10px">${i+1}. ${c.title}</div>
          <a href="/watch-direct?title=${encodeURIComponent(c.title)}&url=${encodeURIComponent(c.url)}"
             style="display:inline-block;padding:16px 20px;
                    border:3px solid #0f0;font-size:22px">
            ▶ Watch
          </a>
          <button onclick='addFav("${c.title.replace(/"/g,'&quot;')}","${c.url}")'
                  style="padding:16px 20px;
                         border:3px solid yellow;
                         background:#000;color:yellow;
                         font-size:22px;margin-left:10px">
            ⭐ Fav
          </button>
        </div>`;
      });
    });
}

function addFav(title,url){
  let f = JSON.parse(localStorage.getItem('favs')||'[]');
  if(!f.find(x=>x.url===url)){
    f.push({title:title,url:url});
    localStorage.setItem('favs',JSON.stringify(f));
    alert("Added");
  }
}

document.getElementById("q").addEventListener("keydown", e=>{
  if(e.key==="Enter") doSearch();
});
</script>

</body>
</html>
"""

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

WATCH_HTML = """
<!doctype html>
<html>
<head>
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{{title}}</title>
<style>
body{background:#000;color:#0f0;font-family:Arial}
video{width:100%;max-height:92vh;border:2px solid #0f0}
</style>
</head>
<body>
<h3 style="text-align:center">{{title}}</h3>
<video controls autoplay playsinline>
  <source src="{{stream}}" type="video/mp2t">
</video>
</body>
</html>
"""

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