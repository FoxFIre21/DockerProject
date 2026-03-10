#!/usr/bin/env python3
import base64
import hashlib
import hmac
import io
import json
import os
import re
import secrets
import shutil
import struct
import subprocess
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from mimetypes import guess_type
from pathlib import Path
from urllib.parse import unquote, urlparse


ROOT = Path(__file__).resolve().parent
STATIC_DIR = ROOT / "static"
USERS_FILE = ROOT / "users.json"
HOST = "0.0.0.0"
PORT = int(os.environ.get("PORT", "9510"))
AUTH_USER = os.environ.get("APP_USER", "admin")
AUTH_PASSWORD = os.environ.get("APP_PASSWORD", "docker123")
ROLE_LEVELS = {"user": 0, "operator": 1, "admin": 2}

SESSIONS = {}  # token -> {"username": str, "created_at": float, "ip": str}
PENDING_2FA = {}  # temp_token -> {"username": str, "expires": float}
PENDING_TOTP_SETUPS = {}  # username -> {"secret": str, "expires": float}

DEMO_CONTAINERS = [
    {
        "id": "demo-api",
        "name": "api-gateway",
        "image": "gateway:latest",
        "status": "running",
        "health": "healthy",
        "ports": "8080 -> 80",
    },
    {
        "id": "demo-db",
        "name": "postgres-core",
        "image": "postgres:16",
        "status": "running",
        "health": "healthy",
        "ports": "5432 -> 5432",
    },
    {
        "id": "demo-worker",
        "name": "queue-worker",
        "image": "worker:v2",
        "status": "exited",
        "health": "degraded",
        "ports": "-",
    },
    {
        "id": "demo-cache",
        "name": "redis-edge",
        "image": "redis:7",
        "status": "running",
        "health": "healthy",
        "ports": "6379 -> 6379",
    },
]
ACTIVITY_LOG = [
    "Console initialisee en mode demo.",
    "Connexion Docker non detectee, fallback UI active.",
]
DOCKER_STATE = {"checked_at": 0.0, "ready": False}


# ===== USER STORE =====

def hash_password(password, salt=None):
    salt_bytes = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt_bytes, 200_000)
    return {
        "salt": base64.b64encode(salt_bytes).decode("utf-8"),
        "hash": base64.b64encode(digest).decode("utf-8"),
    }


def make_user(username, password, role="user", email=""):
    password_data = hash_password(password)
    return {
        "username": username,
        "password": password_data["hash"],
        "salt": password_data["salt"],
        "role": role,
        "email": email,
        "totp_enabled": False,
        "totp_secret": "",
    }


def verify_user_password(user, password):
    try:
        salt = base64.b64decode(user["salt"])
    except Exception:
        return False
    expected = hash_password(password, salt)["hash"]
    return secrets.compare_digest(expected, user.get("password", ""))


def public_user(user):
    return {
        "username": user["username"],
        "email": user.get("email", ""),
        "role": user.get("role", "operator"),
        "totp_enabled": bool(user.get("totp_enabled", False)),
    }


def validate_username(username):
    return bool(re.fullmatch(r"[A-Za-z0-9._-]{3,32}", username))


def normalize_role(role, default="user"):
    role = str(role or "").strip().lower()
    return role if role in ROLE_LEVELS else default


def role_level(role):
    return ROLE_LEVELS.get(normalize_role(role), -1)


def can_manage_users(actor):
    return bool(actor and role_level(actor.get("role")) >= ROLE_LEVELS["operator"])


def can_manage_target(actor, target):
    if not actor or not target:
        return False
    return role_level(actor.get("role")) > role_level(target.get("role"))


def allowed_creation_roles(actor):
    actor_role = normalize_role(actor.get("role"))
    if actor_role == "admin":
        return ["user", "operator", "admin"]
    if actor_role == "operator":
        return ["user"]
    return []


def allowed_role_updates(actor, target):
    if not can_manage_target(actor, target):
        return []
    actor_role = normalize_role(actor.get("role"))
    target_role = normalize_role(target.get("role"))
    if actor_role == "admin":
        if target_role == "operator":
            return ["user", "operator", "admin"]
        if target_role == "user":
            return ["user", "operator", "admin"]
    if actor_role == "operator" and target_role == "user":
        return ["user"]
    return []


