#!/usr/bin/env python3
import os, time, logging, random, requests, subprocess
from flask import Flask, Response, render_template_string, abort, stream_with_context, request

# ============================================================
# Setup
# ============================================================
logging.basicConfig(level=logging.INFO)
app = Flask(__name__)
PORT = 8000

REFRESH_INTERVAL = 1800
LOGO_FALLBACK = "https://iptv-org.github.io/assets/logo.png"

# ============================================================
# PLAYLISTS
# ============================================================
PLAYLISTS = {
    "all": "https://iptv-org.github.io/iptv/index.m3u",
    "india": "https://iptv-org.github.io/iptv/countries/in.m3u",
    "news": "https://iptv-org.github.io/iptv/categories/news.m3u",
    "sports": "https://iptv-org.github.io/iptv/categories/sports.m3u",
    "movies": "https://iptv-org.github.io/iptv/categories/movies.m3u",
    "malayalam": "https://iptv-org.github.io/iptv/languages/mal.m3u",
    "hindi": "https://iptv-org.github.io/iptv/languages/hin.m3u",
}

CACHE = {}

# ============================================================
# M3U PARSER
# ============================================================
def parse_extinf(line):
    if "," in line:
        left, title = line.split(",", 1)
    else:
        left, title = line, ""
    attrs = {}
    pos = 0
    while True:
        eq = left.find("=", pos)
        if eq == -1:
            break
        key_end = eq
        key_start = left.rfind(" ", 0, key_end)
        colon = left.rfind(":", 0, key_end)
        if colon > key_start:
            key_start = colon
        key = left[key_start + 1:key_end].strip()
        if left[eq + 1] == '"':
            val_start = eq + 2
            val_end = left.find('"', val_start)
            val = left[val_start:val_end]
            pos = val_end + 1
        else:
            val_end = left.find(" ", eq + 1)
            if val_end == -1:
                val_end = len(left)
            val = left[eq + 1:val_end]
            pos = val_end
        attrs[key] = val
    return attrs, title.strip()

def parse_m3u(text):
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    out = []
    i = 0
    while i < len(lines):
        if lines[i].startswith("#EXTINF"):
            attrs, title = parse_extinf(lines[i])
            url = lines[i+1]
            out.append({
                "title": title or attrs.get("tvg-name") or "Unknown",
                "url": url,
                "logo": attrs.get("tvg-logo") or ""
            })
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
# MODERN STYLE
# ============================================================
STYLE = """
<style>
body{
  margin:0;
  background:#0f0f0f;
  color:#fff;
  font-family:system-ui,Arial;
  font-size:20px;
  padding:14px;
}
h2,h3{text-align:center;margin:10px 0}
.card{
  background:#1b1b1b;
  border-radius:14px;
  padding:16px;
  margin-bottom:14px;
}
.top{
  display:grid;
  grid-template-columns:1fr 1fr;
  gap:12px;
}
a,button,input{
  font-size:20px;
  padding:14px;
  border-radius:12px;
  border:none;
  background:#2a2a2a;
  color:#fff;
  width:100%;
  text-decoration:none;
}
button{cursor:pointer}
.btns{
  display:grid;
  grid-template-columns:1fr 1fr;
  gap:10px;
  margin-top:12px;
}
hr{
  border:none;
  height:1px;
  background:#333;
  margin:18px 0;
}
.small{opacity:.7;font-size:16px}
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
  <div class="card"><a href="/random">🎲 Random</a></div>
  <div class="card"><a href="/favourites">⭐ Favourites</a></div>
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
<a href="/watch/{{group}}/{{loop.index0}}">▶ Watch</a>
<a href="/stream-noaudio/{{group}}/{{loop.index0}}">📺 144p</a>
</div>

<button style="margin-top:10px"
 onclick='fav("{{ch.title|replace('"','')}}","{{ch.url}}","{{ch.logo}}")'>
⭐ Add to favourites
</button>
</div>
{% endfor %}

<script>
function fav(t,u,l){
 let f=JSON.parse(localStorage.getItem("favs")||"[]");
 if(!f.find(x=>x.url==u)){
  f.push({title:t,url:u,logo:l});
  localStorage.setItem("favs",JSON.stringify(f));
  alert("Added");
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

<h3>Results for "{{query}}"</h3>

{% for r in results %}
<div class="card">
<b>{{r.title}}</b>
<div class="btns">
<a href="/watch/all/{{r.index}}">▶ Watch</a>
<a href="/stream-noaudio/all/{{r.index}}">📺 144p</a>
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

<video controls autoplay playsinline style="width:100%;max-height:80vh;border-radius:12px;">
<source src="{{channel.url}}">
</video>

</body></html>
"""

# ============================================================
# ROUTES
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
    allc = get_channels("all")
    res = []
    for i,c in enumerate(allc):
        if q in c["title"].lower():
            res.append({"index":i,"title":c["title"]})
    return render_template_string(SEARCH_HTML, query=q, results=res, style=STYLE)

@app.route("/random")
def random_ch():
    c = random.choice(get_channels("all"))
    return render_template_string(WATCH_HTML, channel=c, style=STYLE)

@app.route("/watch/<group>/<int:i>")
def watch(group,i):
    return render_template_string(
        WATCH_HTML,
        channel=get_channels(group)[i],
        style=STYLE
    )

# ============================================================
# 144p NO AUDIO STREAM (UNCHANGED)
# ============================================================
@app.route("/stream-noaudio/<group>/<int:i>")
def noaudio(group,i):
    url = get_channels(group)[i]["url"]
    cmd = [
        "ffmpeg","-loglevel","error",
        "-i",url,
        "-an","-vf","scale=256:144","-r","15",
        "-b:v","40k","-f","mpegts","pipe:1"
    ]
    def gen():
        p=subprocess.Popen(cmd,stdout=subprocess.PIPE)
        while True:
            d=p.stdout.read(4096)
            if not d: break
            yield d
    return Response(stream_with_context(gen()),mimetype="video/mp2t")

# ============================================================
if __name__ == "__main__":
    print("Running on http://0.0.0.0:8000")
    app.run(host="0.0.0.0", port=8000, threaded=True)