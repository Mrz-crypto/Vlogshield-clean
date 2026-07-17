from datetime import datetime, timezone
from contextlib import closing
from functools import wraps
import logging
import os
from pathlib import Path
import sqlite3

from flask import flash, g, jsonify, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

try:
    from .app import ROOT, app
except ImportError:
    from app import ROOT, app

try:
    from .storage import mysql_config_from_env
except ImportError:
    from storage import mysql_config_from_env


PUBLIC_ENDPOINTS = {"health_check", "login", "register", "static"}
USER_DB_PATH = Path(os.getenv("USER_DB_PATH", ROOT / "instance" / "vlogshield_users.sqlite3"))
logger = logging.getLogger(__name__)


class UserStore:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self):
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def _init_db(self):
        with closing(self._connect()) as db:
            with db:
                db.execute(
                    """
                    CREATE TABLE IF NOT EXISTS users (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        username TEXT NOT NULL UNIQUE,
                        email TEXT NOT NULL UNIQUE,
                        password_hash TEXT NOT NULL,
                        role TEXT NOT NULL CHECK(role IN ('admin', 'user')),
                        created_at TEXT NOT NULL,
                        last_login_at TEXT
                    )
                    """
                )

    def clear(self):
        with closing(self._connect()) as db:
            with db:
                db.execute("DELETE FROM users")

    def delete_user(self, user_id):
        with closing(self._connect()) as db:
            with db:
                cursor = db.execute("DELETE FROM users WHERE id = ?", (user_id,))
        return cursor.rowcount > 0

    def export_users(self):
        with closing(self._connect()) as db:
            rows = db.execute(
                """
                SELECT id, username, email, password_hash, role, created_at, last_login_at
                FROM users
                ORDER BY id ASC
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def has_users(self):
        with closing(self._connect()) as db:
            row = db.execute("SELECT COUNT(*) AS total FROM users").fetchone()
            return row["total"] > 0

    def create_user(self, username, email, password):
        username = username.strip().lower()
        email = email.strip().lower()
        role = "user" if self.has_users() else "admin"
        now = datetime.now(timezone.utc).isoformat()
        password_hash = generate_password_hash(password)

        with closing(self._connect()) as db:
            with db:
                cursor = db.execute(
                    """
                    INSERT INTO users (username, email, password_hash, role, created_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (username, email, password_hash, role, now),
                )
                user_id = cursor.lastrowid
        _mirror_user_snapshot(
            {
                "id": user_id,
                "username": username,
                "email": email,
                "password_hash": password_hash,
                "role": role,
                "created_at": now,
                "last_login_at": None,
            }
        )
        return self.find_by_id(user_id)

    def find_by_id(self, user_id):
        with closing(self._connect()) as db:
            row = db.execute(
                "SELECT id, username, email, role, created_at, last_login_at FROM users WHERE id = ?",
                (user_id,),
            ).fetchone()
        return dict(row) if row else None

    def find_by_identity(self, identity):
        identity = identity.strip().lower()
        with closing(self._connect()) as db:
            row = db.execute(
                """
                SELECT id, username, email, password_hash, role, created_at, last_login_at
                FROM users
                WHERE username = ? OR email = ?
                """,
                (identity, identity),
            ).fetchone()
        return dict(row) if row else None

    def verify_user(self, identity, password):
        row = self.find_by_identity(identity)
        if not row or not check_password_hash(row["password_hash"], password):
            return None
        now = datetime.now(timezone.utc).isoformat()
        self.update_last_login(row["id"], now)
        row["last_login_at"] = now
        _mirror_user_snapshot(row)
        return self.find_by_id(row["id"])

    def update_last_login(self, user_id, timestamp=None):
        now = timestamp or datetime.now(timezone.utc).isoformat()
        with closing(self._connect()) as db:
            with db:
                db.execute("UPDATE users SET last_login_at = ? WHERE id = ?", (now, user_id))

    def list_users(self):
        with closing(self._connect()) as db:
            rows = db.execute(
                """
                SELECT id, username, email, role, created_at, last_login_at
                FROM users
                ORDER BY id ASC
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def summary(self):
        users = self.list_users()
        return {
            "total_users": len(users),
            "admins": sum(1 for user in users if user["role"] == "admin"),
            "users": sum(1 for user in users if user["role"] == "user"),
        }


class MySQLAuthMirror:
    name = "mysql"

    def __init__(self, config: dict):
        try:
            import mysql.connector
        except ImportError as exc:
            raise RuntimeError("mysql-connector-python is required for MySQL auth mirroring.") from exc

        self._mysql = mysql.connector
        self._config = config
        self._ensure_schema()

    def _connect(self):
        return self._mysql.connect(**self._config)

    def _ensure_schema(self):
        users_ddl = """
            CREATE TABLE IF NOT EXISTS users (
                id INT NOT NULL PRIMARY KEY,
                username VARCHAR(255) NOT NULL UNIQUE,
                email VARCHAR(255) NOT NULL UNIQUE,
                password_hash VARCHAR(255) NOT NULL,
                role VARCHAR(16) NOT NULL,
                created_at VARCHAR(40) NOT NULL,
                last_login_at VARCHAR(40) NULL
            )
        """
        login_events_ddl = """
            CREATE TABLE IF NOT EXISTS login_events (
                event_id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
                user_id INT NOT NULL,
                username VARCHAR(255) NOT NULL,
                email VARCHAR(255) NOT NULL,
                role VARCHAR(16) NOT NULL,
                logged_in_at VARCHAR(40) NOT NULL
            )
        """

        with self._connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(users_ddl)
                cursor.execute(login_events_ddl)
            conn.commit()

    def _write_user(self, cursor, user):
        cursor.execute(
            """
            INSERT INTO users (id, username, email, password_hash, role, created_at, last_login_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (
                user["id"],
                user["username"],
                user["email"],
                user["password_hash"],
                user["role"],
                user["created_at"],
                user.get("last_login_at"),
            ),
        )

    def sync_from_users(self, users):
        with self._connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute("DELETE FROM users")
                for user in users:
                    self._write_user(cursor, user)
            conn.commit()

    def store_user(self, user):
        with self._connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute("DELETE FROM users WHERE id = %s", (user["id"],))
                self._write_user(cursor, user)
            conn.commit()

    def record_login(self, user):
        with self._connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO login_events (user_id, username, email, role, logged_in_at)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (
                        user["id"],
                        user["username"],
                        user["email"],
                        user["role"],
                        datetime.now(timezone.utc).isoformat(),
                    ),
                )
            conn.commit()

    def delete_user(self, user_id):
        with self._connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute("DELETE FROM login_events WHERE user_id = %s", (user_id,))
                cursor.execute("DELETE FROM users WHERE id = %s", (user_id,))
            conn.commit()


def _mirror_user_snapshot(user):
    if user_mirror is None:
        return
    try:
        user_mirror.store_user(user)
    except Exception as exc:
        logger.warning("MySQL user mirroring failed; continuing with local auth only: %s", exc)


def _record_login_event(user):
    if user_mirror is None:
        return
    try:
        user_mirror.record_login(user)
    except Exception as exc:
        logger.warning("MySQL login event mirroring failed; continuing with local auth only: %s", exc)


def _delete_user_everywhere(user_id):
    deleted = user_store.delete_user(user_id)
    if not deleted:
        return False
    if user_mirror is not None:
        try:
            user_mirror.delete_user(user_id)
        except Exception as exc:
            logger.warning("MySQL user deletion mirror failed; continuing with local auth only: %s", exc)
    return True


def create_user_mirror(local_store):
    try:
        config = mysql_config_from_env()
        if not config:
            return None
        mirror = MySQLAuthMirror(config)
        mirror.sync_from_users(local_store.export_users())
        return mirror
    except Exception as exc:
        logger.warning("MySQL auth mirroring unavailable; using SQLite-only auth: %s", exc)
        return None


user_store = UserStore(USER_DB_PATH)
user_mirror = create_user_mirror(user_store)


def configure_user_store(path):
    global user_store
    user_store = UserStore(path)
    if user_mirror is not None:
        try:
            user_mirror.sync_from_users(user_store.export_users())
        except Exception as exc:
            logger.warning("MySQL auth mirror refresh failed: %s", exc)
    return user_store


def current_user():
    user_id = session.get("user_id")
    if not user_id:
        return None
    if getattr(g, "current_user", None) is None:
        g.current_user = user_store.find_by_id(user_id)
    return g.current_user


def wants_json_response():
    if request.path.startswith(("/scan", "/history", "/stats")):
        return True
    best = request.accept_mimetypes.best
    return best == "application/json" and request.accept_mimetypes[best] > request.accept_mimetypes["text/html"]


def auth_required_response():
    if wants_json_response():
        return jsonify({"error": "Authentication required"}), 401
    return redirect(url_for("login", next=request.full_path.rstrip("?")))


def login_required(route):
    @wraps(route)
    def wrapper(*args, **kwargs):
        if not current_user():
            return auth_required_response()
        return route(*args, **kwargs)

    return wrapper


def admin_required(route):
    @wraps(route)
    def wrapper(*args, **kwargs):
        user = current_user()
        if not user:
            return auth_required_response()
        if user["role"] != "admin":
            if wants_json_response():
                return jsonify({"error": "Admin access required"}), 403
            flash("Admin access required.", "error")
            return redirect(url_for("index"))
        return route(*args, **kwargs)

    return wrapper


def validate_registration(username, email, password, confirm):
    if len(username.strip()) < 3:
        return "Username must be at least 3 characters."
    if "@" not in email or "." not in email:
        return "Enter a valid email address."
    if len(password) < 8:
        return "Password must be at least 8 characters."
    if password != confirm:
        return "Passwords do not match."
    return None


@app.context_processor
def inject_current_user():
    return {"current_user": current_user()}


@app.before_request
def require_login_for_private_routes():
    if request.endpoint in PUBLIC_ENDPOINTS or request.endpoint is None:
        return None
    if not current_user():
        return auth_required_response()
    return None


@app.route("/register", methods=["GET", "POST"])
def register():
    if current_user():
        return redirect(url_for("index"))

    if request.method == "POST":
        username = request.form.get("username", "")
        email = request.form.get("email", "")
        password = request.form.get("password", "")
        confirm = request.form.get("confirm", "")
        error = validate_registration(username, email, password, confirm)

        if not error:
            try:
                user = user_store.create_user(username, email, password)
                session.clear()
                session["user_id"] = user["id"]
                session.permanent = True
                _record_login_event(user)
                flash(f"Account created. You are signed in as {user['role']}.", "success")
                return redirect(url_for("index"))
            except sqlite3.IntegrityError:
                error = "Username or email is already registered."

        flash(error, "error")

    return render_template("auth.html", mode="register", first_account=not user_store.has_users())


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user():
        return redirect(url_for("index"))

    next_url = request.args.get("next") or request.form.get("next") or url_for("index")
    if request.method == "POST":
        identity = request.form.get("identity", "")
        password = request.form.get("password", "")
        user = user_store.verify_user(identity, password)

        if user:
            session.clear()
            session["user_id"] = user["id"]
            session.permanent = True
            _record_login_event(user)
            return redirect(next_url if next_url.startswith("/") else url_for("index"))

        flash("Invalid username/email or password.", "error")

    return render_template("auth.html", mode="login", next_url=next_url)


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    flash("Signed out.", "success")
    return redirect(url_for("login"))


@app.route("/admin/users/<int:user_id>/delete", methods=["POST"])
@admin_required
def delete_user(user_id):
    actor = current_user()
    target = user_store.find_by_id(user_id)

    if not target:
        flash("User not found.", "error")
        return redirect(url_for("admin_dashboard"))

    if actor and target["id"] == actor["id"]:
        flash("You cannot delete your own account while signed in.", "error")
        return redirect(url_for("admin_dashboard"))

    summary = user_store.summary()
    if target["role"] == "admin" and summary["admins"] <= 1:
        flash("At least one admin account must remain.", "error")
        return redirect(url_for("admin_dashboard"))

    if not _delete_user_everywhere(user_id):
        flash("User not found.", "error")
        return redirect(url_for("admin_dashboard"))

    flash(f"Deleted user {target['username']}.", "success")
    return redirect(url_for("admin_dashboard"))


@app.route("/admin", methods=["GET"])
@admin_required
def admin_dashboard():
    return render_template(
        "admin.html",
        users=user_store.list_users(),
        auth_summary=user_store.summary(),
    )
