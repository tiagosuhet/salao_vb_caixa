from __future__ import annotations

import os
import re
import sqlite3
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from functools import wraps
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from flask import Flask, flash, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "work_orders.db"
APP_TZ = ZoneInfo("America/Sao_Paulo")
EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")
PAYMENT_METHODS = ["Dinheiro", "Pix", "Cartão", "Transferência"]
CATEGORY_PRESETS = {
    "entrada": [
        "Corte",
        "Escova",
        "Coloração",
        "Manicure",
        "Pedicure",
        "Sobrancelha",
        "Tratamento",
        "Venda de produto",
        "Outros",
    ],
    "saida": [
        "Produtos",
        "Material",
        "Comissao",
        "Aluguel",
        "Agua e luz",
        "Manutencao",
        "Marketing",
        "Impostos",
        "Outros",
    ],
}
TRANSACTION_LABELS = {"entrada": "Entrada", "saida": "Saida"}
DEFAULT_TRANSACTION_TYPE = "entrada"

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "change-this-secret-key")


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def local_now() -> datetime:
    return datetime.now(APP_TZ)


def timestamp_now() -> str:
    return local_now().strftime("%Y-%m-%d %H:%M:%S")


def today_str() -> str:
    return local_now().date().isoformat()


def month_start_str() -> str:
    return local_now().strftime("%Y-%m-01")


def parse_iso_date(value: str) -> datetime.date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def days_before(reference_date: str, days: int) -> str:
    return (parse_iso_date(reference_date) - timedelta(days=days)).isoformat()


def normalize_type(value: str | None) -> str:
    if value in CATEGORY_PRESETS:
        return value
    return DEFAULT_TRANSACTION_TYPE


def is_valid_email(email: str) -> bool:
    return bool(EMAIL_RE.fullmatch(email))


def format_currency_from_cents(amount_cents: int) -> str:
    formatted = f"{amount_cents / 100:,.2f}"
    formatted = formatted.replace(",", "_").replace(".", ",").replace("_", ".")
    return f"R$ {formatted}"


def format_input_amount(amount_cents: int) -> str:
    return f"{amount_cents / 100:.2f}"


def format_datetime_br(value: str | None) -> str:
    if not value:
        return "--"

    for pattern in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d"):
        try:
            parsed = datetime.strptime(value, pattern)
            if pattern == "%Y-%m-%d":
                return parsed.strftime("%d/%m/%Y")
            return parsed.strftime("%d/%m/%Y %H:%M")
        except ValueError:
            continue

    return value


def parse_amount_to_cents(raw_value: str) -> int | None:
    cleaned = raw_value.strip()
    if not cleaned:
        return None

    cleaned = re.sub(r"[^\d,.-]", "", cleaned)
    if not cleaned:
        return None

    if "," in cleaned and "." in cleaned:
        if cleaned.rfind(",") > cleaned.rfind("."):
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:
            cleaned = cleaned.replace(",", "")
    else:
        cleaned = cleaned.replace(",", ".")

    try:
        amount = Decimal(cleaned).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except InvalidOperation:
        return None

    if amount <= 0:
        return None

    return int(amount * 100)


def parse_occurred_at(raw_value: str) -> str:
    cleaned = raw_value.strip()
    if not cleaned:
        return timestamp_now()

    for pattern in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M"):
        try:
            parsed = datetime.strptime(cleaned, pattern)
            return parsed.strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue

    return timestamp_now()


def login_required(view_func):
    @wraps(view_func)
    def wrapped_view(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        return view_func(*args, **kwargs)

    return wrapped_view


def init_db() -> None:
    with get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS categories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                transaction_type TEXT NOT NULL CHECK (transaction_type IN ('entrada', 'saida')),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(name, transaction_type)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                transaction_type TEXT NOT NULL CHECK (transaction_type IN ('entrada', 'saida')),
                amount_cents INTEGER NOT NULL CHECK (amount_cents > 0),
                category_id INTEGER NOT NULL,
                payment_method TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                occurred_at TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id),
                FOREIGN KEY (category_id) REFERENCES categories(id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS cash_closings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                closed_date TEXT NOT NULL UNIQUE,
                closed_at TEXT NOT NULL,
                note TEXT NOT NULL DEFAULT '',
                total_entries_cents INTEGER NOT NULL,
                total_exits_cents INTEGER NOT NULL,
                balance_cents INTEGER NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_transactions_occurred_at
            ON transactions (occurred_at DESC)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_transactions_category
            ON transactions (category_id, occurred_at DESC)
            """
        )
        for transaction_type, names in CATEGORY_PRESETS.items():
            conn.executemany(
                """
                INSERT OR IGNORE INTO categories (name, transaction_type)
                VALUES (?, ?)
                """,
                [(name, transaction_type) for name in names],
            )


def categories_by_type(conn: sqlite3.Connection) -> dict[str, list[dict[str, Any]]]:
    rows = conn.execute(
        """
        SELECT id, name, transaction_type
        FROM categories
        ORDER BY transaction_type, name
        """
    ).fetchall()
    grouped: dict[str, list[dict[str, Any]]] = {"entrada": [], "saida": []}
    for row in rows:
        grouped[row["transaction_type"]].append({"id": row["id"], "name": row["name"]})
    return grouped


def all_categories(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT id, name, transaction_type
        FROM categories
        ORDER BY transaction_type, name
        """
    ).fetchall()


