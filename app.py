import os
import json
from datetime import datetime

from flask import Flask, render_template, request, redirect, url_for, session, flash
from werkzeug.utils import secure_filename
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "fallback-secret-key")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
STATIC_DIR = os.path.join(BASE_DIR, "static")
UPLOAD_DIR = os.path.join(STATIC_DIR, "uploads")

USERS_FILE = os.path.join(DATA_DIR, "users.json")
POSTS_FILE = os.path.join(DATA_DIR, "posts.json")
MESSAGES_FILE = os.path.join(DATA_DIR, "messages.json")

ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif"}


def read_json(path):
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return []


def write_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get_next_id(items):
    if not items:
        return 1
    return max(item["id"] for item in items) + 1


def get_current_user():
    users = read_json(USERS_FILE)
    user_id = session.get("user_id")
    return next((u for u in users if u["id"] == user_id), None)


def is_logged_in():
    return session.get("user_id") is not None


def is_admin():
    user = get_current_user()
    return bool(user and user.get("role") == "admin")


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def get_user_by_id(user_id):
    users = read_json(USERS_FILE)
    return next((u for u in users if u["id"] == user_id), None)


def enrich_post(post):
    user = get_user_by_id(post["user_id"])
    post["author"] = user["username"] if user else "unbekannt"
    post["author_name"] = user["full_name"] if user else "unbekannt"
    return post


def enrich_message(message):
    sender = get_user_by_id(message["sender_id"])
    message["sender_name"] = sender["username"] if sender else "unbekannt"
    return message                      ## Hier werden die Absendernamen zugefügt
                                        ## sofern bekannt. Sonst 'unbekannt'

@app.route("/")
def index():
    posts = read_json(POSTS_FILE)
    user = get_current_user()
    visible_posts = []

    for post in posts:
        if post["visibility"] == "public":
            visible_posts.append(enrich_post(post.copy()))
        elif user and (user["role"] == "admin" or post["user_id"] == user["id"]):
            visible_posts.append(enrich_post(post.copy()))

    return render_template("index.html", posts=visible_posts, user=user)


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        users = read_json(USERS_FILE)

        username = request.form["username"].strip()
        password = request.form["password"].strip()
        full_name = request.form["full_name"].strip()
        garden_name = request.form["garden_name"].strip()
        bio = request.form["bio"].strip()
        role = request.form.get("role", "user").strip()

        if role not in ["admin", "user"]:
            role = "user"

        if any(u["username"] == username for u in users):
            flash("Benutzername existiert bereits.")
            return redirect(url_for("register"))

        users.append({
            "id": get_next_id(users),
            "username": username,
            "password": password,
            "role": role,
            "full_name": full_name,
            "garden_name": garden_name,
            "bio": bio
        })
        write_json(USERS_FILE, users)

        flash("Registrierung erfolgreich.")
        return redirect(url_for("login"))

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        users = read_json(USERS_FILE)
        username = request.form["username"].strip()
        password = request.form["password"].strip()

        user = next((u for u in users if u["username"] == username and u["password"] == password), None)
        if user:
            session["user_id"] = user["id"]
            session["username"] = user["username"]
            session["role"] = user["role"]
            flash("Login erfolgreich.")
            return redirect(url_for("dashboard"))

        flash("Login fehlgeschlagen.")
        return redirect(url_for("login"))

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))


@app.route("/dashboard")
def dashboard():
    if not is_logged_in():
        return redirect(url_for("login"))

    user = get_current_user()
    posts = read_json(POSTS_FILE)
    messages = read_json(MESSAGES_FILE)

    user_posts = [enrich_post(p.copy()) for p in posts if p["user_id"] == user["id"]]
    user_messages = []

    for m in messages:
        if m["recipient_type"] == "public":
            user_messages.append(enrich_message(m.copy()))
        elif m["recipient_type"] == "private" and user["id"] in m["recipient_ids"]:
            user_messages.append(enrich_message(m.copy()))
        elif user["role"] == "admin":
            user_messages.append(enrich_message(m.copy()))

    return render_template("dashboard.html", user=user, posts=user_posts, messages=user_messages)


@app.route("/posts")
def posts():
    posts = read_json(POSTS_FILE)
    user = get_current_user()
    visible_posts = []

    for post in posts:
        if post["visibility"] == "public":
            visible_posts.append(enrich_post(post.copy()))
        elif user and (user["role"] == "admin" or post["user_id"] == user["id"]):
            visible_posts.append(enrich_post(post.copy()))

    return render_template("posts.html", posts=visible_posts, user=user)


