import os
import sqlite3
import secrets
from functools import wraps

from flask import (
    Flask, request, redirect, url_for,
    flash, session, render_template_string
)
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY") or secrets.token_hex(32)

DB_NAME = "finance.db"


# =========================
# DATABASE
# =========================

def connect():
    con = sqlite3.connect(DB_NAME)
    con.row_factory = sqlite3.Row
    return con


def init_db():
    with connect() as con:

        con.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)

        con.execute("""
        CREATE TABLE IF NOT EXISTS savings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            target REAL NOT NULL,
            saved REAL DEFAULT 0,
            due_date TEXT,
            note TEXT,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
        """)


# =========================
# AUTHENTICATION
# =========================

def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return wrapper


# =========================
# DESIGN
# =========================

BASE = """
<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{ title }}</title>

<style>
* {box-sizing:border-box}

body {
    margin:0;
    font-family:Arial,sans-serif;
    background:#f4f6fb;
    color:#172033;
}

header {
    background:#fff;
    padding:18px 6%;
    display:flex;
    justify-content:space-between;
    align-items:center;
    box-shadow:0 2px 12px #00000008;
}

.logo {
    font-size:23px;
    font-weight:bold;
    color:#2463eb;
}

nav a {
    margin-left:18px;
    text-decoration:none;
    color:#475569;
    font-size:14px;
}

.container {
    max-width:1150px;
    margin:35px auto;
    padding:0 18px;
}

h1 {font-size:27px}
h2 {font-size:20px}

.grid {
    display:grid;
    grid-template-columns:repeat(3,1fr);
    gap:15px;
    margin-bottom:20px;
}

.split {
    display:grid;
    grid-template-columns:1fr 1fr;
    gap:18px;
}

.card {
    background:white;
    padding:23px;
    border-radius:15px;
    box-shadow:0 3px 15px #00000006;
    margin-bottom:16px;
}

.statlabel {
    color:#8490a3;
    font-size:14px;
}

.stat {
    font-size:27px;
    font-weight:bold;
    margin-top:10px;
}

.green {color:#16a36a}

.field {margin-bottom:15px}

label {
    display:block;
    margin-bottom:7px;
    font-size:14px;
}

input {
    width:100%;
    padding:13px;
    border:1px solid #dce2ec;
    border-radius:9px;
    font-size:14px;
}

button {
    padding:12px 17px;
    border:0;
    border-radius:9px;
    cursor:pointer;
    font-weight:bold;
}

.primary {
    background:#2463eb;
    color:white;
}

.danger {
    background:#fff0f0;
    color:#dc3535;
}

.bar {
    height:9px;
    background:#edf0f5;
    border-radius:20px;
    overflow:hidden;
    margin:12px 0;
}

.bar span {
    display:block;
    height:100%;
    background:#16b981;
}

.toolbar {
    display:flex;
    justify-content:space-between;
    align-items:center;
    gap:10px;
}

.pill {
    background:#eaf1ff;
    color:#2463eb;
    padding:6px 10px;
    border-radius:20px;
    font-size:12px;
}

.small {
    color:#8490a3;
    font-size:12px;
    margin-top:8px;
}

.muted {
    color:#8490a3;
}

.flash {
    background:#e9f8ef;
    color:#16834c;
    padding:13px;
    border-radius:9px;
    margin-bottom:15px;
}

.empty {
    color:#8993a5;
    padding:20px 0;
}

.auth {
    max-width:420px;
    margin:70px auto;
}

@media(max-width:700px) {
    .grid {grid-template-columns:1fr}
    .split {grid-template-columns:1fr}
    header {padding:15px}
    nav a {margin-left:8px}
    .logo {font-size:19px}
}
</style>
</head>

<body>

<header>
    <div class="logo">FinTrack</div>

    <nav>
        {% if user %}
            <a href="{{ url_for('savings') }}">Накопления</a>
            <a href="{{ url_for('profile') }}">Профиль</a>
            <a href="{{ url_for('logout') }}">Выйти</a>
        {% else %}
            <a href="{{ url_for('login') }}">Войти</a>
            <a href="{{ url_for('register') }}">Регистрация</a>
        {% endif %}
    </nav>
</header>

<div class="container">

{% with messages = get_flashed_messages() %}
    {% for message in messages %}
        <div class="flash">{{ message }}</div>
    {% endfor %}
{% endwith %}

{{ content|safe }}

</div>

</body>
</html>
"""


def page(title, content, **kwargs):
    return render_template_string(
        BASE,
        title=title,
        content=content,
        user=session.get("username"),
        **kwargs
    )


# =========================
# REGISTER
# =========================

