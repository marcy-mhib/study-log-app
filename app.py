from flask import Flask, render_template, request, redirect, url_for, session
from werkzeug.security import generate_password_hash, check_password_hash
import sqlite3
import datetime
import os

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-key")

def format_time(minutes):
    hours = minutes // 60
    mins = minutes % 60
    return f"{hours}時間{mins}分"

app.jinja_env.globals.update(format_time=format_time)

#学習記録を保存
DB_NAME = "study_logs.db"

def init_db():
    """データベースとテーブルを作成"""
    with sqlite3.connect(DB_NAME) as conn:
        cur = conn.cursor()

        #学習ログ
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                subject TEXT,
                time INTEGER,
                memo TEXT,
                date TEXT
            )
            """
        )

        #目標時間設定
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS settings (
                user_id INTEGER PRIMARY KEY,
                daily_goal INTEGER
            )
            """
        )

        #ユーザー
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE,
                password TEXT
            )
            """
        )

        #テストユーザー
        cur.execute("SELECT COUNT(*) FROM users")
        if cur.fetchone()[0] == 0:
            cur.execute(
                "INSERT INTO users (username,password) VALUES (?,?)",
                ("test", generate_password_hash("1234"))
        )
        conn.commit()

def get_logs(user_id):
    with sqlite3.connect(DB_NAME) as conn:
        cur = conn.cursor()

        cur.execute(
            "SELECT id, subject, time, memo, date FROM logs WHERE user_id=? ORDER BY id DESC",
            (user_id,)
        )
        rows = cur.fetchall()

    return [
        {"id": r[0], "subject": r[1], "time": r[2], "memo": r[3], "date": r[4]}
        for r in rows
    ]

def get_stats(user_id):
    today = str(datetime.date.today())
    start_week = str(datetime.date.today() - datetime.timedelta(days=datetime.date.today().weekday()))

    with sqlite3.connect(DB_NAME) as conn:
        cur = conn.cursor()

        # total
        cur.execute("SELECT SUM(time) FROM logs WHERE user_id=?", (user_id,))
        total = cur.fetchone()[0] or 0

        # today
        cur.execute("SELECT SUM(time) FROM logs WHERE user_id=? AND date=?", (user_id, today))
        today_time = cur.fetchone()[0] or 0

        # week
        cur.execute(
            "SELECT SUM(time) FROM logs WHERE user_id=? AND date BETWEEN ? AND ?",
            (user_id, start_week, today)
        )
        week_time = cur.fetchone()[0] or 0

        # streak
        cur.execute("SELECT DISTINCT date FROM logs WHERE user_id=? ORDER BY date DESC", (user_id,))
        dates = [datetime.date.fromisoformat(r[0]) for r in cur.fetchall()]

    streak = 0
    now = datetime.date.today()

    for d in dates:
        if d == now - datetime.timedelta(days=streak):
            streak += 1
        else:
            break

    if now not in dates:
        streak = 0

    return {
        "total": total,
        "today": today_time,
        "week": week_time,
        "streak": streak
    }

def get_chart_data(user_id, offset=0):
    today = datetime.date.today()
    start = today - datetime.timedelta(days=today.weekday())
    start += datetime.timedelta(weeks=offset)

    week_dates = [start + datetime.timedelta(days=i) for i in range(7)]

    with sqlite3.connect(DB_NAME) as conn:
        cur = conn.cursor()

        cur.execute(
            "SELECT date, subject, SUM(time) FROM logs WHERE user_id=? GROUP BY date, subject",
            (user_id,)
        )
        rows = cur.fetchall()

    data_dict = {}

    for date, subject, time in rows:
        if subject not in data_dict:
            data_dict[subject] = {}
        data_dict[subject][date] = time

    base_colors = [
        "#4e79a7", "#f28e2b", "#e15759",
        "#76b7b2", "#59a14f", "#edc948"
    ]

    color_map = {}
    for i, subject in enumerate(data_dict.keys()):
        color_map[subject] = base_colors[i % len(base_colors)]

    datasets = []

    for subject in data_dict:
        times = []
        for d in week_dates:
            times.append(data_dict[subject].get(str(d), 0) / 60)

        datasets.append({
            "label": subject,
            "data": times,
            "backgroundColor": color_map[subject]
        })

    return {
        "week_dates": [str(d) for d in week_dates],
        "datasets": datasets,
        "color_map": color_map
    }

@app.route("/")
@app.route("/week/<offset>")
def index(offset=0):
    offset = int(offset)

    if "user_id" not in session:
        return redirect("/login")

    user_id = session["user_id"]

    logs = get_logs(user_id)
    stats = get_stats(user_id)
    chart = get_chart_data(user_id, offset)

    goal = get_goal(user_id)

    goal_minutes = goal
    goal_hour = goal // 60
    goal_minute = goal % 60
    goal_achieved = stats["week"] >= goal

    remaining = goal - stats["week"]


    with sqlite3.connect(DB_NAME) as conn:
        cur = conn.cursor()

        cur.execute("SELECT subject, SUM(time) FROM logs WHERE user_id=? GROUP BY subject", (user_id,))
        subject_data = cur.fetchall()

        # 色
        base_colors = ["red", "blue", "green", "orange", "purple", "cyan"]
        color_map = {}

        for i, (subject, _) in enumerate(subject_data):
            color_map[subject] = base_colors[i % len(base_colors)]

        conn.commit()

    return render_template(
        "index.html",
        logs=logs,
        total_time=stats["total"],
        today_time=stats["today"],
        week_time=stats["week"],
        streak=stats["streak"],
        week_dates=chart["week_dates"],
        datasets=chart["datasets"],
        color_map=chart["color_map"],
        goal=goal,
        goal_minutes=goal_minutes,
        goal_hour=goal_hour,
        goal_minute=goal_minute,
        goal_achieved=goal_achieved,
        offset=offset,
        subject_data=subject_data,
        remaining=remaining
    )

#追加処理
@app.route("/add", methods=["POST"])
def add():
    if "user_id" not in session:
        return redirect(url_for("login"))

    subject = request.form.get("subject")
    memo = request.form.get("memo")
    hour = int(request.form.get("hour") or 0)
    minute = int(request.form.get("minute") or 0)

    time = hour * 60 + minute


    today = str(datetime.date.today())

    if subject and time:
        with sqlite3.connect(DB_NAME) as conn:
            cur = conn.cursor()

            user_id = session["user_id"]

            cur.execute(
                "INSERT INTO logs (user_id, subject, time, memo, date) VALUES (?, ?, ?, ?, ?)",
                (user_id, subject, time, memo, today),
            )
            conn.commit()

    return redirect(url_for("index"))

#削除機能
@app.route("/delete/<int:log_id>", methods=["POST"])
def delete(log_id):
    if "user_id" not in session:
        return redirect(url_for("login"))

    user_id = session["user_id"]

    with sqlite3.connect(DB_NAME) as conn:
        cur = conn.cursor()

        cur.execute("DELETE FROM logs WHERE id = ? AND user_id = ?", (log_id, user_id))
        conn.commit()

    return redirect(url_for("index"))

#編集ページ
@app.route("/edit/<int:log_id>")
def edit(log_id):
    if "user_id" not in session:
        return redirect(url_for("login"))

    user_id = session["user_id"]

    with sqlite3.connect(DB_NAME) as conn:
        cur = conn.cursor()

        cur.execute("SELECT id, subject, time, memo, date FROM logs WHERE id=? AND user_id=?", (log_id, user_id,))
        log = cur.fetchone()

        if not log:
            return redirect(url_for("index"))

        # 時間分解
        total_minutes = log[2]
        log_hour = total_minutes // 60
        log_minute = total_minutes % 60

        # 科目一覧
        cur.execute("SELECT DISTINCT subject FROM logs WHERE user_id=?", (user_id,))
        subjects = [row[0] for row in cur.fetchall()]
        conn.commit()

    return render_template(
        "edit.html",
        log=log,
        subjects=subjects,
        log_hour=log_hour,
        log_minute=log_minute
        )

#更新処理
@app.route("/update/<int:log_id>", methods=["POST"])
def update(log_id):
    if "user_id" not in session:
        return redirect(url_for("login"))

    user_id = session["user_id"]

    subject = request.form.get("subject")
    memo = request.form.get("memo")

    hour = int(request.form.get("hour") or 0)
    minute = int(request.form.get("minute") or 0)

    time = hour * 60 + minute

    with sqlite3.connect(DB_NAME) as conn:
        cur = conn.cursor()

        cur.execute(
            "UPDATE logs SET subject = ?, time = ?, memo = ? WHERE id = ? AND user_id = ?",
            (subject, int(time), memo, log_id, user_id)
        )
        conn.commit()

    return redirect(url_for("index"))

#目標時間
def get_goal(user_id):
    with sqlite3.connect(DB_NAME) as conn:
        c = conn.cursor()

        c.execute("SELECT daily_goal FROM settings WHERE user_id=?", (user_id,))
        row = c.fetchone()

    if row:
        return row[0]
    return 120

#目標時間設定フォーム
@app.route("/set_goal", methods=["POST"])
def set_goal():
    if "user_id" not in session:
        return redirect(url_for("login"))

    user_id = session["user_id"]

    hour = int(request.form.get("hour") or 0)
    minute = int(request.form.get("minute") or 0)

    goal = hour * 60 + minute

    with sqlite3.connect(DB_NAME) as conn:
        c = conn.cursor()

        c.execute(
            "REPLACE INTO settings (user_id, daily_goal) VALUES (?, ?)",
            (user_id, goal)
        )
        conn.commit()

    return redirect("/")

#ログイン
@app.route("/login", methods=["GET","POST"])
def login():

    error = None

    if request.method == "POST":

        username = request.form["username"]
        password = request.form["password"]

        with sqlite3.connect(DB_NAME) as conn:
            cur = conn.cursor()

            cur.execute(
                "SELECT id, password FROM users WHERE username=?",
                (username,)
            )

            user = cur.fetchone()

        if user and check_password_hash(user[1], password):
            session["user_id"] = user[0]
            return redirect(url_for("index"))
        else:
            error = "ユーザー名またはパスワードが違います"

    return render_template("login.html", error=error)

#新規ユーザー登録
@app.route("/register", methods=["GET","POST"])
def register():

    error = None

    if request.method == "POST":

        username = request.form["username"]
        password = request.form["password"]

        with sqlite3.connect(DB_NAME) as conn:
            cur = conn.cursor()

            hashed_password = generate_password_hash(password)

            try:
                cur.execute(
                    "INSERT INTO users (username,password) VALUES (?,?)",
                    (username,hashed_password)
                )

                conn.commit()
                return redirect(url_for("login"))

            except sqlite3.IntegrityError:
                error = "このユーザー名はすでに使われています"

    return render_template("register.html", error=error)

#ログアウト
@app.route("/logout")
def logout():

    session.clear()

    return redirect("/login")


if __name__ == "__main__":
    init_db()
    app.run(debug = True)