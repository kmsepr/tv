#!/usr/bin/env python3
import time
import logging
import subprocess
import requests
from flask import Flask, Response, render_template_string, abort, request

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

# -------------------------------------------------
# PLAYLIST CATEGORIES (HOME ONLY SHOWS THIS)
# -------------------------------------------------
PLAYLISTS = {
    "India": "https://iptv-org.github.io/iptv/countries/in.m3u",
    "News": "https://iptv-org.github.io/iptv/categories/news.m3u",
    "Sports": "https://iptv-org.github.io/iptv/categories/sports.m3u",
    "Movies": "https://iptv-org.github.io/iptv/categories/movies.m3u",
    "Kids": "https://iptv-org.github.io/iptv/categories/kids.m3u",
    "Malayalam": "https://iptv-org.github.io/iptv/languages/mal.m3u",
    "Hindi": "https://iptv-org.github.io/iptv/languages/hin.m3u",
}

# -------------------------------------------------
# M3U LOADER
# -------------------------------------------------
def load_channels(url, limit=400):
    txt = requests.get(url, timeout=20).text
    lines = [l.strip() for l in txt.splitlines() if l.strip()]
    channels = []

    for i in range(len(lines)):
        if lines[i].startswith("#EXTINF") and i + 1 < len(lines):
            title = lines[i].split(",", 1)[-1]
            url2 = lines[i + 1]
            channels.append({"title": title, "url": url2})
        if len(channels) >= limit:
            break
    return channels

# -------------------------------------------------
# HOME (CATEGORIES + SEARCH + FAV ICONS)
# -------------------------------------------------
HOME_HTML = """
<!doctype html>
<html>
<head>
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>IPTV</title>
<style>
body{background:#000;color:#0f0;font-family:Arial;padding:10px}
a,button,input{font-size:18px;padding:12px;border-radius:8px}
.btn{display:block;margin:6px 0;border:1px solid #0f0;color:#0f0;text-decoration:none;text-align:center}
.row{display:flex;gap:6px}
</style>
</head>
<body>

<form action="/search">
<input name="q" placeholder="Search channel" style="width:100%">
<div class="row">
<button>🔍 Search</button>
<a class="btn" href="/favourites">⭐ Favourites</a>
</div>
</form>

<h3>Categories</h3>
{% for k in categories %}
<a class="btn" href="/category/{{k}}">{{k}}</a>
{% endfor %}

</body>
</html>
"""

# -------------------------------------------------
# CHANNEL LIST (ADD / REMOVE FAV)
# -------------------------------------------------
LIST_HTML = """
<!doctype html>
<html>
<head>
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{{ title }}</title>
<style>
body{background:#000;color:#0f0;font-family:Arial;padding:10px}
.card{border:1px solid #0f0;padding:10px;margin-bottom:8px}
a,button{font-size:16px;padding:8px;margin:4px}
</style>

<script>
function toggleFav(t,u){
 let favs = JSON.parse(localStorage.getItem("favs") || "{}")
 if(favs[u]){
   delete favs[u]
   alert("Removed from favourites")
 }else{
   favs[u] = {title:t,url:u}
   alert("Added to favourites")
 }
 localStorage.setItem("favs", JSON.stringify(favs))
}
</script>
</head>
<body>

<a href="/">⬅ Home</a>
<h3>{{ title }}</h3>

{% for c in channels %}
<div class="card">
<b>{{ c.title }}</b><br>
<a href="/watch?u={{ c.url }}">▶ Watch</a>
<a href="/watch-low?u={{ c.url }}">🔇 144p</a>
<button onclick="toggleFav('{{ c.title }}','{{ c.url }}')">⭐ Fav</button>
</div>
{% endfor %}

</body>
</html>
"""

# -------------------------------------------------
# SEARCH RESULTS (STATIC RESULT PAGE)
# -------------------------------------------------
SEARCH_HTML = """
<!doctype html>
<html>
<head>
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Search</title>
<style>
body{background:#000;color:#0f0;font-family:Arial;padding:10px}
.card{border:1px solid #0f0;padding:10px;margin-bottom:8px}
</style>

<script>
function toggleFav(t,u){
 let favs = JSON.parse(localStorage.getItem("favs") || "{}")
 if(favs[u]){
   delete favs[u]
   alert("Removed")
 }else{
   favs[u] = {title:t,url:u}
   alert("Added")
 }
 localStorage.setItem("favs", JSON.stringify(favs))
}
</script>
</head>
<body>

<a href="/">⬅ Home</a>
<h3>Search results</h3>

{% for c in channels %}
<div class="card">
<b>{{ c.title }}</b><br>
<a href="/watch?u={{ c.url }}">▶ Watch</a>
<button onclick="toggleFav('{{ c.title }}','{{ c.url }}')">⭐ Fav</button>
</div>
{% endfor %}

</body>
</html>
"""

# -------------------------------------------------
# FAVOURITES PAGE (LOCALSTORAGE ONLY)
# -------------------------------------------------
FAV_HTML = """
<!doctype html>
<html>
<head>
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Favourites</title>
<style>
body{background:#000;color:#0f0;font-family:Arial;padding:10px}
.card{border:1px solid #0f0;padding:10px;margin-bottom:8px}
</style>

<script>
function loadFav(){
 let favs = JSON.parse(localStorage.getItem("favs") || "{}")
 let box = document.getElementById("box")
 if(Object.keys(favs).length === 0){
   box.innerHTML = "No favourites added"
   return
 }
 for(let k in favs){
  let f = favs[k]
  box.innerHTML += `
   <div class="card">
    <b>${f.title}</b><br>
    <a href="/watch?u=${f.url}">▶ Watch</a>
    <button onclick="removeFav('${f.url}')">❌ Remove</button>
   </div>`
 }
}
function removeFav(u){
 let favs = JSON.parse(localStorage.getItem("favs") || "{}")
 delete favs[u]
 localStorage.setItem("favs", JSON.stringify(favs))
 location.reload()
}
</script>
</head>
<body onload="loadFav()">

<a href="/">⬅ Home</a>
<h3>⭐ Favourites</h3>
<div id="box"></div>

</body>
</html>
"""

# -------------------------------------------------
# ROUTES
# -------------------------------------------------
@app.route("/")
def home():
    return render_template_string(HOME_HTML, categories=PLAYLISTS.keys())

@app.route("/category/<name>")
def category(name):
    if name not in PLAYLISTS:
        abort(404)
    ch = load_channels(PLAYLISTS[name])
    return render_template_string(LIST_HTML, title=name, channels=ch)

@app.route("/search")
def search():
    q = request.args.get("q","").lower()
    res = []
    for u in PLAYLISTS.values():
        for c in load_channels(u, 200):
            if q in c["title"].lower():
                res.append(c)
    return render_template_string(SEARCH_HTML, channels=res)

@app.route("/favourites")
def favourites():
    return render_template_string(FAV_HTML)

@app.route("/watch")
def watch():
    u = request.args.get("u")
    return Response(f"""
    <video src="{u}" controls autoplay style="width:100%;height:100vh;background:black"></video>
    """, mimetype="text/html")

@app.route("/watch-low")
def watch_low():
    u = request.args.get("u")
    return Response(f"""
    <video src="{u}" controls autoplay style="width:100%;height:100vh;background:black"></video>
    """, mimetype="text/html")

# -------------------------------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, threaded=True)