def category_exists(
    conn: sqlite3.Connection, category_id: int | None, transaction_type: str
) -> bool:
    if category_id is None:
        return False
    row = conn.execute(
        """
        SELECT id
        FROM categories
        WHERE id = ? AND transaction_type = ?
        """,
        (category_id, transaction_type),
    ).fetchone()
    return row is not None


def fetch_summary(
    conn: sqlite3.Connection,
    *,
    start_date: str | None = None,
    end_date: str | None = None,
    category_id: int | None = None,
    transaction_type: str | None = None,
) -> dict[str, int]:
    conditions: list[str] = []
    params: list[Any] = []

    if start_date:
        conditions.append("date(t.occurred_at) >= date(?)")
        params.append(start_date)
    if end_date:
        conditions.append("date(t.occurred_at) <= date(?)")
        params.append(end_date)
    if category_id:
        conditions.append("t.category_id = ?")
        params.append(category_id)
    if transaction_type in CATEGORY_PRESETS:
        conditions.append("t.transaction_type = ?")
        params.append(transaction_type)

    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    row = conn.execute(
        f"""
        SELECT
            COALESCE(SUM(CASE WHEN t.transaction_type = 'entrada' THEN t.amount_cents ELSE 0 END), 0) AS total_entries,
            COALESCE(SUM(CASE WHEN t.transaction_type = 'saida' THEN t.amount_cents ELSE 0 END), 0) AS total_exits,
            COALESCE(SUM(CASE WHEN t.transaction_type = 'entrada' THEN t.amount_cents ELSE -t.amount_cents END), 0) AS balance,
            COUNT(*) AS transaction_count
        FROM transactions t
        {where_clause}
        """,
        params,
    ).fetchone()

    return {
        "total_entries": row["total_entries"],
        "total_exits": row["total_exits"],
        "balance": row["balance"],
        "transaction_count": row["transaction_count"],
    }


def fetch_transactions(
    conn: sqlite3.Connection,
    *,
    start_date: str | None = None,
    end_date: str | None = None,
    category_id: int | None = None,
    transaction_type: str | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    conditions: list[str] = []
    params: list[Any] = []

    if start_date:
        conditions.append("date(t.occurred_at) >= date(?)")
        params.append(start_date)
    if end_date:
        conditions.append("date(t.occurred_at) <= date(?)")
        params.append(end_date)
    if category_id:
        conditions.append("t.category_id = ?")
        params.append(category_id)
    if transaction_type in CATEGORY_PRESETS:
        conditions.append("t.transaction_type = ?")
        params.append(transaction_type)

    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    limit_clause = "LIMIT ?" if limit else ""
    if limit:
        params.append(limit)

    rows = conn.execute(
        f"""
        SELECT
            t.id,
            t.transaction_type,
            t.amount_cents,
            t.payment_method,
            t.description,
            t.occurred_at,
            c.name AS category_name,
            u.email AS recorded_by
        FROM transactions t
        JOIN categories c ON c.id = t.category_id
        JOIN users u ON u.id = t.user_id
        {where_clause}
        ORDER BY t.occurred_at DESC, t.id DESC
        {limit_clause}
        """,
        params,
    ).fetchall()

    return [dict(row) for row in rows]


def fetch_transaction_by_id(
    conn: sqlite3.Connection, transaction_id: int
) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT *
        FROM transactions
        WHERE id = ?
        """,
        (transaction_id,),
    ).fetchone()
    return dict(row) if row else None


def fetch_category_breakdown(
    conn: sqlite3.Connection,
    *,
    start_date: str,
    end_date: str,
    transaction_type: str = "saida",
    limit: int = 5,
) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT
            c.name AS category_name,
            SUM(t.amount_cents) AS total_cents
        FROM transactions t
        JOIN categories c ON c.id = t.category_id
        WHERE t.transaction_type = ?
          AND date(t.occurred_at) >= date(?)
          AND date(t.occurred_at) <= date(?)
        GROUP BY c.name
        ORDER BY total_cents DESC, c.name ASC
        LIMIT ?
        """,
        (transaction_type, start_date, end_date, limit),
    ).fetchall()
    return [dict(row) for row in rows]


