#!/usr/bin/env python3
import time, logging, subprocess, requests, random
from flask import Flask, Response, render_template_string, abort, stream_with_context, request

logging.basicConfig(level=logging.INFO)
app = Flask(__name__)

CACHE = {}
CACHE_TTL = 1800

PLAYLISTS = {
    "india": "https://iptv-org.github.io/iptv/countries/in.m3u",
    "news": "https://iptv-org.github.io/iptv/categories/news.m3u",
    "sports": "https://iptv-org.github.io/iptv/categories/sports.m3u",
    "malayalam": "https://iptv-org.github.io/iptv/languages/mal.m3u",
    "hindi": "https://iptv-org.github.io/iptv/languages/hin.m3u",
    "arabic": "https://iptv-org.github.io/iptv/languages/ara.m3u",
}

# -------------------------------------------------
def load_channels(cat):
    now = time.time()
    if cat in CACHE and now - CACHE[cat]["time"] < CACHE_TTL:
        return CACHE[cat]["channels"]

    txt = requests.get(PLAYLISTS[cat], timeout=25).text
    lines = [l.strip() for l in txt.splitlines() if l.strip()]
    ch = []

    for i in range(len(lines)):
        if lines[i].startswith("#EXTINF") and i + 1 < len(lines):
            ch.append({
                "title": lines[i].split(",",1)[-1],
                "url": lines[i+1],
                "cat": cat
            })

    CACHE[cat] = {"time": now, "channels": ch}
    return ch

def all_channels():
    a=[]
    for c in PLAYLISTS:
        a.extend(load_channels(c))
    return a

# -------------------------------------------------
HOME_HTML = """
<!doctype html>
<html><head>
<meta name=viewport content="width=device-width,initial-scale=1">
<style>
body{background:#000;color:#0f0;font-family:Arial;padding:14px}
input{width:100%;padding:8px;border-radius:6px;margin:6px 0}
a,button{display:inline-block;margin:6px;padding:10px 14px;
border:1px solid #0f0;border-radius:10px;
background:#111;color:#0f0;text-decoration:none}
.card{border:1px solid #0f0;border-radius:10px;padding:10px;margin:8px 0}
</style></head>
<body>

<h3>📺 IPTV</h3>

<input placeholder="🔍 Search all channels..." onkeyup="filter(this.value)">

<button onclick="randomPlay()">🔀 Random Play</button>
<a href="/favourites" style="border-color:yellow;color:yellow">⭐ Favourites</a>

<h4>📂 Categories</h4>
{% for k in playlists %}
<a href="/list/{{k}}">{{k}}</a>
{% endfor %}

<div id="results">
{% for c in channels %}
<div class="card item">
<b>{{c.title}}</b> ({{c.cat}})<br>
<a href="/watch-direct?u={{c.url}}">▶</a>
<a href="/low-direct?u={{c.url}}">🔇</a>
</div>
{% endfor %}
</div>

<script>
let items=document.querySelectorAll(".item");
function filter(q){
 q=q.toLowerCase();
 items.forEach(i=>{
  i.style.display=i.innerText.toLowerCase().includes(q)?"":"none";
 });
}
function randomPlay(){
 let v=[...items].filter(i=>i.style.display!=="none");
 v[Math.floor(Math.random()*v.length)].querySelector("a").click();
}
</script>
</body></html>
"""

WATCH_HTML = """
<!doctype html>
<html><head>
<meta name=viewport content="width=device-width,initial-scale=1">
<style>body{margin:0;background:#000}video{width:100%;height:100vh}</style>
</head><body>
<video autoplay controls playsinline>
<source src="{{url}}" type="{{mime}}">
</video>
</body></html>
"""

FAV_HTML = """
<!doctype html>
<html><head>
<meta name=viewport content="width=device-width,initial-scale=1">
<style>
body{background:#000;color:yellow;font-family:Arial;padding:12px}
.card{border:1px solid yellow;border-radius:10px;padding:10px;margin:8px 0}
a,button{margin:4px;padding:6px 10px;border:1px solid yellow;background:#111;color:yellow}
</style></head>
<body>
<a href="/">⬅ Back</a>
<h3>⭐ Favourites</h3>
<div id="f"></div>
<script>
let f=JSON.parse(localStorage.getItem("favs")||"[]");
let h="";
f.forEach((c,i)=>{
 h+=`<div class=card><b>${c.title}</b><br>
 <a href="/watch-direct?u=${encodeURIComponent(c.url)}">▶</a>
 <a href="/low-direct?u=${encodeURIComponent(c.url)}">🔇</a>
 <button onclick="del(${i})">❌</button></div>`;
});
document.getElementById("f").innerHTML=h;
function del(i){f.splice(i,1);localStorage.setItem("favs",JSON.stringify(f));location.reload();}
</script>
</body></html>
"""

# -------------------------------------------------
@app.route("/")
def home():
    return render_template_string(
        HOME_HTML,
        playlists=PLAYLISTS,
        channels=all_channels()
    )

@app.route("/list/<cat>")
def list_cat(cat):
    return render_template_string(
        HOME_HTML,
        playlists=PLAYLISTS,
        channels=load_channels(cat)
    )

@app.route("/favourites")
def fav(): return render_template_string(FAV_HTML)

@app.route("/watch-direct")
def wd():
    return render_template_string(WATCH_HTML,
        url=request.args["u"],
        mime="application/vnd.apple.mpegurl")

@app.route("/low-direct")
def ld():
    u=request.args["u"]
    cmd=["ffmpeg","-loglevel","error","-i",u,"-an","-vf","scale=256:144",
         "-r","12","-b:v","40k","-f","mpegts","pipe:1"]
    def g():
        p=subprocess.Popen(cmd,stdout=subprocess.PIPE)
        while d:=p.stdout.read(4096): yield d
    return Response(stream_with_context(g()),mimetype="video/mp2t")

# -------------------------------------------------
if __name__=="__main__":
    app.run("0.0.0.0",8000,threaded=True)