def save_users():
    payload = {"users": sorted(USERS.values(), key=lambda item: item["username"].lower())}
    USERS_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def load_users():
    users = {}
    if USERS_FILE.exists():
        try:
            raw = json.loads(USERS_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            raw = {}
        for item in raw.get("users", []):
            username = str(item.get("username", "")).strip()
            if not username:
                continue
            users[username] = {
                "username": username,
                "password": str(item.get("password", "")),
                "salt": str(item.get("salt", "")),
                "role": normalize_role(item.get("role", "user")),
                "email": str(item.get("email", "")),
                "totp_enabled": bool(item.get("totp_enabled", False)),
                "totp_secret": str(item.get("totp_secret", "")),
            }

    if not users:
        users[AUTH_USER] = make_user(AUTH_USER, AUTH_PASSWORD, role="admin")
        save_seed = True
    else:
        save_seed = False

    if not any(user.get("role") == "admin" for user in users.values()):
        if AUTH_USER in users:
            users[AUTH_USER]["role"] = "admin"
        else:
            users[AUTH_USER] = make_user(AUTH_USER, AUTH_PASSWORD, role="admin")
        save_seed = True

    if save_seed:
        payload = {"users": sorted(users.values(), key=lambda item: item["username"].lower())}
        USERS_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    return users


USERS = load_users()


def current_user_record(headers):
    session = user_from_token(headers)
    if not session:
        return None
    return USERS.get(session.get("username", ""))


def admin_count():
    return sum(1 for user in USERS.values() if user.get("role") == "admin")


# ===== TOTP HELPERS =====

def generate_totp_secret():
    return base64.b32encode(os.urandom(20)).decode("utf-8")


def totp_code(secret, t=None):
    if t is None:
        t = int(time.time()) // 30
    key = base64.b32decode(secret, casefold=True)
    msg = struct.pack(">Q", t)
    h = hmac.new(key, msg, hashlib.sha1).digest()
    offset = h[-1] & 0xF
    code = (
        (h[offset] & 0x7F) << 24
        | h[offset + 1] << 16
        | h[offset + 2] << 8
        | h[offset + 3]
    ) % 1_000_000
    return str(code).zfill(6)


def verify_totp(secret, code):
    t = int(time.time()) // 30
    return any(
        secrets.compare_digest(totp_code(secret, t + d), str(code).zfill(6))
        for d in (-1, 0, 1)
    )


def build_qr_svg(text):
    try:
        import qrcode
        from qrcode.image.svg import SvgPathImage
    except ImportError as exc:
        raise RuntimeError("Generation QR indisponible. Lancez `pip install -r requirements.txt`.") from exc

    buffer = io.BytesIO()
    image = qrcode.make(text, image_factory=SvgPathImage, box_size=8, border=2)
    image.save(buffer)
    return buffer.getvalue().decode("utf-8")

# ===== LOGGING =====

def push_log(message):
    ACTIVITY_LOG.insert(0, message)
    del ACTIVITY_LOG[20:]


# ===== RESPONSE HELPERS =====

def json_response(handler, status, payload):
    body = json.dumps(payload).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def load_json(handler):
    try:
        length = int(handler.headers.get("Content-Length", "0"))
    except ValueError:
        return {}
    raw = handler.rfile.read(length) if length else b""
    if not raw:
        return {}
    try:
        return json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError:
        return {}


# ===== DOCKER HELPERS =====

def docker_available():
    return shutil.which("docker") is not None


def compose_file():
    for name in ("compose.yml", "compose.yaml", "docker-compose.yml", "docker-compose.yaml"):
        path = ROOT / name
        if path.exists():
            return path
    return None


def run_command(args):
    return subprocess.run(
        args,
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def docker_mode():
    now = time.monotonic()
    if now - DOCKER_STATE["checked_at"] < 5:
        return DOCKER_STATE["ready"]

    ready = False
    if docker_available():
        result = run_command(["docker", "info", "--format", "{{.ServerVersion}}"])
        ready = result.returncode == 0

    DOCKER_STATE["checked_at"] = now
    DOCKER_STATE["ready"] = ready
    return ready


def normalize_status(status):
    lower = status.lower()
    if "up" in lower or "running" in lower:
        return "running"
    if "restarting" in lower:
        return "restarting"
    if "paused" in lower:
        return "paused"
    return "exited"


def normalize_health(status):
    lower = status.lower()
    if "healthy" in lower:
        return "healthy"
    if "unhealthy" in lower:
        return "critical"
    if "starting" in lower or "restarting" in lower:
        return "degraded"
    if "up" in lower or "running" in lower:
        return "healthy"
    return "offline"


def docker_containers():
    result = run_command(
        [
            "docker",
            "ps",
            "-a",
            "--format",
            "{{.ID}}\t{{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}",
        ]
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "Impossible de recuperer les conteneurs Docker.")

    containers = []
    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        while len(parts) < 5:
            parts.append("")
        container_id, name, image, status_label, ports = parts[:5]
        containers.append(
            {
                "id": container_id,
                "name": name,
                "image": image,
                "status": normalize_status(status_label),
                "health": normalize_health(status_label),
                "ports": ports or "-",
                "statusLabel": status_label,
            }
        )
    return containers


def demo_containers():
    return [container.copy() for container in DEMO_CONTAINERS]


def current_containers():
    if docker_mode():
        try:
            return docker_containers()
        except RuntimeError as exc:
            push_log(str(exc))
    return demo_containers()


def count_summary(containers):
    running = sum(1 for item in containers if item["status"] == "running")
    stopped = sum(1 for item in containers if item["status"] in {"exited", "paused"})
    degraded = sum(1 for item in containers if item["health"] in {"degraded", "critical"})
    return {
        "total": len(containers),
        "running": running,
        "stopped": stopped,
        "degraded": degraded,
    }


def perform_demo_action(action):
    if action == "start-all":
        for item in DEMO_CONTAINERS:
            item["status"] = "running"
            item["health"] = "healthy"
        push_log("Toutes les machines de demo ont ete demarrees.")
        return "Machines de demo demarrees."
    if action == "stop-all":
        for item in DEMO_CONTAINERS:
            item["status"] = "exited"
            item["health"] = "offline"
        push_log("Toutes les machines de demo ont ete arretees.")
        return "Machines de demo arretees."
    if action == "restart-all":
        for item in DEMO_CONTAINERS:
            item["status"] = "running"
            item["health"] = "healthy"
        push_log("Toutes les machines de demo ont ete redemarrees.")
        return "Machines de demo redemarrees."
    if action == "deploy-stack":
        for item in DEMO_CONTAINERS:
            item["status"] = "running"
            item["health"] = "healthy"
        push_log("Deploiement de demo simule avec succes.")
        return "Stack de demo deployee."
    raise ValueError("Action inconnue")


def demo_container_by_id(container_id):
    for item in DEMO_CONTAINERS:
        if item["id"] == container_id:
            return item
    raise LookupError("Machine introuvable.")


def perform_demo_container_action(container_id, action):
    item = demo_container_by_id(container_id)

    if action == "start":
        item["status"] = "running"
        item["health"] = "healthy"
        push_log(f"Machine de demo {item['name']} demarree.")
        return f"{item['name']} demarree."

    if action == "stop":
        item["status"] = "exited"
        item["health"] = "offline"
        push_log(f"Machine de demo {item['name']} arretee.")
        return f"{item['name']} arretee."

    if action == "restart":
        item["status"] = "running"
        item["health"] = "healthy"
        push_log(f"Machine de demo {item['name']} redemarree.")
        return f"{item['name']} redemarree."

    raise ValueError("Action inconnue")


def docker_ids():
    containers = docker_containers()
    return [item["id"] for item in containers]


def docker_container(container_id):
    for item in docker_containers():
        if item["id"] == container_id or item["name"] == container_id:
            return item
    raise LookupError("Machine introuvable.")


def perform_docker_action(action):
    ids = docker_ids()
    if action in {"start-all", "stop-all", "restart-all"} and not ids:
        return "Aucun conteneur trouve."

    if action == "start-all":
        result = run_command(["docker", "start", *ids])
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "Le demarrage a echoue.")
        push_log("Toutes les machines Docker ont ete demarrees.")
        return "Tous les conteneurs ont ete demarres."

    if action == "stop-all":
        result = run_command(["docker", "stop", *ids])
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "L'arret a echoue.")
        push_log("Toutes les machines Docker ont ete arretees.")
        return "Tous les conteneurs ont ete arretes."

    if action == "restart-all":
        result = run_command(["docker", "restart", *ids])
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "Le redemarrage a echoue.")
        push_log("Toutes les machines Docker ont ete redemarrees.")
        return "Tous les conteneurs ont ete redemarres."

    if action == "deploy-stack":
        compose = compose_file()
        if not compose:
            raise RuntimeError("Aucun fichier compose.yml ou docker-compose.yml trouve.")
        result = run_command(["docker", "compose", "up", "-d"])
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "Le deploiement compose a echoue.")
        push_log(f"Stack Docker deployee depuis {compose.name}.")
        return f"Stack deployee depuis {compose.name}."

    raise ValueError("Action inconnue")