def fetch_daily_cashflow(
    conn: sqlite3.Connection, *, start_date: str, end_date: str
) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT
            date(occurred_at) AS flow_date,
            COALESCE(SUM(CASE WHEN transaction_type = 'entrada' THEN amount_cents ELSE 0 END), 0) AS entries_cents,
            COALESCE(SUM(CASE WHEN transaction_type = 'saida' THEN amount_cents ELSE 0 END), 0) AS exits_cents
        FROM transactions
        WHERE date(occurred_at) >= date(?)
          AND date(occurred_at) <= date(?)
        GROUP BY date(occurred_at)
        ORDER BY flow_date ASC
        """,
        (start_date, end_date),
    ).fetchall()

    by_date = {row["flow_date"]: dict(row) for row in rows}
    series: list[dict[str, Any]] = []
    cursor = parse_iso_date(start_date)
    end_cursor = parse_iso_date(end_date)

    while cursor <= end_cursor:
        iso_date = cursor.isoformat()
        point = by_date.get(
            iso_date,
            {"entries_cents": 0, "exits_cents": 0},
        )
        entries_cents = point["entries_cents"]
        exits_cents = point["exits_cents"]
        series.append(
            {
                "date": iso_date,
                "label": cursor.strftime("%d/%m"),
                "entries_cents": entries_cents,
                "exits_cents": exits_cents,
                "net_cents": entries_cents - exits_cents,
            }
        )
        cursor += timedelta(days=1)

    return series


def fetch_category_comparison(
    conn: sqlite3.Connection,
    *,
    start_date: str,
    end_date: str,
    category_id: int | None = None,
) -> list[dict[str, Any]]:
    conditions = [
        "date(t.occurred_at) >= date(?)",
        "date(t.occurred_at) <= date(?)",
    ]
    params: list[Any] = [start_date, end_date]

    if category_id:
        conditions.append("t.category_id = ?")
        params.append(category_id)

    where_clause = " AND ".join(conditions)
    rows = conn.execute(
        f"""
        SELECT
            c.name AS category_name,
            COALESCE(SUM(CASE WHEN t.transaction_type = 'entrada' THEN t.amount_cents ELSE 0 END), 0) AS entries_cents,
            COALESCE(SUM(CASE WHEN t.transaction_type = 'saida' THEN t.amount_cents ELSE 0 END), 0) AS exits_cents
        FROM transactions t
        JOIN categories c ON c.id = t.category_id
        WHERE {where_clause}
        GROUP BY c.name
        ORDER BY SUM(t.amount_cents) DESC, c.name ASC
        LIMIT 6
        """,
        params,
    ).fetchall()
    return [dict(row) for row in rows]


def fetch_payment_breakdown(
    conn: sqlite3.Connection, *, start_date: str, end_date: str
) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT
            payment_method,
            COUNT(*) AS usage_count,
            SUM(amount_cents) AS total_cents
        FROM transactions
        WHERE date(occurred_at) >= date(?)
          AND date(occurred_at) <= date(?)
        GROUP BY payment_method
        ORDER BY total_cents DESC, usage_count DESC, payment_method ASC
        """,
        (start_date, end_date),
    ).fetchall()
    return [dict(row) for row in rows]


