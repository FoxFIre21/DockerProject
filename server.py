#!/usr/bin/env python3
import json
import os
import secrets
import shutil
import subprocess
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from mimetypes import guess_type
from pathlib import Path
from urllib.parse import unquote, urlparse


ROOT = Path(__file__).resolve().parent
STATIC_DIR = ROOT / "static"
HOST = "0.0.0.0"
PORT = int(os.environ.get("PORT", "9510"))
AUTH_USER = os.environ.get("APP_USER", "admin")
AUTH_PASSWORD = os.environ.get("APP_PASSWORD", "docker123")

SESSIONS = {}
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


def push_log(message):
    ACTIVITY_LOG.insert(0, message)
    del ACTIVITY_LOG[20:]


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
        "credentials": {
            "username": AUTH_USER,
            "password": AUTH_PASSWORD,
        },
    }


def get_token(headers):
    auth = headers.get("Authorization", "")
    prefix = "Bearer "
    if auth.startswith(prefix):
        return auth[len(prefix) :].strip()
    return ""


def user_from_token(headers):
    token = get_token(headers)
    return SESSIONS.get(token)


class AppHandler(BaseHTTPRequestHandler):
    server_version = "DockerPanel/1.0"

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/bootstrap":
            return json_response(self, HTTPStatus.OK, dashboard_payload())
        if parsed.path == "/api/dashboard":
            if not user_from_token(self.headers):
                return json_response(self, HTTPStatus.UNAUTHORIZED, {"error": "Authentification requise."})
            payload = dashboard_payload()
            payload["user"] = user_from_token(self.headers)
            return json_response(self, HTTPStatus.OK, payload)
        return self.serve_static(parsed.path)

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/login":
            return self.handle_login()
        if parsed.path == "/api/logout":
            return self.handle_logout()
        if parsed.path.startswith("/api/containers/"):
            return self.handle_container_route(parsed.path)
        if parsed.path.startswith("/api/actions/"):
            return self.handle_action(parsed.path.rsplit("/", 1)[-1])
        return json_response(self, HTTPStatus.NOT_FOUND, {"error": "Route inconnue."})

    def handle_login(self):
        payload = load_json(self)
        username = payload.get("username", "")
        password = payload.get("password", "")
        if username != AUTH_USER or password != AUTH_PASSWORD:
            push_log(f"Tentative de connexion refusee pour {username or 'utilisateur inconnu'}.")
            return json_response(self, HTTPStatus.UNAUTHORIZED, {"error": "Identifiants invalides."})

        token = secrets.token_urlsafe(24)
        SESSIONS[token] = {"username": username}
        push_log(f"Connexion acceptee pour {username}.")
        return json_response(
            self,
            HTTPStatus.OK,
            {
                "token": token,
                "user": {"username": username},
            },
        )

    def handle_logout(self):
        token = get_token(self.headers)
        if token in SESSIONS:
            username = SESSIONS[token]["username"]
            del SESSIONS[token]
            push_log(f"Session fermee pour {username}.")
        return json_response(self, HTTPStatus.OK, {"ok": True})

    def handle_action(self, action):
        user = user_from_token(self.headers)
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
        payload["user"] = user
        return json_response(self, HTTPStatus.OK, payload)

    def handle_container_route(self, path):
        parts = path.strip("/").split("/")
        if len(parts) != 5 or parts[:2] != ["api", "containers"] or parts[3] != "actions":
            return json_response(self, HTTPStatus.NOT_FOUND, {"error": "Route inconnue."})
        container_id = unquote(parts[2])
        action = unquote(parts[4])
        return self.handle_container_action(container_id, action)

    def handle_container_action(self, container_id, action):
        user = user_from_token(self.headers)
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
        payload["user"] = user
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