@app.route("/posts/new", methods=["GET", "POST"])
def post_new():
    if not is_logged_in():
        return redirect(url_for("login"))

    if request.method == "POST":
        posts = read_json(POSTS_FILE)

        title = request.form["title"].strip()
        content = request.form["content"].strip()
        tags_text = request.form.get("tags", "").strip()
        visibility = request.form["visibility"]

        image_name = ""
        file = request.files.get("image")
        if file and file.filename and allowed_file(file.filename):
            os.makedirs(UPLOAD_DIR, exist_ok=True)
            filename = secure_filename(file.filename)
            save_path = os.path.join(UPLOAD_DIR, filename)
            file.save(save_path)
            image_name = f"uploads/{filename}"

        post = {
            "id": get_next_id(posts),
            "user_id": session["user_id"],
            "title": title,
            "content": content,
            "tags": [t.strip() for t in tags_text.split(",") if t.strip()],
            "image": image_name,
            "visibility": visibility,
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M")
        }

        posts.append(post)
        write_json(POSTS_FILE, posts)
        flash("Beitrag gespeichert.")
        return redirect(url_for("posts"))

    return render_template("post_new.html", user=get_current_user())


@app.route("/posts/<int:post_id>")
def post_detail(post_id):
    posts = read_json(POSTS_FILE)
    post = next((p for p in posts if p["id"] == post_id), None)

    if not post:
        return "Beitrag nicht gefunden", 404

    user = get_current_user()

    if post["visibility"] == "private" and not user:
        return redirect(url_for("login"))

    if post["visibility"] == "private" and user and not (user["role"] == "admin" or post["user_id"] == user["id"]):
        return "Kein Zugriff", 403

    return render_template("post_detail.html", post=enrich_post(post.copy()), user=user)


@app.route("/messages/new", methods=["GET", "POST"])
def message_new():
    if not is_logged_in():
        return redirect(url_for("login"))

    users = read_json(USERS_FILE)

    if request.method == "POST":
        messages = read_json(MESSAGES_FILE)

        recipient_type = request.form["recipient_type"]
        subject = request.form["subject"].strip()
        content = request.form["content"].strip()
        recipient_ids = request.form.getlist("recipient_ids")
        group_name = request.form.get("group_name", "").strip()

        if recipient_type == "public":
            recipient_ids = []
            group_name = "all"

        message = {
            "id": get_next_id(messages),
            "sender_id": session["user_id"],
            "recipient_type": recipient_type,
            "recipient_ids": [int(r) for r in recipient_ids],
            "group_name": group_name,
            "subject": subject,
            "content": content,
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M")
        }

        messages.append(message)
        write_json(MESSAGES_FILE, messages)
        flash("Nachricht gesendet.")
        return redirect(url_for("dashboard"))

    return render_template("message_new.html", users=users, user=get_current_user())


@app.route("/inbox")
def inbox():
    if not is_logged_in():
        return redirect(url_for("login"))

    user = get_current_user()
    messages = read_json(MESSAGES_FILE)
    inbox_messages = []

    for m in messages:
        if m["recipient_type"] == "public":
            inbox_messages.append(enrich_message(m.copy()))
        elif m["recipient_type"] == "private" and user["id"] in m["recipient_ids"]:
            inbox_messages.append(enrich_message(m.copy()))
        elif user["role"] == "admin":
            inbox_messages.append(enrich_message(m.copy()))

    return render_template("inbox.html", messages=inbox_messages, user=user)


@app.route("/admin")
def admin():
    if not is_logged_in() or not is_admin():
        return redirect(url_for("login"))

    users = read_json(USERS_FILE)
    posts = [enrich_post(p.copy()) for p in read_json(POSTS_FILE)]
    messages = [enrich_message(m.copy()) for m in read_json(MESSAGES_FILE)]

    return render_template("admin.html", users=users, posts=posts, messages=messages, user=get_current_user())


@app.route("/profile")
def profile():
    if not is_logged_in():
        return redirect(url_for("login"))
    return render_template("profile.html", user=get_current_user())


if __name__ == "__main__":
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(UPLOAD_DIR, exist_ok=True)

    for file_path in [USERS_FILE, POSTS_FILE, MESSAGES_FILE]:
        if not os.path.exists(file_path):
            write_json(file_path, [])

    app.run(debug=os.getenv("FLASK_DEBUG", "1") == "1")