def fetch_last_closing(conn: sqlite3.Connection) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT cc.*, u.email AS closed_by
        FROM cash_closings cc
        JOIN users u ON u.id = cc.user_id
        ORDER BY cc.closed_at DESC
        LIMIT 1
        """
    ).fetchone()
    return dict(row) if row else None


def build_form_context(
    conn: sqlite3.Connection,
    *,
    transaction: dict[str, Any] | None = None,
    action_url: str,
    heading: str,
    submit_label: str,
) -> dict[str, Any]:
    categories_map = categories_by_type(conn)
    current_type = (
        normalize_type(transaction["transaction_type"])
        if transaction
        else DEFAULT_TRANSACTION_TYPE
    )
    occurred_at = transaction["occurred_at"] if transaction else timestamp_now()
    return {
        "transaction": transaction,
        "categories_map": categories_map,
        "current_type": current_type,
        "payment_methods": PAYMENT_METHODS,
        "action_url": action_url,
        "heading": heading,
        "submit_label": submit_label,
        "occurred_at_raw": occurred_at,
        "occurred_at_display": format_datetime_br(occurred_at),
    }


def validate_transaction_input(
    conn: sqlite3.Connection,
    *,
    transaction_type: str,
    amount_cents: int | None,
    category_id: int | None,
    payment_method: str,
) -> str | None:
    if amount_cents is None:
        return "Informe um valor valido para continuar."
    if payment_method not in PAYMENT_METHODS:
        return "Selecione uma forma de pagamento valida."
    if not category_exists(conn, category_id, transaction_type):
        return "Selecione uma categoria compativel com o tipo informado."
    return None


@app.template_filter("money")
def money_filter(value: int) -> str:
    return format_currency_from_cents(int(value))


@app.template_filter("datetime_br")
def datetime_br_filter(value: str | None) -> str:
    return format_datetime_br(value)


@app.template_filter("transaction_label")
def transaction_label_filter(value: str | None) -> str:
    return TRANSACTION_LABELS.get(value or "", "Lancamento")


@app.get("/login")
def login() -> str:
    init_db()
    if "user_id" in session:
        return redirect(url_for("index"))
    return render_template("login.html")


@app.post("/login")
def login_post():
    init_db()

    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")

    if not is_valid_email(email):
        flash("Informe um e-mail valido.", "error")
        return redirect(url_for("login"))

    with get_connection() as conn:
        user = conn.execute(
            "SELECT id, email, password_hash FROM users WHERE email = ?",
            (email,),
        ).fetchone()

    if user is None or not check_password_hash(user["password_hash"], password):
        flash("E-mail ou senha invalidos.", "error")
        return redirect(url_for("login"))

    session["user_id"] = user["id"]
    session["user_email"] = user["email"]
    return redirect(url_for("index"))


@app.post("/register")
def register():
    init_db()

    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")

    if not is_valid_email(email):
        flash("Informe um e-mail valido.", "error")
        return redirect(url_for("login"))

    if len(password) < 6:
        flash("A senha deve ter pelo menos 6 caracteres.", "error")
        return redirect(url_for("login"))

    try:
        with get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO users (email, password_hash)
                VALUES (?, ?)
                """,
                (email, generate_password_hash(password)),
            )
            session["user_id"] = cursor.lastrowid
            session["user_email"] = email
    except sqlite3.IntegrityError:
        flash("Este e-mail ja esta cadastrado.", "error")
        return redirect(url_for("login"))

    flash("Conta criada com sucesso.", "success")
    return redirect(url_for("index"))


@app.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.get("/")
@login_required
def index() -> str:
    init_db()

    today = today_str()
    month_start = month_start_str()
    dashboard_start = days_before(today, 13)

    with get_connection() as conn:
        overall_summary = fetch_summary(conn)
        today_summary = fetch_summary(conn, start_date=today, end_date=today)
        month_summary = fetch_summary(conn, start_date=month_start, end_date=today)
        dashboard_flow = fetch_daily_cashflow(
            conn, start_date=dashboard_start, end_date=today
        )
        today_transactions = fetch_transactions(
            conn, start_date=today, end_date=today, limit=8
        )
        payment_breakdown = fetch_payment_breakdown(
            conn, start_date=month_start, end_date=today
        )
        category_breakdown = fetch_category_breakdown(
            conn, start_date=month_start, end_date=today
        )
        last_closing = fetch_last_closing(conn)

    return render_template(
        "dashboard.html",
        active_page="dashboard",
        overall_summary=overall_summary,
        today_summary=today_summary,
        month_summary=month_summary,
        dashboard_flow=dashboard_flow,
        today_transactions=today_transactions,
        payment_breakdown=payment_breakdown[:4],
        category_breakdown=category_breakdown[:5],
        last_closing=last_closing,
        today=today,
        dashboard_start=dashboard_start,
        user_email=session.get("user_email"),
    )