def perform_docker_container_action(container_id, action):
    container = docker_container(container_id)

    if action == "start":
        result = run_command(["docker", "start", container["id"]])
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "Le demarrage a echoue.")
        push_log(f"Machine Docker {container['name']} demarree.")
        return f"{container['name']} demarree."

    if action == "stop":
        result = run_command(["docker", "stop", container["id"]])
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "L'arret a echoue.")
        push_log(f"Machine Docker {container['name']} arretee.")
        return f"{container['name']} arretee."

    if action == "restart":
        result = run_command(["docker", "restart", container["id"]])
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "Le redemarrage a echoue.")
        push_log(f"Machine Docker {container['name']} redemarree.")
        return f"{container['name']} redemarree."

    raise ValueError("Action inconnue")


def dashboard_payload():
    containers = current_containers()
    summary = count_summary(containers)
    return {
        "mode": "docker" if docker_mode() else "demo",
        "composeAvailable": compose_file() is not None,
        "summary": summary,
        "containers": containers,
        "activity": ACTIVITY_LOG[:10],
    }


def get_token(headers):
    auth = headers.get("Authorization", "")
    prefix = "Bearer "
    if auth.startswith(prefix):
        return auth[len(prefix):].strip()
    return ""


def user_from_token(headers):
    token = get_token(headers)
    return SESSIONS.get(token)

