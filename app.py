import os
from datetime import datetime, date
from decimal import Decimal, InvalidOperation
from urllib.parse import urlparse

from flask import (
    Flask, render_template_string, request, redirect, url_for,
    flash, session, abort
)
from flask_sqlalchemy import SQLAlchemy
from flask_wtf.csrf import CSRFProtect
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError

# ============================================================
# FinTrack — multi-user personal finance application
# ============================================================

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-only-change-this-secret")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {"pool_pre_ping": True}

database_url = os.environ.get("DATABASE_URL", "sqlite:///fintrack.db")
if database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)
app.config["SQLALCHEMY_DATABASE_URI"] = database_url

# Secure cookies on Render/HTTPS; local development remains usable.
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=bool(os.environ.get("RENDER")),
    PERMANENT_SESSION_LIFETIME=60 * 60 * 24 * 14,
)

db = SQLAlchemy(app)
csrf = CSRFProtect(app)

SUPPORTED_CURRENCIES = {
    "UZS": "Узбекский сум",
    "USD": "Доллар США",
    "EUR": "Евро",
    "RUB": "Российский рубль",
    "KZT": "Казахстанский тенге",
    "TRY": "Турецкая лира",
    "SAR": "Саудовский риял",
    "AED": "Дирхам ОАЭ",
}
TX_TYPES = {"income": "Доход", "expense": "Расход", "transfer": "Перевод"}
MAX_AMOUNT = Decimal("999999999999999")


def D(value):
    """Convert user input to a finite positive Decimal."""
    try:
        value = Decimal(str(value).replace(",", ".").strip())
        if not value.is_finite():
            return None
        return value
    except (InvalidOperation, ValueError, TypeError):
        return None


