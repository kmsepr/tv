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
# VIDEO-ONLY TRANSCODER (NO AUDIO, ~40kbps)
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
HOME_HTML = """
<!doctype html>
<html>
<body style="background:#000;color:#0f0;font-family:Arial;font-size:20px;padding:12px">
<h2>📺 IPTV</h2>
<a href="/random" style="display:block;padding:10px;border:2px solid #0f0;margin-bottom:10px">🎲 Random</a>
<a href="/favourites" style="display:block;padding:10px;border:2px solid yellow;color:yellow;margin-bottom:10px">⭐ Favourites</a>
{% for k in playlists %}
<a href="/list/{{k}}" style="display:block;padding:10px;border:2px solid #0f0;margin-bottom:8px">{{k|upper}}</a>
{% endfor %}
</body>
</html>
"""

LIST_HTML = """
<!doctype html>
<html>
<body style="background:#000;color:#0f0;font-family:Arial;font-size:20px;padding:12px">
<h3>{{group|upper}}</h3>
<a href="/" style="padding:10px;border:2px solid #0f0;display:inline-block;margin-bottom:10px">← Home</a>

{% for c in channels %}
<div style="border:2px solid #0f0;padding:12px;margin:10px 0">
  <div>{{loop.index}}. {{c.title}}</div>
  <a href="/watch/{{group}}/{{loop.index0}}" style="display:inline-block;padding:10px;border:2px solid #0f0;margin-top:8px">▶ Watch</a>
  <button onclick='addFav("{{c.title}}","{{c.url}}")'
          style="padding:10px;border:2px solid yellow;background:#000;color:yellow;margin-left:10px">
          ⭐ Fav
  </button>
</div>
{% endfor %}

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
  <source src="{{stream}}" type="video/mp4">
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
        stream="/stream?u=" + ch["url"]
    )

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
    return Response(
        stream_with_context(proxy_video_no_audio(u)),
        mimetype="video/mp4"
    )

@app.route("/random")
def random_watch():
    ch = random.choice(get_channels("all"))
    return render_template_string(
        WATCH_HTML,
        title=ch["title"],
        stream="/stream?u=" + ch["url"]
    )

@app.route("/favourites")
def favourites():
    return render_template_string(FAV_HTML)

# ============================================================
# ENTRY
# ============================================================
if __name__ == "__main__":
    print("Running on http://0.0.0.0:8000")
    app.run(host="0.0.0.0", port=8000, threaded=True)