def get_client_ip(handler):
    forwarded = handler.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return handler.client_address[0] if handler.client_address else "unknown"


class AppHandler(BaseHTTPRequestHandler):
    server_version = "DockerPanel/1.0"

    # ===== GET ROUTES =====

    def do_GET(self):
        parsed = urlparse(self.path)

        if parsed.path == "/api/bootstrap":
            return json_response(self, HTTPStatus.OK, dashboard_payload())

        if parsed.path == "/api/dashboard":
            user = current_user_record(self.headers)
            if not user:
                return json_response(self, HTTPStatus.UNAUTHORIZED, {"error": "Authentification requise."})
            payload = dashboard_payload()
            payload["user"] = public_user(user)
            return json_response(self, HTTPStatus.OK, payload)

        if parsed.path == "/api/2fa/status":
            user = current_user_record(self.headers)
            if not user:
                return json_response(self, HTTPStatus.UNAUTHORIZED, {"error": "Authentification requise."})
            return json_response(self, HTTPStatus.OK, {
                "totp": bool(user.get("totp_enabled", False)),
            })

        if parsed.path == "/api/2fa/totp/setup":
            user = current_user_record(self.headers)
            if not user:
                return json_response(self, HTTPStatus.UNAUTHORIZED, {"error": "Authentification requise."})
            secret = generate_totp_secret()
            PENDING_TOTP_SETUPS[user["username"]] = {
                "secret": secret,
                "expires": time.time() + 600,
            }
            username = user["username"]
            uri = (
                f"otpauth://totp/DockerManager:{username}"
                f"?secret={secret}&issuer=DockerManager&algorithm=SHA1&digits=6&period=30"
            )
            try:
                qr_svg = build_qr_svg(uri)
            except RuntimeError as exc:
                return json_response(self, HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            return json_response(self, HTTPStatus.OK, {"secret": secret, "uri": uri, "qr_svg": qr_svg})

        if parsed.path == "/api/sessions":
            token = get_token(self.headers)
            if not user_from_token(self.headers):
                return json_response(self, HTTPStatus.UNAUTHORIZED, {"error": "Authentification requise."})
            session_list = []
            for sess_token, sess_data in SESSIONS.items():
                session_list.append({
                    "token": sess_token,
                    "token_preview": sess_token[:12],
                    "username": sess_data.get("username", ""),
                    "ip": sess_data.get("ip", "unknown"),
                    "created_at": sess_data.get("created_at", 0),
                    "current": sess_token == token,
                })
            return json_response(self, HTTPStatus.OK, {"sessions": session_list})

        if parsed.path == "/api/account":
            user = current_user_record(self.headers)
            if not user:
                return json_response(self, HTTPStatus.UNAUTHORIZED, {"error": "Authentification requise."})
            return json_response(self, HTTPStatus.OK, public_user(user))

        if parsed.path == "/api/admin/users":
            actor = current_user_record(self.headers)
            if not can_manage_users(actor):
                return json_response(self, HTTPStatus.FORBIDDEN, {"error": "Acces de gestion requis."})
            users = []
            for user in sorted(USERS.values(), key=lambda item: item["username"].lower()):
                item = public_user(user)
                item["manageable"] = can_manage_target(actor, user)
                item["assignable_roles"] = allowed_role_updates(actor, user)
                users.append(item)
            return json_response(self, HTTPStatus.OK, {"users": users})

        return self.serve_static(parsed.path)

    # ===== POST ROUTES =====

    def do_POST(self):
        parsed = urlparse(self.path)

        if parsed.path == "/api/login":
            return self.handle_login()

        if parsed.path == "/api/logout":
            return self.handle_logout()

        if parsed.path == "/api/2fa/verify":
            return self.handle_2fa_verify()

        if parsed.path == "/api/2fa/totp/enable":
            return self.handle_totp_enable()

        if parsed.path == "/api/2fa/totp/disable":
            return self.handle_2fa_disable("totp")

        if parsed.path == "/api/account/email":
            return self.handle_account_email()

        if parsed.path == "/api/account/password":
            return self.handle_account_password()

        if parsed.path == "/api/admin/users":
            return self.handle_admin_user_create()

        if parsed.path == "/api/admin/users/role":
            return self.handle_admin_user_role_update()

        if parsed.path == "/api/admin/users/delete":
            return self.handle_admin_user_delete()

        if parsed.path == "/api/sessions/revoke":
            return self.handle_sessions_revoke()

        if parsed.path.startswith("/api/containers/"):
            return self.handle_container_route(parsed.path)

        if parsed.path.startswith("/api/actions/"):
            return self.handle_action(parsed.path.rsplit("/", 1)[-1])

        return json_response(self, HTTPStatus.NOT_FOUND, {"error": "Route inconnue."})

    # ===== LOGIN =====

    def handle_login(self):
        payload = load_json(self)
        username = payload.get("username", "").strip()
        password = payload.get("password", "")
        user = USERS.get(username)

        if not user or not verify_user_password(user, password):
            push_log(f"Tentative de connexion refusee pour {username or 'utilisateur inconnu'}.")
            return json_response(self, HTTPStatus.UNAUTHORIZED, {"error": "Identifiants invalides."})

        if user.get("totp_enabled") and user.get("totp_secret"):
            temp_token = secrets.token_urlsafe(32)
            PENDING_2FA[temp_token] = {
                "username": username,
                "expires": time.time() + 300,
            }
            push_log(f"A2F requise pour {username}.")
            return json_response(self, HTTPStatus.OK, {
                "2fa_required": True,
                "temp_token": temp_token,
                "methods": ["totp"],
            })

        token = secrets.token_urlsafe(24)
        SESSIONS[token] = {
            "username": username,
            "role": user.get("role", "operator"),
            "created_at": time.time(),
            "ip": get_client_ip(self),
        }
        push_log(f"Connexion acceptee pour {username}.")
        return json_response(self, HTTPStatus.OK, {
            "token": token,
            "user": public_user(user),
        })

    # ===== 2FA VERIFY (login step) =====

    def handle_2fa_verify(self):
        payload = load_json(self)
        temp_token = payload.get("temp_token", "")
        code = str(payload.get("code", "")).strip().zfill(6)

        # Validate temp token
        pending = PENDING_2FA.get(temp_token)
        if not pending:
            return json_response(self, HTTPStatus.UNAUTHORIZED, {"error": "Session temporaire invalide ou expiree."})
        if time.time() > pending["expires"]:
            del PENDING_2FA[temp_token]
            return json_response(self, HTTPStatus.UNAUTHORIZED, {"error": "Session temporaire expiree. Reconnectez-vous."})

        username = pending["username"]
        user = USERS.get(username)
        if not user or not user.get("totp_enabled") or not user.get("totp_secret"):
            del PENDING_2FA[temp_token]
            return json_response(self, HTTPStatus.UNAUTHORIZED, {"error": "A2F non configuree pour ce compte."})

        if not verify_totp(user["totp_secret"], code):
            return json_response(self, HTTPStatus.UNAUTHORIZED, {"error": "Code incorrect ou expire."})

        # Clean up pending
        del PENDING_2FA[temp_token]

        # Create real session
        token = secrets.token_urlsafe(24)
        SESSIONS[token] = {
            "username": username,
            "role": user.get("role", "operator"),
            "created_at": time.time(),
            "ip": get_client_ip(self),
        }
        push_log(f"Connexion A2F acceptee pour {username}.")
        return json_response(self, HTTPStatus.OK, {
            "token": token,
            "user": public_user(user),
        })

    # ===== TOTP =====

    def handle_totp_enable(self):
        user = current_user_record(self.headers)
        if not user:
            return json_response(self, HTTPStatus.UNAUTHORIZED, {"error": "Authentification requise."})

        payload = load_json(self)
        code = str(payload.get("code", "")).strip()
        pending = PENDING_TOTP_SETUPS.get(user["username"])

        if not pending:
            return json_response(self, HTTPStatus.BAD_REQUEST, {"error": "Aucune configuration TOTP en attente. Recommencez la configuration."})
        if time.time() > pending["expires"]:
            del PENDING_TOTP_SETUPS[user["username"]]
            return json_response(self, HTTPStatus.BAD_REQUEST, {"error": "La configuration TOTP a expire. Recommencez la configuration."})

        pending_secret = pending["secret"]

        if not verify_totp(pending_secret, code):
            return json_response(self, HTTPStatus.UNAUTHORIZED, {"error": "Code TOTP invalide."})

        user["totp_secret"] = pending_secret
        user["totp_enabled"] = True
        del PENDING_TOTP_SETUPS[user["username"]]
        save_users()
        push_log(f"TOTP active pour {user['username']}.")
        return json_response(self, HTTPStatus.OK, {"ok": True, "message": "A2F TOTP activee avec succes."})

    def handle_2fa_disable(self, method):
        user = current_user_record(self.headers)
        if not user:
            return json_response(self, HTTPStatus.UNAUTHORIZED, {"error": "Authentification requise."})

        if method != "totp":
            return json_response(self, HTTPStatus.BAD_REQUEST, {"error": "Methode inconnue."})

        user["totp_enabled"] = False
        user["totp_secret"] = ""
        PENDING_TOTP_SETUPS.pop(user["username"], None)
        save_users()
        push_log(f"TOTP desactive pour {user['username']}.")
        return json_response(self, HTTPStatus.OK, {"ok": True})

    # ===== ACCOUNT =====

    def handle_account_email(self):
        user = current_user_record(self.headers)
        if not user:
            return json_response(self, HTTPStatus.UNAUTHORIZED, {"error": "Authentification requise."})

        payload = load_json(self)
        email = payload.get("email", "").strip()
        user["email"] = email
        save_users()
        push_log(f"Email du profil mis a jour pour {user['username']}.")
        return json_response(self, HTTPStatus.OK, {"ok": True, "user": public_user(user)})

    def handle_account_password(self):
        user = current_user_record(self.headers)
        if not user:
            return json_response(self, HTTPStatus.UNAUTHORIZED, {"error": "Authentification requise."})

        payload = load_json(self)
        current = payload.get("current", "")
        new_password = payload.get("new_password", "")

        if not verify_user_password(user, current):
            return json_response(self, HTTPStatus.UNAUTHORIZED, {"error": "Mot de passe actuel incorrect."})

        if not new_password:
            return json_response(self, HTTPStatus.BAD_REQUEST, {"error": "Le nouveau mot de passe ne peut pas etre vide."})

        if len(new_password) < 6:
            return json_response(self, HTTPStatus.BAD_REQUEST, {"error": "Le mot de passe doit contenir au moins 6 caracteres."})

        password_data = hash_password(new_password)
        user["password"] = password_data["hash"]
        user["salt"] = password_data["salt"]
        save_users()
        push_log(f"Mot de passe modifie pour {user['username']}.")
        return json_response(self, HTTPStatus.OK, {"ok": True, "message": "Mot de passe modifie avec succes."})

    def handle_admin_user_create(self):
        actor = current_user_record(self.headers)
        if not actor:
            return json_response(self, HTTPStatus.UNAUTHORIZED, {"error": "Authentification requise."})
        if not can_manage_users(actor):
            return json_response(self, HTTPStatus.FORBIDDEN, {"error": "Acces de gestion requis."})

        payload = load_json(self)
        username = payload.get("username", "").strip()
        password = payload.get("password", "")
        email = payload.get("email", "").strip()
        role = normalize_role(payload.get("role", "user"), default="user")

        if not validate_username(username):
            return json_response(self, HTTPStatus.BAD_REQUEST, {"error": "Nom d'utilisateur invalide. Utilisez 3 a 32 caracteres: lettres, chiffres, point, tiret ou underscore."})
        if username in USERS:
            return json_response(self, HTTPStatus.CONFLICT, {"error": "Cet utilisateur existe deja."})
        if len(password) < 6:
            return json_response(self, HTTPStatus.BAD_REQUEST, {"error": "Le mot de passe doit contenir au moins 6 caracteres."})
        if role not in allowed_creation_roles(actor):
            return json_response(self, HTTPStatus.BAD_REQUEST, {"error": "Vous ne pouvez pas creer ce role."})

        USERS[username] = make_user(username, password, role=role, email=email)
        save_users()
        push_log(f"Utilisateur {username} cree par {actor['username']}.")
        return json_response(self, HTTPStatus.OK, {"ok": True, "user": public_user(USERS[username])})

    def handle_admin_user_role_update(self):
        actor = current_user_record(self.headers)
        if not actor:
            return json_response(self, HTTPStatus.UNAUTHORIZED, {"error": "Authentification requise."})
        if not can_manage_users(actor):
            return json_response(self, HTTPStatus.FORBIDDEN, {"error": "Acces de gestion requis."})

        payload = load_json(self)
        username = payload.get("username", "").strip()
        new_role = normalize_role(payload.get("role", "user"), default="user")
        target = USERS.get(username)

        if not target:
            return json_response(self, HTTPStatus.NOT_FOUND, {"error": "Utilisateur introuvable."})
        if username == actor["username"]:
            return json_response(self, HTTPStatus.BAD_REQUEST, {"error": "Impossible de modifier votre propre role."})
        if new_role not in allowed_role_updates(actor, target):
            return json_response(self, HTTPStatus.BAD_REQUEST, {"error": "Vous ne pouvez pas attribuer ce role a cet utilisateur."})

        old_role = target.get("role", "user")
        if old_role == new_role:
            return json_response(self, HTTPStatus.OK, {"ok": True, "user": public_user(target)})

        target["role"] = new_role
        save_users()
        for session in SESSIONS.values():
            if session.get("username") == username:
                session["role"] = new_role
        push_log(f"Role de {username} change de {old_role} vers {new_role} par {actor['username']}.")
        return json_response(self, HTTPStatus.OK, {"ok": True, "user": public_user(target)})

    def handle_admin_user_delete(self):
        actor = current_user_record(self.headers)
        if not actor:
            return json_response(self, HTTPStatus.UNAUTHORIZED, {"error": "Authentification requise."})
        if not can_manage_users(actor):
            return json_response(self, HTTPStatus.FORBIDDEN, {"error": "Acces de gestion requis."})

        payload = load_json(self)
        username = payload.get("username", "").strip()
        if username not in USERS:
            return json_response(self, HTTPStatus.NOT_FOUND, {"error": "Utilisateur introuvable."})
        if username == actor["username"]:
            return json_response(self, HTTPStatus.BAD_REQUEST, {"error": "Impossible de supprimer votre propre compte."})
        if not can_manage_target(actor, USERS[username]):
            return json_response(self, HTTPStatus.BAD_REQUEST, {"error": "Vous ne pouvez pas supprimer cet utilisateur."})
        if USERS[username].get("role") == "admin" and admin_count() <= 1:
            return json_response(self, HTTPStatus.BAD_REQUEST, {"error": "Impossible de supprimer le dernier administrateur."})

        del USERS[username]
        save_users()
        revoked_tokens = [token for token, session in SESSIONS.items() if session.get("username") == username]
        for token in revoked_tokens:
            del SESSIONS[token]
        push_log(f"Utilisateur {username} supprime par {actor['username']}.")
        return json_response(self, HTTPStatus.OK, {"ok": True})

    # ===== SESSIONS REVOKE =====

    def handle_sessions_revoke(self):
        current_token = get_token(self.headers)
        if not user_from_token(self.headers):
            return json_response(self, HTTPStatus.UNAUTHORIZED, {"error": "Authentification requise."})

        payload = load_json(self)
        token_to_revoke = payload.get("token", "")

        if token_to_revoke == current_token:
            return json_response(self, HTTPStatus.BAD_REQUEST, {"error": "Impossible de revoquer votre session courante via cette interface."})

        if token_to_revoke in SESSIONS:
            username = SESSIONS[token_to_revoke].get("username", "?")
            del SESSIONS[token_to_revoke]
            push_log(f"Session de {username} revoquee.")
            return json_response(self, HTTPStatus.OK, {"ok": True})

        return json_response(self, HTTPStatus.NOT_FOUND, {"error": "Session introuvable."})

    # ===== LOGOUT =====

    def handle_logout(self):
        token = get_token(self.headers)
        if token in SESSIONS:
            username = SESSIONS[token]["username"]
            del SESSIONS[token]
            push_log(f"Session fermee pour {username}.")
        return json_response(self, HTTPStatus.OK, {"ok": True})

    # ===== EXISTING HANDLERS =====

    def handle_action(self, action):
        user = current_user_record(self.headers)
        if not user:
            return json_response(self, HTTPStatus.UNAUTHORIZED, {"error": "Authentification requise."})

        try:
            if docker_mode():
                message = perform_docker_action(action)
            else:
                message = perform_demo_action(action)
        except ValueError:
            return json_response(self, HTTPStatus.NOT_FOUND, {"error": "Action inconnue."})
        except RuntimeError as exc:
            push_log(str(exc))
            return json_response(self, HTTPStatus.BAD_REQUEST, {"error": str(exc)})

        payload = dashboard_payload()
        payload["message"] = message
        payload["user"] = public_user(user)
        return json_response(self, HTTPStatus.OK, payload)

    def handle_container_route(self, path):
        parts = path.strip("/").split("/")
        if len(parts) != 5 or parts[:2] != ["api", "containers"] or parts[3] != "actions":
            return json_response(self, HTTPStatus.NOT_FOUND, {"error": "Route inconnue."})
        container_id = unquote(parts[2])
        action = unquote(parts[4])
        return self.handle_container_action(container_id, action)

    def handle_container_action(self, container_id, action):
        user = current_user_record(self.headers)
        if not user:
            return json_response(self, HTTPStatus.UNAUTHORIZED, {"error": "Authentification requise."})

        try:
            if docker_mode():
                message = perform_docker_container_action(container_id, action)
            else:
                message = perform_demo_container_action(container_id, action)
        except ValueError:
            return json_response(self, HTTPStatus.NOT_FOUND, {"error": "Action inconnue."})
        except LookupError as exc:
            return json_response(self, HTTPStatus.NOT_FOUND, {"error": str(exc)})
        except RuntimeError as exc:
            push_log(str(exc))
            return json_response(self, HTTPStatus.BAD_REQUEST, {"error": str(exc)})

        payload = dashboard_payload()
        payload["message"] = message
        payload["user"] = public_user(user)
        return json_response(self, HTTPStatus.OK, payload)

    def serve_static(self, path):
        requested = path.strip("/") or "index.html"
        target = (STATIC_DIR / requested).resolve()
        if STATIC_DIR not in target.parents and target != STATIC_DIR:
            return json_response(self, HTTPStatus.FORBIDDEN, {"error": "Acces refuse."})
        if target.is_dir():
            target = target / "index.html"
        if not target.exists():
            target = STATIC_DIR / "index.html"
        if not target.exists():
            return json_response(self, HTTPStatus.NOT_FOUND, {"error": "Fichier introuvable."})

        data = target.read_bytes()
        content_type = guess_type(str(target))[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format, *args):
        return


def main():
    server = ThreadingHTTPServer((HOST, PORT), AppHandler)
    print(f"Serveur actif sur http://{HOST}:{PORT}")
    server.serve_forever()


if __name__ == "__main__":
    main()
