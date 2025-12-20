#!/usr/bin/env python3
import time, random, logging, requests, subprocess
from flask import Flask, Response, render_template_string, abort, stream_with_context, request

# ============================================================
# SETUP
# ============================================================
logging.basicConfig(level=logging.INFO)
app = Flask(__name__)

REFRESH_INTERVAL = 1800

PLAYLISTS = {
    "all": "https://iptv-org.github.io/iptv/index.m3u",
    "india": "https://iptv-org.github.io/iptv/countries/in.m3u",
    "news": "https://iptv-org.github.io/iptv/categories/news.m3u",
    "sports": "https://iptv-org.github.io/iptv/categories/sports.m3u",
    "malayalam": "https://iptv-org.github.io/iptv/languages/mal.m3u",
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
            url = lines[i + 1]
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
# STREAM PROXIES (UNCHANGED)
# ============================================================
def proxy_audio_only(url):
    cmd = ["ffmpeg", "-i", url, "-vn", "-ac", "1", "-b:a", "40k", "-f", "mp3", "pipe:1"]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    for c in iter(lambda: p.stdout.read(1024), b""):
        yield c

def proxy_video_144p(url):
    cmd = [
        "ffmpeg", "-i", url, "-an",
        "-vf", "scale=-2:144",
        "-b:v", "40k",
        "-preset", "veryfast",
        "-movflags", "frag_keyframe+empty_moov",
        "-f", "mp4", "pipe:1"
    ]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    for c in iter(lambda: p.stdout.read(1024), b""):
        yield c

# ============================================================
# UI STYLE (BIG, CLEAN)
# ============================================================
STYLE = """
<style>
body{
  background:black;
  color:#0f0;
  font-family:Arial, sans-serif;
  font-size:24px;
  padding:14px;
}
h2,h3{text-align:center;margin:10px 0}
.card{
  border:3px solid #0f0;
  border-radius:16px;
  padding:18px;
  margin-bottom:16px;
}
.top-grid{
  display:grid;
  grid-template-columns:1fr 1fr;
  gap:14px;
  margin-bottom:20px;
}
a,button,input{
  font-size:24px;
  padding:16px;
  border-radius:14px;
  border:3px solid #0f0;
  background:black;
  color:#0f0;
  text-decoration:none;
  width:100%;
  box-sizing:border-box;
}
button{cursor:pointer}
.search{margin-bottom:18px}
.btn-row{
  display:grid;
  grid-template-columns:1fr 1fr 1fr;
  gap:12px;
  margin-top:14px;
}
.small-btn{font-size:22px}
hr{border:1px solid #0f0;margin:22px 0}
</style>
"""

# ============================================================
# HTML
# ============================================================
HOME_HTML = """<!doctype html>
<html>
<head>
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>IPTV</title>

<style>
body{
  background:#000;
  color:#0f0;
  font-family:Arial, sans-serif;
  font-size:24px;
  padding:14px;
}
h2{text-align:center;margin:10px 0}
.card{
  border:3px solid #0f0;
  border-radius:16px;
  padding:18px;
  margin-bottom:16px;
}
.top-grid{
  display:grid;
  grid-template-columns:1fr 1fr;
  gap:14px;
}
a,button,input{
  font-size:24px;
  padding:16px;
  border-radius:14px;
  border:3px solid #0f0;
  background:black;
  color:#0f0;
  text-decoration:none;
  width:100%;
  box-sizing:border-box;
}
button{cursor:pointer}
.search{margin-bottom:18px}
hr{border:1px solid #0f0;margin:22px 0}
</style>
</head>

<body>

<h2>📺 IPTV</h2>

<!-- SEARCH -->
<div class="card search">
<form action="/search">
<input name="q" placeholder="🔍 Search channel..." autofocus>
</form>
</div>

<!-- TOP BUTTONS -->
<div class="top-grid">
  <div class="card"><a href="/random">🎲 RANDOM</a></div>
  <div class="card"><a href="/favourites">⭐ FAVOURITES</a></div>
</div>

<hr>

<h3 style="text-align:center">📂 CATEGORIES</h3>

{% for key in playlists %}
<div class="card">
  <a href="/list/{{ key }}">{{ key|upper }}</a>
</div>
{% endfor %}

</body>
</html>
"""

LIST_HTML = """<!doctype html>
<html>
<head>
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{{ group|capitalize }}</title>

<style>
body{
  background:#000;
  color:#0f0;
  font-family:Arial, sans-serif;
  font-size:22px;
  padding:14px;
}
.card{
  border:3px solid #0f0;
  border-radius:16px;
  padding:16px;
  margin-bottom:16px;
}
a,button,input{
  font-size:22px;
  padding:14px;
  border-radius:12px;
  border:3px solid #0f0;
  background:black;
  color:#0f0;
  text-decoration:none;
}
.btn-row{
  display:grid;
  grid-template-columns:1fr 1fr 1fr;
  gap:10px;
  margin-top:12px;
}
hr{border:1px solid #0f0;margin:20px 0}
img{
  width:48px;
  height:48px;
  border-radius:8px;
  background:#222;
}
</style>
</head>

<body>

<a href="/">⬅ BACK</a>
<hr>

<h3 style="text-align:center">{{ group|upper }}</h3>

{% for ch in channels %}
<div class="card">
  <div style="display:flex;gap:12px;align-items:center">
    <div style="font-size:22px">{{ loop.index }}.</div>
    <img src="{{ ch.logo or fallback }}" onerror="this.src='{{ fallback }}'">
    <div style="flex:1;font-size:22px">{{ ch.title }}</div>
  </div>

  <div class="btn-row">
    <a href="/watch/{{ group }}/{{ loop.index0 }}">▶ WATCH</a>
    <a href="/play-audio/{{ group }}/{{ loop.index0 }}">🎧 AUDIO</a>
    <a href="/stream-noaudio/{{ group }}/{{ loop.index0 }}">🔇 144P</a>
  </div>

  <button style="margin-top:10px"
   onclick='addFav("{{ ch.title|replace('"','&#34;') }}","{{ ch.url }}","{{ ch.logo }}")'>
   ⭐ ADD TO FAV
  </button>
</div>
{% endfor %}

<script>
function addFav(title, url, logo){
  let f = JSON.parse(localStorage.getItem('favs') || '[]');
  if(!f.find(x => x.url === url)){
    f.push({title:title, url:url, logo:logo});
    localStorage.setItem('favs', JSON.stringify(f));
    alert("Added to favourites");
  } else {
    alert("Already in favourites");
  }
}
</script>

</body>
</html>
"""

WATCH_HTML = """
<!doctype html>
<html><head>{{style}}</head><body>
<a href="/">⬅ BACK</a>
<h2>{{channel.title}}</h2>
<video controls autoplay style="width:100%;max-height:80vh;border:3px solid #0f0">
<source src="{{channel.url}}">
</video>
</body></html>
"""

SEARCH_HTML = """
<!doctype html>
<html><head>{{style}}</head><body>
<a href="/">⬅ BACK</a><hr>
<h3>Results for "{{q}}"</h3>

{% for ch in results %}
<div class="card">
<b>{{ch.title}}</b>
<div class="btn-row">
<a class="small-btn" href="/watch/all/{{ch.index}}">▶</a>
<a class="small-btn" href="/play-144p/all/{{ch.index}}">📺</a>
<a class="small-btn" href="/play-audio/all/{{ch.index}}">🎧</a>
</div>
</div>
{% endfor %}
</body></html>
"""

FAV_HTML = """
<!doctype html>
<html><head>{{style}}</head><body>
<a href="/">⬅ BACK</a>
<h2>⭐ FAVOURITES</h2>
<div id="f"></div>

<script>
let f=JSON.parse(localStorage.getItem("favs")||"[]");
let h="";
f.forEach(c=>{
 h+=`<div class="card"><b>${c.title}</b>
 <div class="btn-row">
 <a class="small-btn" href="/watch-direct?u=${encodeURIComponent(c.url)}">▶</a>
 <a class="small-btn" href="/play-144p-direct?u=${encodeURIComponent(c.url)}">📺</a>
 <a class="small-btn" href="/play-audio-direct?u=${encodeURIComponent(c.url)}">🎧</a>
 </div></div>`;
});
document.getElementById("f").innerHTML=h;
</script>
</body></html>
"""

# ============================================================
# ROUTES (UNCHANGED)
# ============================================================
@app.route("/")
def home():
    return render_template_string(HOME_HTML, playlists=PLAYLISTS, style=STYLE)

@app.route("/list/<group>")
def list_group(group):
    return render_template_string(LIST_HTML, group=group,
        channels=get_channels(group), style=STYLE)

@app.route("/random")
def random_play():
    ch = random.choice(get_channels("all"))
    return render_template_string(WATCH_HTML, channel=ch, style=STYLE)

@app.route("/watch/<group>/<int:i>")
def watch(group, i):
    return render_template_string(WATCH_HTML,
        channel=get_channels(group)[i], style=STYLE)

@app.route("/search")
def search():
    q = request.args.get("q","").lower()
    res=[]
    for i,ch in enumerate(get_channels("all")):
        if q in ch["title"].lower():
            ch["index"]=i
            res.append(ch)
    return render_template_string(SEARCH_HTML,
        q=q, results=res, style=STYLE)

@app.route("/play-audio/<group>/<int:i>")
def play_audio(group,i):
    return Response(stream_with_context(
        proxy_audio_only(get_channels(group)[i]["url"])),
        mimetype="audio/mpeg")

@app.route("/play-144p/<group>/<int:i>")
def play_144p(group,i):
    return Response(stream_with_context(
        proxy_video_144p(get_channels(group)[i]["url"])),
        mimetype="video/mp4")

@app.route("/play-audio-direct")
def audio_direct():
    return Response(stream_with_context(
        proxy_audio_only(request.args["u"])),
        mimetype="audio/mpeg")

@app.route("/play-144p-direct")
def video_direct():
    return Response(stream_with_context(
        proxy_video_144p(request.args["u"])),
        mimetype="video/mp4")

@app.route("/watch-direct")
def watch_direct():
    return render_template_string(WATCH_HTML,
        channel={"title":"Channel","url":request.args["u"]},
        style=STYLE)

@app.route("/favourites")
def favs():
    return render_template_string(FAV_HTML, style=STYLE)

# ============================================================
if __name__ == "__main__":
    print("Running on http://0.0.0.0:8000")
    app.run(host="0.0.0.0", port=8000, threaded=True)