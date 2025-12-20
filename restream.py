#!/usr/bin/env python3
import time, logging, random, subprocess, requests
from flask import Flask, Response, render_template_string, abort, stream_with_context, request

# ============================================================
# Basic Setup
# ============================================================
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
app = Flask(__name__)

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
    "malayalam": "https://iptv-org.github.io/iptv/languages/mal.m3u",
}

CACHE = {}

# ============================================================
# M3U PARSER
# ============================================================
def parse_m3u(txt):
    lines = [l.strip() for l in txt.splitlines() if l.strip()]
    out = []
    i = 0
    while i < len(lines):
        if lines[i].startswith("#EXTINF"):
            title = lines[i].split(",", 1)[-1]
            url = lines[i+1] if i+1 < len(lines) else ""
            out.append({"title": title, "url": url, "logo": ""})
            i += 2
        else:
            i += 1
    return out

def get_channels(name):
    now = time.time()
    if name in CACHE and now - CACHE[name]["time"] < REFRESH_INTERVAL:
        return CACHE[name]["data"]

    r = requests.get(PLAYLISTS[name], timeout=20)
    ch = parse_m3u(r.text)
    CACHE[name] = {"time": now, "data": ch}
    return ch

# ============================================================
# AUDIO ONLY
# ============================================================
def proxy_audio(url):
    cmd = ["ffmpeg","-loglevel","error","-i",url,"-vn","-b:a","40k","-f","mp3","pipe:1"]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE)
    try:
        while True:
            b = p.stdout.read(4096)
            if not b: break
            yield b
    finally:
        p.terminate()

# ============================================================
# HTML
# ============================================================
HOME_HTML = """
<h2>IPTV</h2>
<a href="/favourites">⭐ Favourites</a><br><br>
{% for k in playlists %}
<a href="/list/{{k}}">{{k}}</a><br>
{% endfor %}
"""

LIST_HTML = """
<h3>{{group}}</h3>
<a href="/">⬅ Home</a><br><br>
{% for c in channels %}
<div>
<b>{{c.title}}</b><br>
<a href="/watch/{{group}}/{{loop.index0}}">▶</a>
<a href="/play-audio/{{group}}/{{loop.index0}}">🎧</a>
<a href="/stream-noaudio/{{group}}/{{loop.index0}}">🔇144p</a>
<button onclick="toggleFav('{{c.title}}','{{c.url}}')">⭐</button>
</div><hr>
{% endfor %}

<script>
function toggleFav(t,u){
 let f = JSON.parse(localStorage.getItem("favs")||"{}");
 if(f[u]){ delete f[u]; alert("Removed"); }
 else { f[u]={title:t,url:u}; alert("Added"); }
 localStorage.setItem("favs",JSON.stringify(f));
}
</script>
"""

WATCH_HTML = """
<h3>{{c.title}}</h3>
<a href="/">⬅</a><br><br>
<button onclick="fav()">⭐ Favourite</button><br><br>
<video src="{{c.url}}" controls autoplay style="width:100%"></video>

<script>
function fav(){
 let f=JSON.parse(localStorage.getItem("favs")||"{}");
 let u="{{c.url}}";
 if(!f[u]){ f[u]={title:"{{c.title}}",url:u}; }
 localStorage.setItem("favs",JSON.stringify(f));
 alert("Saved");
}
</script>
"""

FAV_HTML = """
<h2>⭐ Favourites</h2>
<a href="/">⬅ Home</a><br><br>
<div id="box"></div>

<script>
function load(){
 let f=JSON.parse(localStorage.getItem("favs")||"{}");
 let b=document.getElementById("box");
 if(Object.keys(f).length==0){ b.innerHTML="No favourites"; return; }
 for(let k in f){
  b.innerHTML+=`
   <div>
    <b>${f[k].title}</b><br>
    <a href="/watch-direct?u=${encodeURIComponent(f[k].url)}">▶</a>
    <button onclick="del('${k}')">❌</button>
   </div><hr>`;
 }
}
function del(u){
 let f=JSON.parse(localStorage.getItem("favs"));
 delete f[u];
 localStorage.setItem("favs",JSON.stringify(f));
 location.reload();
}
load();
</script>
"""

# ============================================================
# ROUTES
# ============================================================
@app.route("/")
def home(): return render_template_string(HOME_HTML, playlists=PLAYLISTS)

@app.route("/list/<g>")
def lst(g): return render_template_string(LIST_HTML, group=g, channels=get_channels(g))

@app.route("/watch/<g>/<int:i>")
def watch(g,i): return render_template_string(WATCH_HTML, c=get_channels(g)[i])

@app.route("/watch-direct")
def wd(): return render_template_string(WATCH_HTML, c={"title":"Fav","url":request.args["u"]})

@app.route("/favourites")
def fav(): return render_template_string(FAV_HTML)

@app.route("/play-audio/<g>/<int:i>")
def aud(g,i):
    return Response(stream_with_context(proxy_audio(get_channels(g)[i]["url"])), mimetype="audio/mpeg")

@app.route("/stream-noaudio/<g>/<int:i>")
def noaud(g,i):
    cmd=["ffmpeg","-i",get_channels(g)[i]["url"],"-an","-vf","scale=256:144","-b:v","40k","-f","mpegts","pipe:1"]
    def gen():
        p=subprocess.Popen(cmd,stdout=subprocess.PIPE)
        while True:
            b=p.stdout.read(4096)
            if not b: break
            yield b
    return Response(stream_with_context(gen()), mimetype="video/mp2t")

# ============================================================
if __name__ == "__main__":
    app.run("0.0.0.0",8000,threaded=True)