@app.get("/lancamentos/novo")
@login_required
def new_transaction() -> str:
    init_db()

    current_type = normalize_type(request.args.get("type"))

    with get_connection() as conn:
        context = build_form_context(
            conn,
            transaction={
                "transaction_type": current_type,
                "amount_input": "",
                "category_id": "",
                "payment_method": "Dinheiro",
                "description": "",
                "occurred_at": timestamp_now(),
            },
            action_url=url_for("create_transaction"),
            heading="Registrar lancamento",
            submit_label="Salvar lancamento",
        )

    return render_template(
        "transaction_form.html",
        active_page="new_transaction",
        is_edit=False,
        **context,
    )


@app.post("/lancamentos")
@login_required
def create_transaction():
    init_db()

    transaction_type = normalize_type(request.form.get("transaction_type"))
    amount_cents = parse_amount_to_cents(request.form.get("amount", ""))
    category_id = request.form.get("category_id", type=int)
    payment_method = request.form.get("payment_method", "").strip()
    description = request.form.get("description", "").strip()[:180]
    occurred_at = parse_occurred_at(request.form.get("occurred_at", ""))

    with get_connection() as conn:
        error = validate_transaction_input(
            conn,
            transaction_type=transaction_type,
            amount_cents=amount_cents,
            category_id=category_id,
            payment_method=payment_method,
        )
        if error:
            flash(error, "error")
            return redirect(url_for("new_transaction", type=transaction_type))

        conn.execute(
            """
            INSERT INTO transactions (
                user_id,
                transaction_type,
                amount_cents,
                category_id,
                payment_method,
                description,
                occurred_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session["user_id"],
                transaction_type,
                amount_cents,
                category_id,
                payment_method,
                description,
                occurred_at,
            ),
        )

    flash("Lancamento registrado com sucesso.", "success")
    return redirect(url_for("index"))


@app.get("/lancamentos/<int:transaction_id>/editar")
@login_required
def edit_transaction(transaction_id: int) -> str:
    init_db()

    with get_connection() as conn:
        transaction = fetch_transaction_by_id(conn, transaction_id)
        if transaction is None:
            flash("Lancamento nao encontrado.", "error")
            return redirect(url_for("history"))

        context = build_form_context(
            conn,
            transaction={
                **transaction,
                "amount_input": format_input_amount(transaction["amount_cents"]),
            },
            action_url=url_for("update_transaction", transaction_id=transaction_id),
            heading="Editar lancamento",
            submit_label="Salvar alteracoes",
        )

    return render_template(
        "transaction_form.html",
        active_page="new_transaction",
        is_edit=True,
        **context,
    )


@app.post("/lancamentos/<int:transaction_id>/atualizar")
@login_required
def update_transaction(transaction_id: int):
    init_db()

    transaction_type = normalize_type(request.form.get("transaction_type"))
    amount_cents = parse_amount_to_cents(request.form.get("amount", ""))
    category_id = request.form.get("category_id", type=int)
    payment_method = request.form.get("payment_method", "").strip()
    description = request.form.get("description", "").strip()[:180]
    occurred_at = parse_occurred_at(request.form.get("occurred_at", ""))

    with get_connection() as conn:
        existing = fetch_transaction_by_id(conn, transaction_id)
        if existing is None:
            flash("Lancamento nao encontrado.", "error")
            return redirect(url_for("history"))

        error = validate_transaction_input(
            conn,
            transaction_type=transaction_type,
            amount_cents=amount_cents,
            category_id=category_id,
            payment_method=payment_method,
        )
        if error:
            flash(error, "error")
            return redirect(url_for("edit_transaction", transaction_id=transaction_id))

        conn.execute(
            """
            UPDATE transactions
            SET transaction_type = ?,
                amount_cents = ?,
                category_id = ?,
                payment_method = ?,
                description = ?,
                occurred_at = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                transaction_type,
                amount_cents,
                category_id,
                payment_method,
                description,
                occurred_at,
                transaction_id,
            ),
        )

    flash("Lancamento atualizado com sucesso.", "success")
    return redirect(url_for("history"))


@app.post("/lancamentos/<int:transaction_id>/excluir")
@login_required
def delete_transaction(transaction_id: int):
    init_db()

    with get_connection() as conn:
        existing = conn.execute(
            "SELECT id FROM transactions WHERE id = ?", (transaction_id,)
        ).fetchone()
        if existing is None:
            flash("Lancamento nao encontrado.", "error")
            return redirect(url_for("history"))

        conn.execute("DELETE FROM transactions WHERE id = ?", (transaction_id,))

    flash("Lancamento removido com sucesso.", "success")
    return redirect(url_for("history"))