@app.route("/register", methods=["GET", "POST"])
def register():

    if request.method == "POST":

        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        if not username or not email or len(password) < 8:
            flash("Заполните все поля. Пароль минимум 8 символов.")
            return redirect(url_for("register"))

        try:
            with connect() as con:
                con.execute("""
                    INSERT INTO users(username,email,password)
                    VALUES(?,?,?)
                """, (
                    username,
                    email,
                    generate_password_hash(password)
                ))

            flash("Регистрация успешна! Теперь войдите.")
            return redirect(url_for("login"))

        except sqlite3.IntegrityError:
            flash("Этот email уже зарегистрирован.")

    content = """
    <div class="card auth">
        <h1>Создать аккаунт</h1>
        <p class="muted">Присоединяйтесь к FinTrack</p>

        <form method="post">
            <div class="field">
                <label>Ваше имя</label>
                <input name="username" required>
            </div>

            <div class="field">
                <label>Email</label>
                <input name="email" type="email" required>
            </div>

            <div class="field">
                <label>Пароль</label>
                <input name="password" type="password" minlength="8" required>
            </div>

            <button class="primary">Зарегистрироваться</button>
        </form>

        <p>Уже есть аккаунт? <a href="/login">Войти</a></p>
    </div>
    """

    return page("Регистрация", content)


# =========================
# LOGIN
# =========================

@app.route("/login", methods=["GET", "POST"])
def login():

    if request.method == "POST":

        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        with connect() as con:
            user = con.execute(
                "SELECT * FROM users WHERE email=?",
                (email,)
            ).fetchone()

        if user and check_password_hash(user["password"], password):

            session.clear()
            session["user_id"] = user["id"]
            session["username"] = user["username"]

            return redirect(url_for("savings"))

        flash("Неверный email или пароль.")

    content = """
    <div class="card auth">
        <h1>Вход в аккаунт</h1>
        <p class="muted">Рады видеть вас снова!</p>

        <form method="post">
            <div class="field">
                <label>Email</label>
                <input name="email" type="email" required>
            </div>
<div class="field">
                <label>Пароль</label>
                <input name="password" type="password" required>
            </div>

            <button class="primary">Войти</button>
        </form>

        <p>Нет аккаунта? <a href="/register">Регистрация</a></p>
    </div>
    """

    return page("Вход", content)


# =========================
# LOGOUT
# =========================

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# =========================
# PROFILE
# =========================

@app.route("/profile")
@login_required
def profile():

    with connect() as con:
        user = con.execute(
            "SELECT * FROM users WHERE id=?",
            (session["user_id"],)
        ).fetchone()

        count = con.execute(
            "SELECT COUNT(*) FROM savings WHERE user_id=?",
            (session["user_id"],)
        ).fetchone()[0]

    content = f"""
    <h1>Мой профиль</h1>

    <div class="card">
        <h2>👤 {user['username']}</h2>
        <p>Email: {user['email']}</p>
        <p>Количество финансовых целей: {count}</p>
        <p class="muted">Дата регистрации: {user['created_at']}</p>
        <a href="/logout">Выйти из аккаунта</a>
    </div>
    """

    return page("Мой профиль", content)


# =========================
# MONEY FORMAT
# =========================

@app.template_filter("money")
def money(value):
    return f"{float(value):,.0f}".replace(",", " ")


# =========================
# SAVINGS
# =========================