# ----------------------------- Models -----------------------------

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(60), nullable=False)
    email = db.Column(db.String(254), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class Balance(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True)
    name = db.Column(db.String(80), nullable=False)
    currency = db.Column(db.String(3), nullable=False)
    amount = db.Column(db.Numeric(24, 2), nullable=False, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class Transaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True)
    balance_id = db.Column(db.Integer, db.ForeignKey("balance.id", ondelete="RESTRICT"), nullable=False, index=True)
    target_balance_id = db.Column(db.Integer, db.ForeignKey("balance.id", ondelete="RESTRICT"), nullable=True)
    tx_type = db.Column(db.String(12), nullable=False)
    amount = db.Column(db.Numeric(24, 2), nullable=False)
    category = db.Column(db.String(80), nullable=False, default="Другое")
    description = db.Column(db.String(500), nullable=True)
    tx_date = db.Column(db.Date, nullable=False, default=date.today, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    balance = db.relationship("Balance", foreign_keys=[balance_id])
    target_balance = db.relationship("Balance", foreign_keys=[target_balance_id])


class SavingsGoal(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True)
    title = db.Column(db.String(100), nullable=False)
    currency = db.Column(db.String(3), nullable=False)
    target = db.Column(db.Numeric(24, 2), nullable=False)
    saved = db.Column(db.Numeric(24, 2), nullable=False, default=0)
    due_date = db.Column(db.Date, nullable=True)
    note = db.Column(db.String(500), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


# ----------------------------- Helpers -----------------------------

def current_user():
    uid = session.get("user_id")
    return db.session.get(User, uid) if uid else None


def login_required(view):
    from functools import wraps
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not current_user():
            session.clear()
            flash("Войдите в аккаунт, чтобы продолжить.", "error")
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped


def owned_balance(balance_id, user_id=None):
    user_id = user_id or session.get("user_id")
    return Balance.query.filter_by(id=balance_id, user_id=user_id).first()


def fmt(value):
    try:
        return f"{Decimal(value):,.2f}".replace(",", " ").rstrip("0").rstrip(".")
    except Exception:
        return "0"


app.jinja_env.filters["money"] = fmt


def seed_default_balances(user):
    """Create the two starter wallets once for a newly registered user."""
    db.session.add_all([
        Balance(user_id=user.id, name="Наличные", currency="UZS", amount=Decimal("0")),
        Balance(user_id=user.id, name="Основной счёт", currency="USD", amount=Decimal("0")),
    ])


def commit_or_rollback():
    try:
        db.session.commit()
        return True
    except Exception:
        db.session.rollback()
        raise


# ----------------------------- Shared layout -----------------------------

BASE = r"""
<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{ title }} — FinTrack</title>
<style>
:root{--blue:#315eea;--ink:#172033;--muted:#718096;--bg:#f4f6fb;--line:#e8edf5;--green:#159765;--red:#d94b58}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px Arial,sans-serif}
header{background:#fff;border-bottom:1px solid var(--line);padding:15px max(20px,calc((100% - 1180px)/2));display:flex;align-items:center;justify-content:space-between;gap:16px;flex-wrap:wrap}
.logo{font-size:23px;font-weight:800;color:var(--blue);text-decoration:none;letter-spacing:-.5px}
nav{display:flex;gap:16px;flex-wrap:wrap}nav a{color:#4b5870;text-decoration:none;font-size:14px}nav a:hover{color:var(--blue)}
main{max-width:1180px;margin:30px auto;padding:0 18px}
h1{font-size:28px;margin:0 0 8px}h2{font-size:19px;margin:0 0 17px}h3{font-size:16px;margin:0 0 10px}
.sub{color:var(--muted);margin:0 0 22px}.grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:14px;margin:18px 0}
.cols{display:grid;grid-template-columns: minmax(280px,.85fr) minmax(0,1.5fr);gap:16px}
.card{background:#fff;border:1px solid var(--line);border-radius:16px;padding:21px;box-shadow:0 5px 20px #18294b06;margin-bottom:16px}
.metric-label{font-size:13px;color:var(--muted)}.metric{font-size:25px;font-weight:750;margin-top:9px;overflow-wrap:anywhere}.positive{color:var(--green)}.negative{color:var(--red)}
label{display:block;font-size:13px;font-weight:600;margin:0 0 7px}.field{margin-bottom:14px}
input,select,textarea{width:100%;padding:12px 13px;border:1px solid #d9e0eb;border-radius:10px;background:#fff;color:var(--ink);font:14px Arial}
textarea{min-height:75px;resize:vertical}
button,.btn{display:inline-block;border:0;border-radius:10px;padding:11px 15px;background:var(--blue);color:white;font-weight:700;text-decoration:none;cursor:pointer;font-size:14px}
.btn-light{background:#edf2ff;color:#315eea}.btn-danger{background:#fff0f0;color:#c83c4a}.btn-small{padding:8px 10px;font-size:12px}
.row{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap}
.pill{display:inline-block;background:#edf2ff;color:#315eea;border-radius:30px;padding:5px 9px;font-size:12px}
.muted,.small{color:var(--muted)}.small{font-size:12px}.flash{padding:12px 14px;border-radius:10px;margin:0 0 14px;background:#e9f8ef;color:#147c4d}.flash.error{background:#fff0f0;color:#b83243}
table{width:100%;border-collapse:collapse}th,td{text-align:left;padding:12px 9px;border-bottom:1px solid var(--line);font-size:13px;vertical-align:top}th{color:var(--muted);font-weight:600}
.table-wrap{overflow-x:auto}.amount-in{color:var(--green);font-weight:700}.amount-out{color:var(--red);font-weight:700}
.wallet{display:flex;justify-content:space-between;gap:12px;align-items:center}.wallet-name{font-weight:700}.wallet-amount{font-size:21px;font-weight:750;margin-top:7px}
.progress{height:8px;border-radius:20px;background:#edf0f5;overflow:hidden;margin:10px 0}.progress span{display:block;height:100%;background:#20ae7b}
.auth{max-width:440px;margin:55px auto}.empty{padding:20px 0;color:var(--muted)}
.actions{display:flex;gap:8px;flex-wrap:wrap}.right{text-align:right}
footer{text-align:center;color:#9aa4b4;padding:25px;font-size:12px}
@media(max-width:850px){.grid{grid-template-columns:repeat(2,minmax(0,1fr))}.cols{grid-template-columns:1fr}}
@media(max-width:520px){.grid{grid-template-columns:1fr 1fr}.metric{font-size:19px}main{margin:20px auto}header{padding:14px 18px}nav{gap:11px}}
</style>
</head>
<body>
<header>
<a class="logo" href="{{ url_for('dashboard') if user else url_for('index') }}">FinTrack</a>
<nav>
{% if user %}
<a href="{{ url_for('dashboard') }}">Обзор</a>
<a href="{{ url_for('balances') }}">Мои балансы</a>
<a href="{{ url_for('new_transaction') }}">Операция</a>
<a href="{{ url_for('transactions') }}">История</a>
<a href="{{ url_for('savings') }}">Накопления</a>
<a href="{{ url_for('profile') }}">Профиль</a>
<a href="{{ url_for('logout') }}">Выйти</a>
{% else %}
<a href="{{ url_for('login') }}">Войти</a><a href="{{ url_for('register') }}">Регистрация</a>
{% endif %}
</nav>
</header>
<main>
{% with messages=get_flashed_messages(with_categories=true) %}
{% for category,message in messages %}<div class="flash {{ 'error' if category=='error' else '' }}">{{ message }}</div>{% endfor %}
{% endwith %}
{{ content|safe }}
</main>
<footer>FinTrack · Личные финансы под контролем</footer>
</body></html>
"""


def page(title, content, **context):
    return render_template_string(
        BASE, title=title, content=content, user=current_user(),
        currencies=SUPPORTED_CURRENCIES, **context
    )


# ----------------------------- Public pages -----------------------------

@app.route("/")
def index():
    if current_user():
        return redirect(url_for("dashboard"))
    content = """
    <section class="card" style="padding:55px 28px;text-align:center">
      <span class="pill">Личный финансовый кабинет</span>
      <h1 style="font-size:38px;margin:18px 0 12px">Все деньги. Все счета. Полный контроль.</h1>
      <p class="sub" style="max-width:620px;margin:0 auto 25px">Учитывайте доходы и расходы, ведите несколько балансов в разных валютах, отслеживайте переводы и историю каждой операции.</p>
      <a class="btn" href="{{ url_for('register') }}">Создать аккаунт</a>
      <a class="btn btn-light" href="{{ url_for('login') }}">Войти</a>
    </section>
    <div class="grid">
      <div class="card"><h3>💳 Несколько балансов</h3><p class="muted">Наличные, карта, банковский счёт и другие кошельки.</p></div>
      <div class="card"><h3>💱 Разные валюты</h3><p class="muted">UZS, USD, EUR и другие валюты отдельно.</p></div>
      <div class="card"><h3>📊 Доходы и расходы</h3><p class="muted">Категории, суммы, даты и понятная история.</p></div>
      <div class="card"><h3>🎯 Финансовые цели</h3><p class="muted">Накопления и прогресс по каждой цели.</p></div>
    </div>"""
    return page("Главная", content)


@app.route("/register", methods=["GET", "POST"])
def register():
    if current_user():
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        if not username or len(username) > 60 or "@" not in email or len(email) > 254 or len(password) < 8:
            flash("Проверьте имя и email. Пароль должен содержать минимум 8 символов.", "error")
        else:
            user = User(username=username, email=email, password_hash=generate_password_hash(password))
            db.session.add(user)
            try:
                db.session.flush()
                seed_default_balances(user)
                db.session.commit()
                flash("Аккаунт создан. Войдите, чтобы начать.")
                return redirect(url_for("login"))
            except IntegrityError:
                db.session.rollback()
                flash("Этот email уже зарегистрирован.", "error")
    content = """
    <div class="card auth"><h1>Регистрация</h1><p class="sub">Создайте личный финансовый кабинет.</p>
    <form method="post">
      <div class="field"><label>Имя</label><input name="username" maxlength="60" required></div>
      <div class="field"><label>Email</label><input name="email" type="email" maxlength="254" required></div>
      <div class="field"><label>Пароль (минимум 8 символов)</label><input name="password" type="password" minlength="8" required></div>
      <button>Создать аккаунт</button>
    </form><p class="muted">Уже зарегистрированы? <a href="{{ url_for('login') }}">Войти</a></p></div>"""
    return page("Регистрация", content)


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user():
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = User.query.filter_by(email=email).first()
        if user and check_password_hash(user.password_hash, password):
            session.clear()
            session.permanent = True
            session["user_id"] = user.id
            flash("Вы успешно вошли.")
            return redirect(url_for("dashboard"))
        flash("Неверный email или пароль.", "error")
    content = """
    <div class="card auth"><h1>Вход</h1><p class="sub">Войдите в свой FinTrack.</p>
    <form method="post">
      <div class="field"><label>Email</label><input name="email" type="email" required></div>
      <div class="field"><label>Пароль</label><input name="password" type="password" required></div>
      <button>Войти</button>
    </form><p class="muted">Нет аккаунта? <a href="{{ url_for('register') }}">Зарегистрироваться</a></p></div>"""
    return page("Вход", content)


@app.route("/logout", methods=["GET", "POST"])
def logout():
    session.clear()
    flash("Вы вышли из аккаунта.")
    return redirect(url_for("index"))


# ----------------------------- Dashboard -----------------------------

@app.route("/dashboard")
@login_required
def dashboard():
    uid = session["user_id"]
    balances = Balance.query.filter_by(user_id=uid).order_by(Balance.currency, Balance.name).all()
    recent = Transaction.query.filter_by(user_id=uid).order_by(Transaction.tx_date.desc(), Transaction.id.desc()).limit(8).all()
    goals = SavingsGoal.query.filter_by(user_id=uid).order_by(SavingsGoal.id.desc()).limit(4).all()
    sums = {}
    for b in balances:
        sums[b.currency] = sums.get(b.currency, Decimal("0")) + b.amount
    content = """
    <div class="row"><div><h1>Финансовый обзор</h1><p class="sub">Добро пожаловать, {{ user_name }}. Вот состояние ваших финансов.</p></div><a class="btn" href="{{ url_for('new_transaction') }}">+ Добавить операцию</a></div>
    <div class="grid">
    {% for currency,amount in sums.items() %}
      <div class="card"><div class="metric-label">Общий остаток · {{ currency }}</div><div class="metric">{{ amount|money }} {{ currency }}</div></div>
    {% else %}<div class="card"><p class="muted">Пока нет балансов.</p></div>{% endfor %}
      <div class="card"><div class="metric-label">Балансов</div><div class="metric">{{ balances|length }}</div></div>
      <div class="card"><div class="metric-label">Финансовых целей</div><div class="metric">{{ goals|length }}</div></div>
    </div>
    <div class="cols">
      <section class="card"><div class="row"><h2>Мои балансы</h2><a href="{{ url_for('balances') }}">Все балансы →</a></div>
      {% for b in balances %}<div class="wallet" style="padding:12px 0;border-bottom:1px solid #e8edf5"><div><div class="wallet-name">{{ b.name }}</div><div class="small">{{ b.currency }}</div></div><div class="wallet-amount">{{ b.amount|money }} {{ b.currency }}</div></div>{% else %}<p class="empty">Добавьте первый баланс.</p>{% endfor %}</section>
      <section class="card"><div class="row"><h2>Последние операции</h2><a href="{{ url_for('transactions') }}">Вся история →</a></div>
      {% for t in recent %}<div style="padding:10px 0;border-bottom:1px solid #e8edf5"><div class="row"><b>{{ tx_labels[t.tx_type] }}</b><span class="{{ 'amount-in' if t.tx_type=='income' else 'amount-out' }}">{{ '+' if t.tx_type=='income' else '−' if t.tx_type=='expense' else '↔' }}{{ t.amount|money }} {{ t.balance.currency }}</span></div><div class="small">{{ t.category }} · {{ t.description or 'Без комментария' }} · {{ t.tx_date.strftime('%d.%m.%Y') }}</div></div>{% else %}<p class="empty">Операций пока нет.</p>{% endfor %}</section>
    </div>
    """
    return page("Обзор", content, balances=balances, recent=recent, goals=goals, sums=sums,
                user_name=current_user().username, tx_labels=TX_TYPES)


# ----------------------------- Balances -----------------------------

@app.route("/balances", methods=["GET", "POST"])
@login_required
def balances():
    uid = session["user_id"]
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        currency = request.form.get("currency", "").upper()
        opening = D(request.form.get("opening", "0"))
        if not name or len(name) > 80 or currency not in SUPPORTED_CURRENCIES or opening is None or opening < 0 or opening > MAX_AMOUNT:
            flash("Проверьте название, валюту и начальный остаток.", "error")
        else:
            db.session.add(Balance(user_id=uid, name=name, currency=currency, amount=opening))
            db.session.commit()
            flash("Баланс создан.")
        return redirect(url_for("balances"))
    items = Balance.query.filter_by(user_id=uid).order_by(Balance.currency, Balance.name).all()
    content = """
    <h1>Мои балансы</h1><p class="sub">Создавайте отдельные кошельки, карты и счета. Остатки разных валют не смешиваются.</p>
    <div class="cols">
      <section class="card"><h2>Добавить баланс</h2>
      <form method="post">
        <div class="field"><label>Название баланса</label><input name="name" maxlength="80" placeholder="Например, Карта Uzcard" required></div>
        <div class="field"><label>Валюта</label><select name="currency">{% for code,label in currencies.items() %}<option value="{{ code }}">{{ code }} — {{ label }}</option>{% endfor %}</select></div>
        <div class="field"><label>Начальный остаток</label><input name="opening" type="number" min="0" step="0.01" value="0" required></div>
        <button>Создать баланс</button>
      </form></section>
      <section class="card"><h2>Все балансы</h2>
      {% for b in items %}
        <div class="wallet" style="padding:14px 0;border-bottom:1px solid #e8edf5"><div><div class="wallet-name">{{ b.name }}</div><span class="pill">{{ b.currency }}</span></div><div class="right"><div class="wallet-amount">{{ b.amount|money }}</div><div class="small">{{ b.currency }}</div></div></div>
        <div class="actions" style="margin:8px 0 14px"><a class="btn btn-light btn-small" href="{{ url_for('new_transaction', balance_id=b.id) }}">Операция</a>
        <form method="post" action="{{ url_for('delete_balance', balance_id=b.id) }}" onsubmit="return confirm('Удалить баланс? Это возможно только если по нему нет истории операций.')"><input type="hidden" name="csrf_token" value="{{ csrf_token() }}"><button class="btn-danger btn-small">Удалить</button></form></div>
      {% else %}<p class="empty">Балансов пока нет.</p>{% endfor %}
      </section>
    </div>"""
    return page("Мои балансы", content, items=items)


@app.route("/balances/<int:balance_id>/delete", methods=["POST"])
@login_required
def delete_balance(balance_id):
    b = owned_balance(balance_id)
    if not b:
        abort(404)
    has_tx = Transaction.query.filter(or_(Transaction.balance_id == b.id, Transaction.target_balance_id == b.id)).first()
    if has_tx:
        flash("Нельзя удалить баланс с историей операций. История нужна для финансового учёта.", "error")
    else:
        db.session.delete(b)
        db.session.commit()
        flash("Баланс удалён.")
    return redirect(url_for("balances"))


# ----------------------------- Transactions -----------------------------

@app.route("/transactions/new", methods=["GET", "POST"])
@login_required
def new_transaction():
    uid = session["user_id"]
    balances = Balance.query.filter_by(user_id=uid).order_by(Balance.name).all()
    if not balances:
        flash("Сначала создайте баланс.", "error")
        return redirect(url_for("balances"))

    if request.method == "POST":
        tx_type = request.form.get("tx_type", "")
        balance_id = request.form.get("balance_id", type=int)
        target_id = request.form.get("target_balance_id", type=int)
        amount = D(request.form.get("amount", ""))
        category = request.form.get("category", "Другое").strip()[:80] or "Другое"
        description = request.form.get("description", "").strip()[:500]
        raw_date = request.form.get("tx_date", "")
        try:
            tx_date = datetime.strptime(raw_date, "%Y-%m-%d").date() if raw_date else date.today()
        except ValueError:
            tx_date = None

        source = owned_balance(balance_id, uid) if balance_id else None
        target = owned_balance(target_id, uid) if target_id else None

        if tx_type not in TX_TYPES or not source or amount is None or amount <= 0 or amount > MAX_AMOUNT or not tx_date:
            flash("Проверьте тип операции, баланс, сумму и дату.", "error")
        elif tx_type == "transfer":
            if not target or target.id == source.id:
                flash("Выберите другой баланс для перевода.", "error")
            elif target.currency != source.currency:
                flash("Перевод между разными валютами пока не поддерживается. Создайте операцию обмена отдельно; автоматическая конвертация не выполняется.", "error")
            elif source.amount < amount:
                flash("Недостаточно средств на исходном балансе.", "error")
            else:
                source.amount -= amount
                target.amount += amount
                db.session.add(Transaction(user_id=uid, balance_id=source.id, target_balance_id=target.id,
                                           tx_type="transfer", amount=amount, category="Перевод",
                                           description=description, tx_date=tx_date))
                db.session.commit()
                flash("Перевод выполнен. Остатки обоих балансов обновлены.")
                return redirect(url_for("transactions"))
        else:
            if tx_type == "expense" and source.amount < amount:
                flash("Недостаточно средств на выбранном балансе.", "error")
            else:
                if tx_type == "income":
                    source.amount += amount
                else:
                    source.amount -= amount
                db.session.add(Transaction(user_id=uid, balance_id=source.id, tx_type=tx_type,
                                           amount=amount, category=category, description=description,
                                           tx_date=tx_date))
                db.session.commit()
                flash("Операция сохранена, баланс обновлён.")
                return redirect(url_for("transactions"))

    content = """
    <div class="card" style="max-width:700px;margin:auto"><h1>Новая операция</h1><p class="sub">Доход увеличивает остаток, расход уменьшает, перевод перемещает деньги между вашими балансами.</p>
    <form method="post" id="txform">
      <div class="field"><label>Тип операции</label><select name="tx_type" id="tx_type" onchange="toggleTransfer()"><option value="expense">Расход</option><option value="income">Доход</option><option value="transfer">Перевод между балансами</option></select></div>
      <div class="field"><label>С какого баланса</label><select name="balance_id" required>{% for b in balances %}<option value="{{ b.id }}" {% if selected_id==b.id %}selected{% endif %}>{{ b.name }} · {{ b.currency }} · остаток {{ b.amount|money }}</option>{% endfor %}</select></div>
      <div class="field" id="target_wrap" style="display:none"><label>На какой баланс</label><select name="target_balance_id"><option value="">Выберите баланс</option>{% for b in balances %}<option value="{{ b.id }}">{{ b.name }} · {{ b.currency }}</option>{% endfor %}</select><p class="small">Переводы доступны между балансами одной валюты.</p></div>
      <div class="field"><label>Сумма</label><input name="amount" type="number" min="0.01" step="0.01" required></div>
      <div class="field" id="category_wrap"><label>Категория</label><select name="category">{% for c in categories %}<option>{{ c }}</option>{% endfor %}</select></div>
      <div class="field"><label>Дата</label><input name="tx_date" type="date" value="{{ today }}" required></div>
      <div class="field"><label>Комментарий / на что потратили</label><textarea name="description" maxlength="500" placeholder="Например: продукты, кафе, зарплата..."></textarea></div>
      <button>Сохранить операцию</button> <a class="btn btn-light" href="{{ url_for('transactions') }}">Отмена</a>
    </form></div>
    <script>
    function toggleTransfer(){
      const transfer=document.getElementById('tx_type').value==='transfer';
      document.getElementById('target_wrap').style.display=transfer?'block':'none';
      document.getElementById('category_wrap').style.display=transfer?'none':'block';
    }toggleTransfer();
    </script>"""
    return page("Новая операция", content, balances=balances, today=date.today().isoformat(),
                selected_id=request.args.get("balance_id", type=int),
                categories=["Продукты", "Транспорт", "Дом и коммунальные услуги", "Здоровье", "Одежда", "Кафе и рестораны", "Покупки", "Развлечения", "Образование", "Зарплата", "Бизнес", "Подарки", "Другое"])


@app.route("/transactions")
@login_required
def transactions():
    uid = session["user_id"]
    query = Transaction.query.filter_by(user_id=uid)
    kind = request.args.get("type", "")
    if kind in TX_TYPES:
        query = query.filter_by(tx_type=kind)
    selected_balance = request.args.get("balance", type=int)
    if selected_balance:
        b = owned_balance(selected_balance, uid)
        if b:
            query = query.filter(or_(Transaction.balance_id == b.id, Transaction.target_balance_id == b.id))
    items = query.order_by(Transaction.tx_date.desc(), Transaction.id.desc()).limit(500).all()
    balances = Balance.query.filter_by(user_id=uid).order_by(Balance.name).all()
    content = """
    <div class="row"><div><h1>История операций</h1><p class="sub">Все ваши доходы, расходы и переводы. Показаны последние 500 записей.</p></div><a class="btn" href="{{ url_for('new_transaction') }}">+ Операция</a></div>
    <div class="card">
      <form method="get" class="row" style="margin-bottom:12px">
        <select name="type" style="max-width:220px"><option value="">Все типы</option>{% for k,v in labels.items() %}<option value="{{ k }}" {% if selected_type==k %}selected{% endif %}>{{ v }}</option>{% endfor %}</select>
        <select name="balance" style="max-width:260px"><option value="">Все балансы</option>{% for b in balances %}<option value="{{ b.id }}" {% if selected_balance==b.id %}selected{% endif %}>{{ b.name }} · {{ b.currency }}</option>{% endfor %}</select>
        <button class="btn-light">Фильтровать</button><a class="btn btn-light" href="{{ url_for('transactions') }}">Сбросить</a>
      </form>
      <div class="table-wrap"><table><thead><tr><th>Дата</th><th>Тип</th><th>Категория / описание</th><th>Баланс</th><th>Сумма</th><th></th></tr></thead><tbody>
      {% for t in items %}
      <tr>
        <td>{{ t.tx_date.strftime('%d.%m.%Y') }}</td>
        <td>{{ labels[t.tx_type] }}</td>
        <td><b>{{ t.category }}</b><br><span class="small">{{ t.description or '' }}</span>{% if t.target_balance %}<br><span class="small">→ {{ t.target_balance.name }}</span>{% endif %}</td>
        <td>{{ t.balance.name }}<br><span class="small">{{ t.balance.currency }}</span></td>
        <td class="{{ 'amount-in' if t.tx_type=='income' else 'amount-out' }}">{{ '+' if t.tx_type=='income' else '−' if t.tx_type=='expense' else '↔' }}{{ t.amount|money }} {{ t.balance.currency }}</td>
        <td><form method="post" action="{{ url_for('delete_transaction', tx_id=t.id) }}" onsubmit="return confirm('Удалить операцию и пересчитать баланс?')"><input type="hidden" name="csrf_token" value="{{ csrf_token() }}"><button class="btn-danger btn-small">Удалить</button></form></td>
      </tr>
      {% else %}<tr><td colspan="6" class="empty">Операций по выбранному фильтру нет.</td></tr>{% endfor %}
      </tbody></table></div>
    </div>"""
    return page("История операций", content, items=items, balances=balances, labels=TX_TYPES,
                selected_type=kind, selected_balance=selected_balance)


@app.route("/transactions/<int:tx_id>/delete", methods=["POST"])
@login_required
def delete_transaction(tx_id):
    tx = Transaction.query.filter_by(id=tx_id, user_id=session["user_id"]).first_or_404()
    source = owned_balance(tx.balance_id)
    target = owned_balance(tx.target_balance_id) if tx.target_balance_id else None

    # Reverse the original effect before removing the ledger record.
    if tx.tx_type == "income":
        if not source or source.amount < tx.amount:
            flash("Нельзя удалить доход: на балансе уже недостаточно средств для обратного пересчёта.", "error")
            return redirect(url_for("transactions"))
        source.amount -= tx.amount
    elif tx.tx_type == "expense":
        if source:
            source.amount += tx.amount
    elif tx.tx_type == "transfer":
        if not source or not target or target.amount < tx.amount:
            flash("Нельзя отменить перевод: на целевом балансе недостаточно средств.", "error")
            return redirect(url_for("transactions"))
        target.amount -= tx.amount
        source.amount += tx.amount

    db.session.delete(tx)
    db.session.commit()
    flash("Операция удалена, остаток пересчитан.")
    return redirect(url_for("transactions"))


# ----------------------------- Savings goals -----------------------------

@app.route("/savings", methods=["GET", "POST"])
@login_required
def savings():
    uid = session["user_id"]
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        currency = request.form.get("currency", "").upper()
        target = D(request.form.get("target", ""))
        saved = D(request.form.get("saved", "0"))
        raw_due = request.form.get("due_date", "")
        try:
            due = datetime.strptime(raw_due, "%Y-%m-%d").date() if raw_due else None
        except ValueError:
            due = None
        if not title or len(title) > 100 or currency not in SUPPORTED_CURRENCIES or target is None or saved is None or target <= 0 or saved < 0 or saved > target or target > MAX_AMOUNT:
            flash("Проверьте название, валюту и суммы цели.", "error")
        else:
            db.session.add(SavingsGoal(user_id=uid, title=title, currency=currency, target=target,
                                       saved=saved, due_date=due, note=request.form.get("note", "").strip()[:500]))
            db.session.commit()
            flash("Финансовая цель создана.")
        return redirect(url_for("savings"))
    goals = SavingsGoal.query.filter_by(user_id=uid).order_by(SavingsGoal.id.desc()).all()
    content = """
    <h1>Финансовые цели</h1><p class="sub">Отслеживайте прогресс накоплений. Цели ведутся отдельно от фактических остатков на счетах.</p>
    <div class="cols">
      <section class="card"><h2>Новая цель</h2><form method="post">
        <div class="field"><label>Название цели</label><input name="title" maxlength="100" placeholder="Например, отпуск" required></div>
        <div class="field"><label>Валюта цели</label><select name="currency">{% for code,label in currencies.items() %}<option value="{{ code }}">{{ code }} — {{ label }}</option>{% endfor %}</select></div>
        <div class="field"><label>Нужная сумма</label><input name="target" type="number" min="0.01" step="0.01" required></div>
        <div class="field"><label>Уже накоплено</label><input name="saved" type="number" min="0" step="0.01" value="0"></div>
        <div class="field"><label>Желаемый срок</label><input name="due_date" type="date"></div>
        <div class="field"><label>Комментарий</label><input name="note" maxlength="500"></div><button>Создать цель</button>
      </form></section>
      <section class="card"><h2>Мои цели</h2>
      {% for g in goals %}<div style="padding:14px 0;border-bottom:1px solid #e8edf5">
        <div class="row"><b>{{ g.title }}</b><span class="pill">{{ ((g.saved/g.target)*100)|round|int }}%</span></div>
        <div class="metric">{{ g.saved|money }} <span class="small">из {{ g.target|money }} {{ g.currency }}</span></div>
        <div class="progress"><span style="width:{{ [100,(g.saved/g.target*100)]|min }}%"></span></div>
        <div class="small">Срок: {{ g.due_date.strftime('%d.%m.%Y') if g.due_date else 'не указан' }} · {{ g.note or '' }}</div>
        <form method="post" action="{{ url_for('update_goal', goal_id=g.id) }}" class="row" style="margin-top:10px">
          <input name="saved" type="number" min="0" max="{{ g.target }}" step="0.01" value="{{ g.saved }}" required style="max-width:180px">
          <button class="btn-light btn-small">Обновить накопленное</button>
        </form>
        <form method="post" action="{{ url_for('delete_goal', goal_id=g.id) }}" onsubmit="return confirm('Удалить цель?')" style="margin-top:7px"><button class="btn-danger btn-small">Удалить цель</button></form>
      </div>{% else %}<p class="empty">Целей пока нет. Создайте первую.</p>{% endfor %}
      </section>
    </div>"""
    return page("Накопления", content, goals=goals)


@app.route("/savings/<int:goal_id>/update", methods=["POST"])
@login_required
def update_goal(goal_id):
    goal = SavingsGoal.query.filter_by(id=goal_id, user_id=session["user_id"]).first_or_404()
    saved = D(request.form.get("saved", ""))
    if saved is None or saved < 0 or saved > goal.target:
        flash("Сумма должна быть от нуля до целевой суммы.", "error")
    else:
        goal.saved = saved
        db.session.commit()
        flash("Прогресс цели обновлён.")
    return redirect(url_for("savings"))


@app.route("/savings/<int:goal_id>/delete", methods=["POST"])
@login_required
def delete_goal(goal_id):
    goal = SavingsGoal.query.filter_by(id=goal_id, user_id=session["user_id"]).first_or_404()
    db.session.delete(goal)
    db.session.commit()
    flash("Цель удалена.")
    return redirect(url_for("savings"))


# ----------------------------- Profile -----------------------------

@app.route("/profile")
@login_required
def profile():
    user = current_user()
    balance_count = Balance.query.filter_by(user_id=user.id).count()
    tx_count = Transaction.query.filter_by(user_id=user.id).count()
    goal_count = SavingsGoal.query.filter_by(user_id=user.id).count()
    content = """
    <h1>Мой профиль</h1><div class="card" style="max-width:650px">
      <h2>{{ user.username }}</h2><p>{{ user.email }}</p>
      <p class="muted">Зарегистрирован: {{ user.created_at.strftime('%d.%m.%Y') }}</p>
      <div class="grid"><div><div class="metric">{{ balance_count }}</div><div class="small">Балансов</div></div>
      <div><div class="metric">{{ tx_count }}</div><div class="small">Операций</div></div>
      <div><div class="metric">{{ goal_count }}</div><div class="small">Целей</div></div></div>
      <p class="small">Ваши финансовые данные доступны только после входа в ваш аккаунт.</p>
    </div>"""
    return page("Профиль", content, user=user, balance_count=balance_count, tx_count=tx_count, goal_count=goal_count)


# ----------------------------- Error pages / startup -----------------------------

@app.errorhandler(404)
def not_found(error):
    return page("Не найдено", '<div class="card"><h1>404</h1><p>Страница не найдена.</p><a href="/">На главную</a></div>'), 404


@app.errorhandler(500)
def server_error(error):
    db.session.rollback()
    return page("Ошибка", '<div class="card"><h1>Ошибка сервера</h1><p>Произошла внутренняя ошибка. Попробуйте ещё раз.</p><a href="/">На главную</a></div>'), 500


with app.app_context():
    db.create_all()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=False)
