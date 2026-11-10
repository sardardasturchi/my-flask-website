from flask import Flask, request, redirect, url_for, render_template_string, flash
import sqlite3
from datetime import date
from pathlib import Path

BASE = Path(__file__).resolve().parent
DB_PATH = BASE / "finance.db"
app = Flask(__name__)
app.secret_key = "replace-this-secret-key"

app.config["TEMPLATES_AUTO_RELOAD"] = True

DEFAULT_CATEGORIES = {
    "expense": ["Еда", "Транспорт", "Покупки", "Жильё", "Здоровье", "Развлечения", "Связь и интернет", "Образование", "Подарки", "Другое"],
    "income": ["Зарплата", "Подработка", "Бизнес", "Подарок", "Инвестиции", "Другое"]
}

def connect():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con

def init_db():
    with connect() as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            kind TEXT NOT NULL CHECK(kind IN ('expense','income')),
            category TEXT NOT NULL,
            amount REAL NOT NULL,
            tx_date TEXT NOT NULL,
            account TEXT DEFAULT 'Наличные',
            note TEXT DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            kind TEXT NOT NULL CHECK(kind IN ('expense','income')),
            UNIQUE(name, kind)
        );
        CREATE TABLE IF NOT EXISTS debts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            direction TEXT NOT NULL CHECK(direction IN ('i_owe','owed_to_me')),
            person TEXT NOT NULL,
            amount REAL NOT NULL,
            remaining REAL NOT NULL,
            due_date TEXT DEFAULT '',
            note TEXT DEFAULT '',
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS savings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            target REAL NOT NULL,
            saved REAL NOT NULL DEFAULT 0,
            due_date TEXT DEFAULT '',
            note TEXT DEFAULT ''
        );
        """)
        for kind, names in DEFAULT_CATEGORIES.items():
            for name in names:
                con.execute("INSERT OR IGNORE INTO categories(name,kind) VALUES(?,?)", (name, kind))

BASE_STYLE = r"""
<style>
:root{--bg:#f4f6fa;--card:#fff;--ink:#172033;--muted:#7c8799;--line:#e8edf3;--navy:#17243b;--blue:#5869e8;--green:#159b72;--red:#df5965}
*{box-sizing:border-box}body{margin:0;background:var(--bg);font-family:Inter,Segoe UI,Arial,sans-serif;color:var(--ink)}
header{background:var(--navy);color:white;padding:19px max(20px,calc((100% - 1200px)/2));display:flex;align-items:center;justify-content:space-between}
.brand{font-weight:850;font-size:21px;letter-spacing:.4px}.brand span{color:#9eacff}.headnote{font-size:12px;color:#c4cede}
nav{background:#fff;border-bottom:1px solid var(--line);padding:0 max(12px,calc((100% - 1200px)/2));display:flex;gap:4px;overflow-x:auto}
nav a{padding:15px 13px;text-decoration:none;color:#697589;font-size:13px;font-weight:700;white-space:nowrap;border-bottom:3px solid transparent}
nav a.active{color:var(--blue);border-color:var(--blue)}
main{max-width:1200px;margin:27px auto;padding:0 20px}h1{font-size:27px;margin:0 0 6px}h2{font-size:17px;margin:0 0 17px}.sub{color:var(--muted);margin-bottom:22px;font-size:14px}
.card{background:var(--card);border:1px solid var(--line);border-radius:17px;padding:20px;box-shadow:0 5px 18px #1c2b4408}
.grid{display:grid;grid-template-columns:repeat(3,1fr);gap:15px;margin-bottom:18px}.statlabel{font-size:12px;color:var(--muted);margin-bottom:10px}.stat{font-size:25px;font-weight:850}.green{color:var(--green)}.red{color:var(--red)}
.split{display:grid;grid-template-columns:350px 1fr;gap:17px;align-items:start}.field{margin-bottom:13px}label{display:block;font-size:12px;font-weight:700;color:#5d687b;margin-bottom:7px}
input,select,textarea{width:100%;border:1px solid #dfe5ed;border-radius:10px;padding:11px 12px;font-size:14px;background:#fff;color:var(--ink);outline:none}textarea{min-height:70px;resize:vertical}
input:focus,select:focus,textarea:focus{border-color:var(--blue);box-shadow:0 0 0 3px #5869e81c}
button,.btn{border:0;border-radius:10px;background:var(--navy);color:white;padding:11px 15px;font-size:13px;font-weight:750;cursor:pointer;text-decoration:none;display:inline-block}
button.primary{background:var(--blue)}button.danger{background:#fff0f1;color:var(--red);padding:8px 10px}
table{width:100%;border-collapse:collapse}th{text-align:left;color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.4px;padding:12px 9px;border-bottom:1px solid var(--line)}td{padding:13px 9px;border-bottom:1px solid #f0f2f6;font-size:13px}tr:last-child td{border-bottom:0}
.amount{font-weight:800;white-space:nowrap}.amount.exp{color:var(--red)}.amount.inc{color:var(--green)}.muted{color:var(--muted)}.small{font-size:11px;color:var(--muted);margin-top:3px}
.flash{background:#eaf8f3;color:#167957;border-radius:10px;padding:11px 14px;margin-bottom:15px;font-size:13px}.empty{text-align:center;color:var(--muted);padding:32px}
.bar{height:8px;border-radius:9px;background:#edf0f5;overflow:hidden;margin:10px 0}.bar>span{display:block;height:100%;background:var(--blue);border-radius:9px}
.actions{display:flex;gap:6px;align-items:center}.toolbar{display:flex;justify-content:space-between;align-items:center;gap:10px;margin-bottom:13px;flex-wrap:wrap}
.pill{display:inline-block;padding:5px 8px;border-radius:20px;background:#f1f3f7;color:#657087;font-size:11px}
@media(max-width:820px){.split{grid-template-columns:1fr}.grid{grid-template-columns:1fr}.headnote{display:none}main{margin-top:20px}.tablewrap{overflow-x:auto}table{min-width:650px}}
</style>
"""

LAYOUT = r"""
<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>{{ title }} — MYFINANCE</title>""" + BASE_STYLE + r"""</head>
<body><header><div class="brand">MY<span>FINANCE</span></div><div class="headnote">Личный финансовый кабинет · {{ today }}</div></header>
<nav>
{% for key,label in nav %}<a href="{{ url_for(key) }}" class="{{ 'active' if active==key else '' }}">{{ label }}</a>{% endfor %}
</nav><main>
{% with msgs=get_flashed_messages() %}{% if msgs %}<div class="flash">{{ msgs[0] }}</div>{% endif %}{% endwith %}
<h1>{{ title }}</h1><div class="sub">{{ subtitle }}</div>
{{ content|safe }}
</main></body></html>
"""

NAV = [
    ("dashboard", "Обзор"), ("transactions", "Доходы и расходы"),
    ("categories_page", "Категории"), ("debts", "Долги"),
    ("savings", "Сбережения")
]

def page(active, title, subtitle, content, **kwargs):
    return render_template_string(LAYOUT, active=active, title=title, subtitle=subtitle,
        content=render_template_string(content, **kwargs), nav=NAV, today=date.today().strftime("%d.%m.%Y"))

@app.template_filter("money")
def money(v):
    return f"{float(v or 0):,.0f}".replace(",", " ")

@app.route("/")
def dashboard():
    with connect() as con:
        rows = con.execute("SELECT kind,COALESCE(SUM(amount),0) total FROM transactions GROUP BY kind").fetchall()
        recent = con.execute("SELECT * FROM transactions ORDER BY tx_date DESC,id DESC LIMIT 7").fetchall()
        debt_out = con.execute("SELECT COALESCE(SUM(remaining),0) FROM debts WHERE direction='i_owe'").fetchone()[0]
        debt_in = con.execute("SELECT COALESCE(SUM(remaining),0) FROM debts WHERE direction='owed_to_me'").fetchone()[0]
        saved = con.execute("SELECT COALESCE(SUM(saved),0) FROM savings").fetchone()[0]
    totals = {r["kind"]:r["total"] for r in rows}
    inc, exp = totals.get("income",0), totals.get("expense",0)
    content = r"""
    <div class="grid">
      <div class="card"><div class="statlabel">Общий баланс</div><div class="stat">{{ (inc-exp)|money }} сум</div></div>
      <div class="card"><div class="statlabel">Все доходы</div><div class="stat green">+ {{ inc|money }} сум</div></div>
      <div class="card"><div class="statlabel">Все расходы</div><div class="stat red">− {{ exp|money }} сум</div></div>
      <div class="card"><div class="statlabel">Я должен</div><div class="stat">{{ debt_out|money }} сум</div></div>
      <div class="card"><div class="statlabel">Мне должны</div><div class="stat">{{ debt_in|money }} сум</div></div>
      <div class="card"><div class="statlabel">В сбережениях</div><div class="stat">{{ saved|money }} сум</div></div>
    </div>
    <div class="card"><div class="toolbar"><h2>Последние операции</h2><a class="btn" href="{{ url_for('transactions') }}">Все операции</a></div>
    <div class="tablewrap"><table><tr><th>Категория</th><th>Дата</th><th>Тип</th><th>Сумма</th></tr>
    {% for x in recent %}<tr><td><b>{{ x.category }}</b><div class="small">{{ x.note }}</div></td><td>{{ x.tx_date }}</td><td>{{ 'Расход' if x.kind=='expense' else 'Доход' }}</td><td class="amount {{ 'exp' if x.kind=='expense' else 'inc' }}">{{ '-' if x.kind=='expense' else '+' }}{{ x.amount|money }}</td></tr>{% else %}<tr><td colspan="4" class="empty">Пока нет операций</td></tr>{% endfor %}</table></div></div>
    """
    return page("dashboard","Финансовый обзор","Вся ваша финансовая картина в одном месте.",content,
                inc=inc,exp=exp,debt_out=debt_out,debt_in=debt_in,saved=saved,recent=recent)

@app.route("/transactions")
def transactions():
    kind = request.args.get("kind","all")
    where,params=[],[]
    if kind in ("income","expense"):
        where.append("kind=?");params.append(kind)
    clause=(" WHERE "+" AND ".join(where)) if where else ""
    with connect() as con:
        rows=con.execute("SELECT * FROM transactions"+clause+" ORDER BY tx_date DESC,id DESC",params).fetchall()
        cats=con.execute("SELECT * FROM categories ORDER BY kind,name").fetchall()
    content=r"""
    <div class="split"><div class="card"><h2>{{ 'Изменить операцию' if edit else 'Добавить операцию' }}</h2>
    <form method="post" action="{{ url_for('save_transaction', item_id=edit.id) if edit else url_for('add_transaction') }}">
    <div class="field"><label>Тип</label><select name="kind" id="kind" onchange="filterCats()"><option value="expense" {{ 'selected' if not edit or edit.kind=='expense' else '' }}>Расход</option><option value="income" {{ 'selected' if edit and edit.kind=='income' else '' }}>Доход</option></select></div>
    <div class="field"><label>Категория</label><select name="category" id="category">{% for c in cats %}<option data-kind="{{ c.kind }}" value="{{ c.name }}" {{ 'selected' if edit and edit.category==c.name else '' }}>{{ c.name }}</option>{% endfor %}</select></div>
    <div class="field"><label>Сумма (сум)</label><input name="amount" type="number" min="1" step="1" required value="{{ edit.amount if edit else '' }}" placeholder="Например, 50000"></div>
    <div class="field"><label>Дата</label><input name="tx_date" type="date" required value="{{ edit.tx_date if edit else today_iso }}"></div>
    <div class="field"><label>Счёт / кошелёк</label><input name="account" value="{{ edit.account if edit else 'Наличные' }}" placeholder="Наличные, карта..."></div>
    <div class="field"><label>Комментарий</label><input name="note" value="{{ edit.note if edit else '' }}" maxlength="180"></div>
    <button class="primary" type="submit">{{ 'Сохранить изменения' if edit else 'Добавить' }}</button>{% if edit %} <a class="btn" href="{{ url_for('transactions') }}">Отмена</a>{% endif %}
    </form></div>
    <div class="card"><div class="toolbar"><h2>История операций</h2><form><select name="kind" onchange="this.form.submit()"><option value="all">Все операции</option><option value="expense" {{ 'selected' if kind=='expense' else '' }}>Расходы</option><option value="income" {{ 'selected' if kind=='income' else '' }}>Доходы</option></select></form></div>
    <div class="tablewrap"><table><tr><th>Операция</th><th>Дата</th><th>Счёт</th><th>Сумма</th><th>Действия</th></tr>
    {% for x in rows %}<tr><td><b>{{ x.category }}</b><div class="small">{{ x.note }}</div><span class="pill">{{ 'Расход' if x.kind=='expense' else 'Доход' }}</span></td><td>{{ x.tx_date }}</td><td>{{ x.account }}</td><td class="amount {{ 'exp' if x.kind=='expense' else 'inc' }}">{{ '-' if x.kind=='expense' else '+' }}{{ x.amount|money }}</td><td><div class="actions"><a class="btn" href="{{ url_for('transactions',edit=x.id) }}">Изменить</a><form method="post" action="{{ url_for('delete_transaction',item_id=x.id) }}" onsubmit="return confirm('Удалить операцию?')"><button class="danger">Удалить</button></form></div></td></tr>{% else %}<tr><td colspan="5" class="empty">Операций пока нет</td></tr>{% endfor %}</table></div></div></div>
    <script>function filterCats(){let k=document.getElementById('kind').value;let s=document.getElementById('category');for(let o of s.options){o.hidden=o.dataset.kind!==k;}if(s.selectedOptions[0]?.hidden){let first=[...s.options].find(o=>!o.hidden);if(first)s.value=first.value;}}filterCats();</script>
    """
    edit_id=request.args.get("edit",type=int)
    edit=next((r for r in rows if r["id"]==edit_id),None) if edit_id else None
    return page("transactions","Доходы и расходы","Добавляйте, редактируйте и удаляйте финансовые операции.",content,
                rows=rows,cats=cats,edit=edit,kind=kind,today_iso=date.today().isoformat())

@app.route("/transactions/add",methods=["POST"])
def add_transaction():
    save_tx(None);return redirect(url_for("transactions"))

@app.route("/transactions/<int:item_id>/save",methods=["POST"])
def save_transaction(item_id):
    save_tx(item_id);return redirect(url_for("transactions"))

def save_tx(item_id):
    kind=request.form.get("kind");category=request.form.get("category","").strip()
    try: amount=float(request.form.get("amount","0"))
    except ValueError: amount=0
    tx_date=request.form.get("tx_date","")
    with connect() as con:
        valid=con.execute("SELECT 1 FROM categories WHERE name=? AND kind=?",(category,kind)).fetchone()
        if kind not in ("income","expense") or not valid or amount<=0 or not tx_date:
            flash("Проверьте тип, категорию, сумму и дату.");return
        vals=(kind,category,amount,tx_date,request.form.get("account","Наличные").strip(),request.form.get("note","").strip())
        if item_id: con.execute("UPDATE transactions SET kind=?,category=?,amount=?,tx_date=?,account=?,note=? WHERE id=?",(*vals,item_id));flash("Операция изменена.")
        else: con.execute("INSERT INTO transactions(kind,category,amount,tx_date,account,note) VALUES(?,?,?,?,?,?)",vals);flash("Операция добавлена.")

@app.route("/transactions/<int:item_id>/delete",methods=["POST"])
def delete_transaction(item_id):
    with connect() as con: con.execute("DELETE FROM transactions WHERE id=?",(item_id,))
    flash("Операция удалена.");return redirect(url_for("transactions"))

@app.route("/categories",methods=["GET","POST"])
def categories_page():
    if request.method=="POST":
        name=request.form.get("name","").strip();kind=request.form.get("kind")
        if name and kind in ("expense","income"):
            try:
                with connect() as con: con.execute("INSERT INTO categories(name,kind) VALUES(?,?)",(name,kind))
                flash("Категория добавлена.")
            except sqlite3.IntegrityError: flash("Такая категория уже существует.")
        return redirect(url_for("categories_page"))
    with connect() as con: cats=con.execute("SELECT * FROM categories ORDER BY kind,name").fetchall()
    content=r"""
    <div class="split"><div class="card"><h2>Новая категория</h2><form method="post"><div class="field"><label>Название</label><input name="name" required maxlength="50" placeholder="Например, Кафе"></div><div class="field"><label>Для чего?</label><select name="kind"><option value="expense">Расход</option><option value="income">Доход</option></select></div><button class="primary">Добавить категорию</button></form></div>
    <div class="card"><h2>Мои категории</h2><div class="tablewrap"><table><tr><th>Название</th><th>Тип</th><th></th></tr>{% for c in cats %}<tr><td><b>{{ c.name }}</b></td><td>{{ 'Расход' if c.kind=='expense' else 'Доход' }}</td><td><form method="post" action="{{ url_for('delete_category',cat_id=c.id) }}" onsubmit="return confirm('Удалить категорию?')"><button class="danger">Удалить</button></form></td></tr>{% endfor %}</table></div></div></div>
    """
    return page("categories_page","Категории","Создавайте собственные категории для удобного учёта.",content,cats=cats)

@app.route("/categories/<int:cat_id>/delete",methods=["POST"])
def delete_category(cat_id):
    with connect() as con:
        c=con.execute("SELECT * FROM categories WHERE id=?",(cat_id,)).fetchone()
        if c and con.execute("SELECT COUNT(*) FROM transactions WHERE category=? AND kind=?",(c["name"],c["kind"])).fetchone()[0]:
            flash("Нельзя удалить категорию, которая используется в операциях.")
        elif c:
            con.execute("DELETE FROM categories WHERE id=?",(cat_id,));flash("Категория удалена.")
    return redirect(url_for("categories_page"))

@app.route("/debts",methods=["GET","POST"])
def debts():
    if request.method=="POST":
        direction=request.form.get("direction");person=request.form.get("person","").strip()
        try: amount=float(request.form.get("amount","0"))
        except ValueError: amount=0
        if direction in ("i_owe","owed_to_me") and person and amount>0:
            with connect() as con:
                con.execute("INSERT INTO debts(direction,person,amount,remaining,due_date,note,created_at) VALUES(?,?,?,?,?,?,?)",
                    (direction,person,amount,amount,request.form.get("due_date",""),request.form.get("note","").strip(),date.today().isoformat()))
            flash("Долг добавлен.")
        else: flash("Заполните имя, тип долга и сумму.")
        return redirect(url_for("debts"))
    with connect() as con: rows=con.execute("SELECT * FROM debts ORDER BY id DESC").fetchall()
    out=sum(r["remaining"] for r in rows if r["direction"]=="i_owe")
    incoming=sum(r["remaining"] for r in rows if r["direction"]=="owed_to_me")
    content=r"""
    <div class="grid"><div class="card"><div class="statlabel">Я должен</div><div class="stat red">{{ out|money }} сум</div></div><div class="card"><div class="statlabel">Мне должны</div><div class="stat green">{{ incoming|money }} сум</div></div><div class="card"><div class="statlabel">Количество долгов</div><div class="stat">{{ rows|length }}</div></div></div>
    <div class="split"><div class="card"><h2>Добавить долг</h2><form method="post"><div class="field"><label>Тип долга</label><select name="direction"><option value="i_owe">Я должен</option><option value="owed_to_me">Мне должны</option></select></div><div class="field"><label>Человек</label><input name="person" required placeholder="Имя"></div><div class="field"><label>Сумма (сум)</label><input name="amount" type="number" min="1" required></div><div class="field"><label>Вернуть до</label><input name="due_date" type="date"></div><div class="field"><label>Комментарий</label><input name="note"></div><button class="primary">Сохранить долг</button></form></div>
    <div class="card"><h2>Список долгов</h2><div class="tablewrap"><table><tr><th>Человек</th><th>Тип</th><th>Остаток</th><th>Срок</th><th></th></tr>{% for d in rows %}<tr><td><b>{{ d.person }}</b><div class="small">{{ d.note }}</div></td><td>{{ 'Я должен' if d.direction=='i_owe' else 'Мне должны' }}</td><td class="amount">{{ d.remaining|money }} сум</td><td>{{ d.due_date or '—' }}</td><td><div class="actions"><form method="post" action="{{ url_for('repay_debt',debt_id=d.id) }}"><input type="hidden" name="amount" value="{{ d.remaining }}"><button class="primary">Закрыть</button></form><form method="post" action="{{ url_for('delete_debt',debt_id=d.id) }}"><button class="danger">✕</button></form></div></td></tr>{% else %}<tr><td colspan="5" class="empty">Долгов пока нет</td></tr>{% endfor %}</table></div><p class="small">Кнопка «Закрыть» отмечает долг полностью погашенным и убирает его из активных сумм.</p></div></div>
    """
    return page("debts","Долги","Отдельно учитывайте деньги, которые вы должны, и деньги, которые должны вам.",content,rows=rows,out=out,incoming=incoming)

@app.route("/debts/<int:debt_id>/repay",methods=["POST"])
def repay_debt(debt_id):
    with connect() as con: con.execute("UPDATE debts SET remaining=0 WHERE id=?",(debt_id,))
    flash("Долг отмечен как закрытый.");return redirect(url_for("debts"))

@app.route("/debts/<int:debt_id>/delete",methods=["POST"])
def delete_debt(debt_id):
    with connect() as con: con.execute("DELETE FROM debts WHERE id=?",(debt_id,))
    flash("Запись о долге удалена.");return redirect(url_for("debts"))

@app.route("/savings",methods=["GET","POST"])
def savings():
    if request.method=="POST":
        title=request.form.get("title","").strip()
        try: target=float(request.form.get("target","0"));saved=float(request.form.get("saved","0"))
        except ValueError: target=saved=0
        if title and target>0 and 0<=saved<=target:
            with connect() as con: con.execute("INSERT INTO savings(title,target,saved,due_date,note) VALUES(?,?,?,?,?)",(title,target,saved,request.form.get("due_date",""),request.form.get("note","").strip()))
            flash("Цель накопления создана.")
        else: flash("Проверьте название и суммы. Накопления не могут превышать цель.")
        return redirect(url_for("savings"))
    with connect() as con: rows=con.execute("SELECT * FROM savings ORDER BY id DESC").fetchall()
    content=r"""
    <div class="grid"><div class="card"><div class="statlabel">Всего накоплено</div><div class="stat green">{{ total|money }} сум</div></div><div class="card"><div class="statlabel">Целей</div><div class="stat">{{ rows|length }}</div></div><div class="card"><div class="statlabel">Осталось накопить</div><div class="stat">{{ left|money }} сум</div></div></div>
    <div class="split"><div class="card"><h2>Новая цель</h2><form method="post"><div class="field"><label>На что копим?</label><input name="title" required placeholder="Например, ноутбук"></div><div class="field"><label>Целевая сумма (сум)</label><input name="target" type="number" min="1" required></div><div class="field"><label>Уже накоплено (сум)</label><input name="saved" type="number" min="0" value="0"></div><div class="field"><label>Желаемый срок</label><input name="due_date" type="date"></div><div class="field"><label>Комментарий</label><input name="note"></div><button class="primary">Создать цель</button></form></div>
    <div class="card"><h2>Мои цели</h2>{% for s in rows %}<div style="padding:12px 0;border-bottom:1px solid #edf0f5"><div class="toolbar"><b>{{ s.title }}</b><span class="pill">{{ ((s.saved/s.target)*100)|round|int }}%</span></div><div class="stat">{{ s.saved|money }} <span class="muted" style="font-size:13px">из {{ s.target|money }} сум</span></div><div class="bar"><span style="width:{{ [100,(s.saved/s.target*100)]|min }}%"></span></div><div class="small">Срок: {{ s.due_date or 'не указан' }} · {{ s.note }}</div><form method="post" action="{{ url_for('add_saving',saving_id=s.id) }}" style="display:flex;gap:7px;margin-top:10px"><input name="amount" type="number" min="1" placeholder="Сумма пополнения" required><button class="primary">Пополнить</button></form><form method="post" action="{{ url_for('delete_saving',saving_id=s.id) }}" style="margin-top:7px"><button class="danger">Удалить цель</button></form></div>{% else %}<div class="empty">Создайте первую цель накопления</div>{% endfor %}</div></div>
    """
    total=sum(r["saved"] for r in rows);left=sum(max(0,r["target"]-r["saved"]) for r in rows)
    return page("savings","Сбережения","Создавайте финансовые цели и следите за прогрессом.",content,rows=rows,total=total,left=left)

@app.route("/savings/<int:saving_id>/add",methods=["POST"])
def add_saving(saving_id):
    try: amount=float(request.form.get("amount","0"))
    except ValueError: amount=0
    with connect() as con:
        s=con.execute("SELECT * FROM savings WHERE id=?",(saving_id,)).fetchone()
        if s and amount>0: con.execute("UPDATE savings SET saved=MIN(target,saved+?) WHERE id=?",(amount,saving_id));flash("Сбережения пополнены.")
        else: flash("Введите корректную сумму.")
    return redirect(url_for("savings"))

@app.route("/savings/<int:saving_id>/delete",methods=["POST"])
def delete_saving(saving_id):
    with connect() as con: con.execute("DELETE FROM savings WHERE id=?",(saving_id,))
    flash("Цель удалена.");return redirect(url_for("savings"))

init_db()

if __name__ == "__main__":
    app.run(debug=True)
