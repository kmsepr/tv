#!/usr/bin/env python3
import time, random, logging, requests, subprocess
from flask import Flask, Response, render_template_string, abort, stream_with_context, request

# ============================================================
# SETUP (UNCHANGED)
# ============================================================
logging.basicConfig(level=logging.INFO)
app = Flask(__name__)
PORT = 8000

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
# M3U PARSER (UNCHANGED)
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
# STREAM (UNCHANGED)
# ============================================================
def proxy_video_144p(url):
    cmd = [
        "ffmpeg", "-i", url,
        "-an",
        "-vf", "scale=256:144",
        "-r", "15",
        "-b:v", "40k",
        "-preset", "ultrafast",
        "-f", "mp4", "pipe:1"
    ]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    for c in iter(lambda: p.stdout.read(4096), b""):
        yield c

# ============================================================
# READABLE UI STYLE (BIG TEXT)
# ============================================================
STYLE = """
<style>
body{
  background:#111;
  color:#fff;
  font-family:Arial, sans-serif;
  font-size:26px;
  padding:16px;
  margin:0;
}
h2,h3{
  text-align:center;
  font-size:30px;
}
.card{
  background:#1e1e1e;
  border-radius:16px;
  padding:18px;
  margin-bottom:18px;
}
.top{
  display:grid;
  grid-template-columns:1fr 1fr;
  gap:16px;
}
a,button,input{
  font-size:26px;
  padding:18px;
  border-radius:14px;
  border:none;
  background:#2c2c2c;
  color:#fff;
  width:100%;
  box-sizing:border-box;
  text-decoration:none;
}
button{cursor:pointer}
.btns{
  display:grid;
  grid-template-columns:1fr 1fr;
  gap:14px;
  margin-top:14px;
}
input{
  background:#000;
}
hr{
  border:none;
  height:2px;
  background:#333;
  margin:22px 0;
}
.small{
  font-size:22px;
  opacity:.8;
}
</style>
"""

# ============================================================
# HOME
# ============================================================
HOME_HTML = """
<!doctype html><html><head>{{style}}</head><body>

<h2>📺 IPTV</h2>

<div class="card">
<form action="/search">
<input name="q" placeholder="Search channel">
</form>
</div>

<div class="top">
  <div class="card"><a href="/random">🎲 RANDOM</a></div>
  <div class="card"><a href="/favourites">⭐ FAVOURITES</a></div>
</div>

<hr>

<h3>Categories</h3>

{% for k in playlists %}
<div class="card">
<a href="/list/{{k}}">{{k|upper}}</a>
</div>
{% endfor %}

</body></html>
"""

# ============================================================
# LIST
# ============================================================
LIST_HTML = """
<!doctype html><html><head>{{style}}</head><body>

<a class="small" href="/">← Back</a>
<hr>

{% for ch in channels %}
<div class="card">
<b>{{loop.index}}. {{ch.title}}</b>

<div class="btns">
<a href="/watch/{{group}}/{{loop.index0}}">▶ WATCH</a>
<a href="/play-144p/{{group}}/{{loop.index0}}">📺 144P</a>
</div>

<button style="margin-top:14px"
 onclick='fav("{{ch.title|replace('"','')}}","{{ch.url}}")'>
⭐ ADD TO FAVOURITES
</button>
</div>
{% endfor %}

<script>
function fav(t,u){
 let f=JSON.parse(localStorage.getItem("favs")||"[]");
 if(!f.find(x=>x.url==u)){
  f.push({title:t,url:u});
  localStorage.setItem("favs",JSON.stringify(f));
  alert("Added to favourites");
 }
}
</script>

</body></html>
"""

# ============================================================
# SEARCH
# ============================================================
SEARCH_HTML = """
<!doctype html><html><head>{{style}}</head><body>

<a class="small" href="/">← Back</a>
<h3>Results</h3>

{% for r in results %}
<div class="card">
<b>{{r.title}}</b>
<div class="btns">
<a href="/watch/all/{{r.index}}">▶ WATCH</a>
<a href="/play-144p/all/{{r.index}}">📺 144P</a>
</div>
</div>
{% endfor %}

</body></html>
"""

# ============================================================
# WATCH
# ============================================================
WATCH_HTML = """
<!doctype html><html><head>{{style}}</head><body>

<h3>{{channel.title}}</h3>

<video controls autoplay playsinline
 style="width:100%;max-height:80vh;border-radius:16px;">
<source src="{{channel.url}}">
</video>

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
    return render_template_string(
        LIST_HTML,
        channels=get_channels(group),
        group=group,
        style=STYLE
    )

@app.route("/search")
def search():
    q = request.args.get("q","").lower()
    res=[]
    for i,ch in enumerate(get_channels("all")):
        if q in ch["title"].lower():
            res.append({"index":i,"title":ch["title"]})
    return render_template_string(SEARCH_HTML, results=res, style=STYLE)

@app.route("/random")
def random_ch():
    return render_template_string(
        WATCH_HTML,
        channel=random.choice(get_channels("all")),
        style=STYLE
    )

@app.route("/watch/<group>/<int:i>")
def watch(group,i):
    return render_template_string(
        WATCH_HTML,
        channel=get_channels(group)[i],
        style=STYLE
    )

@app.route("/play-144p/<group>/<int:i>")
def play_144p(group,i):
    return Response(
        stream_with_context(proxy_video_144p(get_channels(group)[i]["url"])),
        mimetype="video/mp4"
    )

# ============================================================
if __name__ == "__main__":
    print("Running on http://0.0.0.0:8000")
    app.run(host="0.0.0.0", port=8000, threaded=True)