@app.get("/historico")
@login_required
def history() -> str:
    init_db()

    today = today_str()
    start_date = request.args.get("start_date", today).strip() or today
    end_date = request.args.get("end_date", today).strip() or today
    category_id = request.args.get("category_id", type=int)
    transaction_type = request.args.get("transaction_type", "").strip()
    if transaction_type not in CATEGORY_PRESETS:
        transaction_type = ""

    with get_connection() as conn:
        overall_summary = fetch_summary(conn)
        filtered_summary = fetch_summary(
            conn,
            start_date=start_date,
            end_date=end_date,
            category_id=category_id,
            transaction_type=transaction_type or None,
        )
        filtered_flow = fetch_daily_cashflow(
            conn, start_date=start_date, end_date=end_date
        )
        transactions = fetch_transactions(
            conn,
            start_date=start_date,
            end_date=end_date,
            category_id=category_id,
            transaction_type=transaction_type or None,
        )
        categories = all_categories(conn)
        filtered_category_breakdown = fetch_category_comparison(
            conn,
            start_date=start_date,
            end_date=end_date,
            category_id=category_id,
        )
        month_summary = fetch_summary(
            conn,
            start_date=month_start_str(),
            end_date=today,
        )
        payment_breakdown = fetch_payment_breakdown(
            conn,
            start_date=month_start_str(),
            end_date=today,
        )
        category_breakdown = fetch_category_breakdown(
            conn,
            start_date=month_start_str(),
            end_date=today,
        )
        last_closing = fetch_last_closing(conn)

    return render_template(
        "history.html",
        active_page="history",
        overall_summary=overall_summary,
        filtered_summary=filtered_summary,
        filtered_flow=filtered_flow,
        transactions=transactions,
        categories=categories,
        filtered_category_breakdown=filtered_category_breakdown,
        selected_category_id=category_id,
        selected_transaction_type=transaction_type,
        start_date=start_date,
        end_date=end_date,
        month_summary=month_summary,
        payment_breakdown=payment_breakdown,
        category_breakdown=category_breakdown,
        last_closing=last_closing,
    )


@app.get("/fechar-caixa")
@login_required
def close_cash_view() -> str:
    init_db()

    today = today_str()

    with get_connection() as conn:
        today_summary = fetch_summary(conn, start_date=today, end_date=today)
        last_closing = conn.execute(
            """
            SELECT cc.*, u.email AS closed_by
            FROM cash_closings cc
            JOIN users u ON u.id = cc.user_id
            WHERE cc.closed_date = ?
            ORDER BY cc.closed_at DESC
            LIMIT 1
            """,
            (today,),
        ).fetchone()

    return render_template(
        "close_cash.html",
        active_page="close_cash",
        today=today,
        today_summary=today_summary,
        last_closing=dict(last_closing) if last_closing else None,
    )


@app.post("/fechar-caixa")
@login_required
def close_cash():
    init_db()

    today = today_str()
    note = request.form.get("note", "").strip()[:240]

    with get_connection() as conn:
        today_summary = fetch_summary(conn, start_date=today, end_date=today)
        existing = conn.execute(
            "SELECT id FROM cash_closings WHERE closed_date = ?",
            (today,),
        ).fetchone()

        if existing is None:
            conn.execute(
                """
                INSERT INTO cash_closings (
                    user_id,
                    closed_date,
                    closed_at,
                    note,
                    total_entries_cents,
                    total_exits_cents,
                    balance_cents
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session["user_id"],
                    today,
                    timestamp_now(),
                    note,
                    today_summary["total_entries"],
                    today_summary["total_exits"],
                    today_summary["balance"],
                ),
            )
            flash("Caixa do dia fechado com sucesso.", "success")
        else:
            conn.execute(
                """
                UPDATE cash_closings
                SET user_id = ?,
                    closed_at = ?,
                    note = ?,
                    total_entries_cents = ?,
                    total_exits_cents = ?,
                    balance_cents = ?
                WHERE closed_date = ?
                """,
                (
                    session["user_id"],
                    timestamp_now(),
                    note,
                    today_summary["total_entries"],
                    today_summary["total_exits"],
                    today_summary["balance"],
                    today,
                ),
            )
            flash("Fechamento de hoje atualizado com sucesso.", "success")

    return redirect(url_for("index"))


if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8081")), debug=True)