@app.route("/savings", methods=["GET", "POST"])
@login_required
def savings():

    user_id = session["user_id"]

    if request.method == "POST":

        title = request.form.get("title", "").strip()

        try:
            target = float(request.form.get("target", "0"))
            saved = float(request.form.get("saved", "0"))
        except ValueError:
            target = saved = 0

        if title and 0 < target <= 1_000_000_000_000 and 0 <= saved <= target:
            with connect() as con:
                con.execute("""
                    INSERT INTO savings
                    (user_id,title,target,saved,due_date,note)
                    VALUES(?,?,?,?,?,?)
                """, (
                    user_id,
                    title,
                    target,
                    saved,
                    request.form.get("due_date", ""),
                    request.form.get("note", "").strip()
                ))

            flash("Цель накопления создана.")

        else:
            flash("Проверьте название и суммы.")

        return redirect(url_for("savings"))

    with connect() as con:

        rows = con.execute("""
            SELECT * FROM savings
            WHERE user_id=?
            ORDER BY id DESC
        """, (user_id,)).fetchall()

    total = sum(r["saved"] for r in rows)
    left = sum(max(0, r["target"] - r["saved"]) for r in rows)

    content = """
    <h1>Мои накопления</h1>
    <p class="muted">Здравствуйте, {{ username }}! Управляйте своими финансовыми целями.</p>

    <div class="grid">

        <div class="card">
            <div class="statlabel">Всего накоплено</div>
            <div class="stat green">{{ total|money }} сум</div>
        </div>

        <div class="card">
            <div class="statlabel">Количество целей</div>
            <div class="stat">{{ rows|length }}</div>
        </div>

        <div class="card">
            <div class="statlabel">Осталось накопить</div>
            <div class="stat">{{ left|money }} сум</div>
        </div>

    </div>

    <div class="split">

        <div class="card">
            <h2>Новая цель</h2>

            <form method="post">

                <div class="field">
                    <label>На что копим?</label>
                    <input name="title" required placeholder="Например, ноутбук">
                </div>

                <div class="field">
                    <label>Целевая сумма (сум)</label>
                    <input name="target" type="number" min="1" required>
                </div>

                <div class="field">
                    <label>Уже накоплено (сум)</label>
                    <input name="saved" type="number" min="0" value="0">
                </div>

                <div class="field">
                    <label>Желаемый срок</label>
                    <input name="due_date" type="date">
                </div>

                <div class="field">
                    <label>Комментарий</label>
                    <input name="note">
                </div>

                <button class="primary">Создать цель</button>

            </form>
        </div>

        <div class="card">
            <h2>Мои цели</h2>

            {% for s in rows %}

            <div style="padding:15px 0;border-bottom:1px solid #edf0f5">

                <div class="toolbar">
                    <b>{{ s.title }}</b>
                    <span class="pill">
                        {{ ((s.saved/s.target)*100)|round|int }}%
                    </span>
                </div>

                <div class="stat">
                    {{ s.saved|money }}
                    <span class="muted" style="font-size:13px">
                        из {{ s.target|money }} сум
                    </span>
                </div>

                <div class="bar">
                    <span style="width:{{ [100,(s.saved/s.target*100)]|min }}%"></span>
                </div>

                <div class="small">
                    Срок: {{ s.due_date or 'не указан' }}
                    · {{ s.note or '' }}
                </div>

                <form method="post"
                      action="{{ url_for('add_saving', saving_id=s.id) }}"
                      style="display:flex;gap:7px;margin-top:12px">

                    <input name="amount" type="number" min="1"
                           placeholder="Сумма пополнения" required>

                    <button class="primary">Пополнить</button>

                </form>

                <form method="post"
                      action="{{ url_for('delete_saving', saving_id=s.id) }}"
                      style="margin-top:8px"
                      onsubmit="return confirm('Удалить эту цель?')">

                    <button class="danger">Удалить цель</button>

                </form>

            </div>

            {% else %}

            <div class="empty">
                У вас пока нет целей накопления.
            </div>

            {% endfor %}

        </div>

    </div>
    """

    return render_template_string(
        BASE,
        title="Накопления",
        content=render_template_string(
            content,
            rows=rows,
            total=total,
            left=left,
            username=session["username"]
        ),
        user=session["username"]
    )


# =========================
# ADD SAVINGS
# =========================

@app.route("/savings/<int:saving_id>/add", methods=["POST"])
@login_required
def add_saving(saving_id):

    try:
        amount = float(request.form.get("amount", "0"))
    except ValueError:
        amount = 0

    with connect() as con:

        s = con.execute("""
            SELECT * FROM savings
            WHERE id=? AND user_id=?
        """, (saving_id, session["user_id"])).fetchone()

        if s and 0 < amount <= 1_000_000_000_000:
            con.execute("""
                UPDATE savings
                SET saved=MIN(target,saved+?)
                WHERE id=? AND user_id=?
            """, (amount, saving_id, session["user_id"]))

            flash("Сбережения пополнены.")

        else:
            flash("Некорректная сумма или цель не найдена.")

    return redirect(url_for("savings"))


# =========================
# DELETE SAVINGS
# =========================

@app.route("/savings/<int:saving_id>/delete", methods=["POST"])
@login_required
def delete_saving(saving_id):

    with connect() as con:
        con.execute("""
            DELETE FROM savings
            WHERE id=? AND user_id=?
        """, (saving_id, session["user_id"]))

    flash("Цель удалена.")

    return redirect(url_for("savings"))
# =========================
# HOME
# =========================

@app.route("/")
def index():

    if "user_id" in session:
        return redirect(url_for("savings"))

    content = """
    <div class="card" style="text-align:center;padding:55px 20px">
        <h1>Управляйте своими финансами разумно.</h1>
        <p class="muted">
            Создавайте финансовые цели, копите деньги
            и следите за своим прогрессом.
        </p>

        <br>

        <a href="/register">
            <button class="primary">Создать аккаунт</button>
        </a>

        <a href="/login">
            <button>Войти</button>
        </a>
    </div>
    """

    return page("FinTrack", content)


# =========================
# START
# =========================

init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
