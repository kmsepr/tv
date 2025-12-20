#!/usr/bin/env python3
import time, random, logging, subprocess, requests
from flask import Flask, Response, render_template_string, abort, stream_with_context

# ============================================================
# BASIC SETUP
# ============================================================
app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

REFRESH_INTERVAL = 1800

# ============================================================
# PLAYLISTS
# ============================================================
PLAYLISTS = {
    "india": "https://iptv-org.github.io/iptv/countries/in.m3u",
    "news": "https://iptv-org.github.io/iptv/categories/news.m3u",
}

CACHE = {}

# ============================================================
# M3U PARSER
# ============================================================
def parse_m3u(txt):
    lines = [l.strip() for l in txt.splitlines() if l.strip()]
    out, i = [], 0
    while i < len(lines):
        if lines[i].startswith("#EXTINF"):
            title = lines[i].split(",", 1)[-1]
            url = lines[i+1]
            out.append({"title": title, "url": url})
            i += 2
        else:
            i += 1
    return out

def get_channels(name):
    now = time.time()
    if name in CACHE and now - CACHE[name]["t"] < REFRESH_INTERVAL:
        return CACHE[name]["c"]
    r = requests.get(PLAYLISTS[name], timeout=20)
    ch = parse_m3u(r.text)
    CACHE[name] = {"t": now, "c": ch}
    return ch

# ============================================================
# HTML TEMPLATES
# ============================================================
HOME_HTML = """
<!doctype html>
<html>
<head>
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>IPTV</title>
<style>
body{background:#000;color:#0f0;font-family:monospace}
a{color:#0ff;text-decoration:none;display:block;padding:6px}
</style>
</head>
<body>
<h3>Channels</h3>
{% for i,c in enumerate(channels) %}
<a href="/watch/{{ group }}/{{ i }}">{{ i }}. {{ c.title }}</a>
{% endfor %}
<hr>
<a href="/random">▶ Random</a>
</body>
</html>
"""

WATCH_HTML = """
<!doctype html>
<html>
<head>
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{{ title }}</title>
<style>
body{background:#000;color:#0f0;margin:0;text-align:center}
video{width:100%;max-height:90vh}
</style>
</head>
<body>
<h4>{{ title }}</h4>
<video controls autoplay playsinline>
  <source src="{{ url }}" type="video/mp4">
</video>
</body>
</html>
"""

# ============================================================
# 144p NO-AUDIO VIDEO STREAM (USED BY /watch)
# ============================================================
@app.route("/video/<group>/<int:idx>")
def video_144p(group, idx):
    ch = get_channels(group)
    if idx >= len(ch):
        abort(404)

    src = ch[idx]["url"]

    cmd = [
        "ffmpeg","-loglevel","error",
        "-reconnect","1","-reconnect_streamed","1","-reconnect_delay_max","5",
        "-i",src,
        "-an",
        "-vf","scale=256:144",
        "-r","15",
        "-c:v","libx264",
        "-preset","ultrafast",
        "-tune","zerolatency",
        "-b:v","40k","-maxrate","40k","-bufsize","200k",
        "-movflags","frag_keyframe+empty_moov",
        "-f","mp4","pipe:1"
    ]

    def gen():
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        try:
            while True:
                d = p.stdout.read(4096)
                if not d:
                    break
                yield d
        finally:
            p.terminate()

    return Response(stream_with_context(gen()), mimetype="video/mp4")

# ============================================================
# AUDIO ONLY (UNCHANGED)
# ============================================================
@app.route("/play-audio/<group>/<int:idx>")
def play_audio(group, idx):
    ch = get_channels(group)
    src = ch[idx]["url"]

    cmd = [
        "ffmpeg","-loglevel","error",
        "-i",src,
        "-vn","-ac","1","-ar","22050","-b:a","40k",
        "-f","mp3","pipe:1"
    ]

    def gen():
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        try:
            while True:
                d = p.stdout.read(4096)
                if not d:
                    break
                yield d
        finally:
            p.terminate()

    return Response(stream_with_context(gen()), mimetype="audio/mpeg")

# ============================================================
# ROUTES
# ============================================================
@app.route("/")
def home():
    ch = get_channels("india")
    return render_template_string(HOME_HTML, channels=ch, group="india")

@app.route("/watch/<group>/<int:idx>")
def watch(group, idx):
    ch = get_channels(group)
    return render_template_string(
        WATCH_HTML,
        title=ch[idx]["title"] + " (144p)",
        url=f"/video/{group}/{idx}"
    )

@app.route("/watch-direct/<group>/<int:idx>")
def watch_direct(group, idx):
    ch = get_channels(group)
    return render_template_string(
        WATCH_HTML,
        title=ch[idx]["title"] + " (DIRECT)",
        url=ch[idx]["url"]
    )

@app.route("/random")
def random_watch():
    ch = get_channels("india")
    i = random.randint(0, len(ch)-1)
    return watch("india", i)

# ============================================================
# ENTRY
# ============================================================
if __name__ == "__main__":
    print("Running on http://0.0.0.0:8000")
    app.run(host="0.0.0.0", port=8000, threaded=True)