import os, sqlite3, re, requests
from flask import Flask, render_template, request, redirect, session
from dotenv import load_dotenv
from functools import wraps
from datetime import datetime
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET")
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL")
AUDD_KEY = os.getenv("AUDD_API_KEY")

# ---------------- DATABASE ----------------
def db(): return sqlite3.connect("database.db", check_same_thread=False)
db().execute("""CREATE TABLE IF NOT EXISTS users(email TEXT PRIMARY KEY)""")
db().execute("""CREATE TABLE IF NOT EXISTS playlists(email TEXT, name TEXT, url TEXT, created TEXT)""")
db().execute("""CREATE TABLE IF NOT EXISTS analytics(email TEXT, category TEXT)""")
db().commit()

# ---------------- AUTH ----------------
def login_required(f):
    @wraps(f)
    def wrap(*a, **k):
        if "email" not in session:
            return redirect("/login")
        return f(*a, **k)
    return wrap

# ---------------- GOOGLE LOGIN ----------------
@app.route("/login")
def login():
    flow = Flow.from_client_secrets_file(
        os.getenv("GOOGLE_CLIENT_SECRETS"),
        scopes=["https://www.googleapis.com/auth/youtube"],
        redirect_uri="http://localhost:5000/callback"
    )
    url, state = flow.authorization_url(access_type="offline", include_granted_scopes="true")
    session["state"] = state
    return redirect(url)

@app.route("/callback")
def callback():
    flow = Flow.from_client_secrets_file(
        os.getenv("GOOGLE_CLIENT_SECRETS"),
        scopes=["https://www.googleapis.com/auth/youtube"],
        state=session["state"],
        redirect_uri="http://localhost:5000/callback"
    )
    flow.fetch_token(authorization_response=request.url)
    creds = flow.credentials

    email = creds.id_token["email"]
    session["email"] = email
    session["admin"] = email == ADMIN_EMAIL
    session["creds"] = creds.to_json()

    db().execute("INSERT OR IGNORE INTO users VALUES(?)", (email,))
    db().commit()
    return redirect("/dashboard")

def youtube():
    creds = Credentials.from_authorized_user_info(eval(session["creds"]))
    return build("youtube", "v3", credentials=creds)

# ---------------- DASHBOARD ----------------
@app.route("/dashboard")
@login_required
def dashboard():
    rows = db().execute(
        "SELECT name,url,created FROM playlists WHERE email=?", (session["email"],)
    ).fetchall()
    return render_template("dashboard.html", playlists=rows)

# ---------------- MANUAL CREATE ----------------
@app.route("/create", methods=["GET","POST"])
@login_required
def create():
    if request.method == "POST":
        title = request.form["title"] or "My Playlist"
        items = request.form["items"].splitlines()
        yt = youtube()

        playlist = yt.playlists().insert(
            part="snippet,status",
            body={"snippet":{"title":title}, "status":{"privacyStatus":"unlisted"}}
        ).execute()

        pid = playlist["id"]
        url = f"https://www.youtube.com/playlist?list={pid}"

        for item in items:
            vid_match = re.search(r"(?:v=|youtu\.be/)([\w-]{11})", item)
            vid = vid_match.group(1) if vid_match else yt.search().list(part="id", q=item, maxResults=1, type="video").execute()["items"][0]["id"]["videoId"]

            yt.playlistItems().insert(
                part="snippet",
                body={"snippet":{"playlistId":pid,"resourceId":{"kind":"youtube#video","videoId":vid}}}
            ).execute()
            category = "Other"
            if "love" in item.lower(): category="Romantic"
            elif "sad" in item.lower(): category="Sad"
            elif "party" in item.lower(): category="Party"
            db().execute("INSERT INTO analytics VALUES(?,?)", (session["email"], category))

        db().execute("INSERT INTO playlists VALUES(?,?,?,?)", (session["email"], title, url, datetime.now()))
        db().commit()
        return redirect("/dashboard")
    return render_template("create.html")

# ---------------- OPTIONAL MUSIC RECOGNITION ----------------
@app.route("/recognize", methods=["GET","POST"])
@login_required
def recognize():
    if request.method == "POST":
        audio = request.files["audio"]
        r = requests.post(
            "https://api.audd.io/",
            files={"file": audio},
            data={"api_token": AUDD_KEY}
        ).json()
        if not r.get("result"):
            return render_template("recognize.html", error="Song could not be recognized")
        session["recognized_song"] = f"{r['result']['title']} {r['result']['artist']}"
        return redirect("/recognize/result")
    return render_template("recognize.html")

@app.route("/recognize/result", methods=["GET","POST"])
@login_required
def recognize_result():
    song = session.get("recognized_song")
    if not song: return redirect("/dashboard")
    yt = youtube()
    if request.method=="POST":
        action = request.form["action"]
        if action=="new":
            playlist = yt.playlists().insert(part="snippet,status", body={"snippet":{"title":"Recognized Songs"},"status":{"privacyStatus":"unlisted"}}).execute()
            pid = playlist["id"]
        else:
            pid = request.form["playlist_id"].split("list=")[-1]
        vid = yt.search().list(part="id", q=song, maxResults=1, type="video").execute()["items"][0]["id"]["videoId"]
        yt.playlistItems().insert(part="snippet", body={"snippet":{"playlistId":pid,"resourceId":{"kind":"youtube#video","videoId":vid}}}).execute()
        db().execute("INSERT INTO playlists VALUES(?,?,?,?)", (session["email"], "Recognized Songs", f"https://youtube.com/playlist?list={pid}", datetime.now()))
        db().commit()
        return redirect("/dashboard")
    playlists = db().execute("SELECT url FROM playlists WHERE email=?", (session["email"],)).fetchall()
    return render_template("recognize_result.html", song=song, playlists=playlists)

# ---------------- ANALYTICS ----------------
@app.route("/analytics")
@login_required
def analytics():
    data = db().execute("SELECT category,COUNT(*) FROM analytics WHERE email=? GROUP BY category", (session["email"],)).fetchall()
    return render_template("analytics.html", data=data)

# ---------------- ADMIN ----------------
@app.route("/admin")
@login_required
def admin():
    if not session.get("admin"): return "Forbidden",403
    users = db().execute("SELECT COUNT(*) FROM users").fetchone()[0]
    playlists = db().execute("SELECT COUNT(*) FROM playlists").fetchone()[0]
    return render_template("admin.html", users=users, playlists=playlists)

# ---------------- LEGAL ----------------
@app.route("/terms")
def terms(): return render_template("terms.html")
@app.route("/privacy")
def privacy(): return render_template("privacy.html")

# ---------------- RUN ----------------
if __name__=="__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
