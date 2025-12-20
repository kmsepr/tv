#!/usr/bin/env python3
import time, logging, subprocess, requests
from flask import Flask, Response, render_template_string, abort, request

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

# -------------------------------------------------
# PLAYLISTS (CATEGORIES)
# -------------------------------------------------
PLAYLISTS = {
    "india": "https://iptv-org.github.io/iptv/countries/in.m3u",
    "news": "https://iptv-org.github.io/iptv/categories/news.m3u",
    "sports": "https://iptv-org.github.io/iptv/categories/sports.m3u",
    "movies": "https://iptv-org.github.io/iptv/categories/movies.m3u",
    "music": "https://iptv-org.github.io/iptv/categories/music.m3u",
    "kids": "https://iptv-org.github.io/iptv/categories/kids.m3u",
    "malayalam": "https://iptv-org.github.io/iptv/languages/mal.m3u",
    "tamil": "https://iptv-org.github.io/iptv/languages/tam.m3u",
}

CACHE = {}
CACHE_TTL = 1800

# -------------------------------------------------
# LOAD CHANNELS
# -------------------------------------------------
def load_channels(key):
    now = time.time()
    if key in CACHE and now - CACHE[key]["time"] < CACHE_TTL:
        return CACHE[key]["data"]

    txt = requests.get(PLAYLISTS[key], timeout=20).text
    lines = [l.strip() for l in txt.splitlines() if l.strip()]
    ch = []

    for i in range(len(lines)):
        if lines[i].startswith("#EXTINF") and i + 1 < len(lines):
            title = lines[i].split(",", 1)[-1]
            url = lines[i + 1]
            ch.append({"title": title, "url": url})

    CACHE[key] = {"data": ch, "time": now}
    return ch

# -------------------------------------------------
# HTML (KEYPAD FRIENDLY + LOCALSTORAGE FAV)
# -------------------------------------------------
HTML = """
<!doctype html>
<html>
<head>
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>IPTV</title>
<style>
body{background:#000;color:#0f0;font-family:Arial;padding:10px}
h3{margin:6px 0}
.search{display:flex;gap:6px;margin-bottom:6px}
input{flex:1;padding:14px;font-size:18px;border:1px solid #0f0;background:#111;color:#0f0;border-radius:8px}
button{padding:14px 18px;font-size:18px;border:1px solid #0f0;background:#111;color:#0f0;border-radius:8px}
.nav{display:flex;gap:8px;margin-bottom:12px}
.nav a{flex:1;text-align:center;padding:14px;font-size:18px;
border:1px solid #0f0;background:#111;color:#0f0;border-radius:8px;text-decoration:none}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:12px}
.card{border:1px solid #0f0;border-radius:10px;padding:10px;background:#111;text-align:center}
a.link{display:block;margin:6px 0;padding:10px;border:1px solid #0f0;border-radius:6px;color:#0f0;text-decoration:none}
.small{font-size:14px;padding:6px;margin-top:6px}
</style>

<script>
function favs(){
  try{ return JSON.parse(localStorage.getItem("iptv_favs")||"[]") }
  catch(e){ return [] }
}
function save(f){ localStorage.setItem("iptv_favs",JSON.stringify(f)) }

function toggle(key,title){
 let f=favs();
 let i=f.findIndex(x=>x.key===key);
 if(i>=0){
   if(confirm("Remove from favourites?")){
     f.splice(i,1); save(f); location.reload();
   }
 }else{
   if(confirm("Add to favourites?")){
     f.push({key:key,title:title}); save(f);
     alert("Added to favourites");
   }
 }
}
</script>
</head>

<body>

<h3>📺 IPTV</h3>

<form method="get" action="/search" class="search">
<input name="q" placeholder="Search channels">
<button>🔍</button>
</form>

<div class="nav">
<a href="/">🏠 HOME</a>
<a href="/favourites">⭐ FAVOURITES</a>
</div>

{% if page=="home" %}
<div class="grid">
{% for k,v in items.items() %}
<div class="card">
<a class="link" href="/category/{{ k }}">{{ k.upper() }}</a>
</div>
{% endfor %}
</div>

{% elif page=="list" %}
<div class="grid">
{% for i in items %}
<div class="card">
<b>{{ i.title }}</b>
<a class="link" href="/watch/{{ cat }}/{{ loop.index0 }}">▶ Watch</a>
<a class="link" href="/watch-low/{{ cat }}/{{ loop.index0 }}">🔇 144p</a>
<button class="small"
onclick="toggle('{{ cat }}|{{ loop.index0 }}','{{ i.title }}')">
⭐ Favourite
</button>
</div>
{% endfor %}
</div>

{% elif page=="favs" %}
<div id="favlist" class="grid"></div>
<script>
document.addEventListener("DOMContentLoaded",()=>{
 const box=document.getElementById("favlist");
 const f=favs();
 if(!f.length){ box.innerHTML="<p>No favourites added</p>"; return; }

 f.forEach(x=>{
   let [cat,idx]=x.key.split("|");
   box.innerHTML+=`
   <div class="card">
     <b>${x.title}</b>
     <a class="link" href="/watch/${cat}/${idx}">▶ Watch</a>
     <a class="link" href="/watch-low/${cat}/${idx}">🔇 144p</a>
     <button class="small" onclick="toggle('${x.key}','${x.title}')">
       ❌ Remove
     </button>
   </div>`;
 });
});
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
    return render_template_string(HTML, page="home", items=PLAYLISTS)

@app.route("/category/<cat>")
def category(cat):
    if cat not in PLAYLISTS: abort(404)
    return render_template_string(
        HTML, page="list", items=load_channels(cat), cat=cat
    )

@app.route("/favourites")
def favourites():
    return render_template_string(HTML, page="favs")

@app.route("/watch/<cat>/<int:idx>")
def watch(cat, idx):
    ch = load_channels(cat)
    if idx >= len(ch): abort(404)
    return f"""
    <video controls autoplay playsinline
     style="width:100%;height:100vh;background:#000"
     src="{ch[idx]['url']}"></video>
    """

@app.route("/watch-low/<cat>/<int:idx>")
def watch_low(cat, idx):
    return f"""
    <video controls autoplay playsinline
     style="width:100%;height:100vh;background:#000"
     src="/stream/{cat}/{idx}"></video>
    """

@app.route("/stream/<cat>/<int:idx>")
def stream(cat, idx):
    ch = load_channels(cat)
    if idx >= len(ch): abort(404)

    cmd = [
        "ffmpeg","-loglevel","error",
        "-i", ch[idx]["url"],
        "-an",
        "-vf","scale=256:144",
        "-r","15",
        "-c:v","libx264",
        "-preset","ultrafast",
        "-tune","zerolatency",
        "-b:v","40k",
        "-f","mpegts","pipe:1"
    ]

    def gen():
        p=subprocess.Popen(cmd,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL)
        try:
            while True:
                d=p.stdout.read(4096)
                if not d: break
                yield d
        finally:
            p.terminate()

    return Response(gen(),mimetype="video/mp2t")

# -------------------------------------------------
if __name__ == "__main__":
    print("▶ http://0.0.0.0:8000")
    app.run(host="0.0.0.0", port=8000, threaded=True)