#!/usr/bin/env python3
"""
Frappe ERP Flexible VPS Deployment
────────────────────────────────────────────────────────────────────────────────
• Choose how many environments (1-5), name them anything (dev/staging/prod/uat)
• Pick optional shared services: Mailpit (email catcher), Backup (via Ofelia)
• MariaDB lives INSIDE each env stack — fully self-contained, zero cross-stack deps
• FRAPPE_IMAGE env var so any image/registry/fork works without editing YMLs
• Auto-installs Docker on Ubuntu/Debian, auto-logs in to GHCR
• Generates ALL compose YMLs dynamically — no pre-existing stack files needed
• State file = resumable deployments

Usage:
    sudo python3 deploy-vps.py            # Fresh or resumed deploy
    sudo python3 deploy-vps.py --reset    # Wipe state, start over
    sudo python3 deploy-vps.py --status   # Show current stack status
"""

from __future__ import annotations
import os, sys, json, subprocess, argparse, getpass, logging, textwrap
from pathlib import Path
from time import sleep
from datetime import datetime
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Optional, Tuple

# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  DATA MODELS                                                                ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

@dataclass
class EnvConfig:
    name: str    # e.g. "dev", "staging", "prod" — used as stack name prefix
    domain: str  # e.g. "erp-dev.example.com"

@dataclass
class DeployConfig:
    environments:       List[EnvConfig]
    optional_services:  List[str]   # subset of ["mailpit", "backup"]
    frappe_image:       str         # e.g. "ghcr.io/org/repo" (no tag)
    tag_name:           str         # e.g. "main"
    db_root_password:   str
    letsencrypt_email:  str
    traefik_domain:     str
    portainer_domain:   str
    portainer_password: str         # set via API after portainer deploys
    mailpit_domain:     str         # only meaningful when "mailpit" in optional_services
    github_username:    str

    def to_dict(self) -> Dict:
        d = asdict(self)
        d["environments"] = [asdict(e) for e in self.environments]
        return d

    @staticmethod
    def from_dict(d: Dict) -> DeployConfig:
        d = dict(d)
        d["environments"] = [EnvConfig(**e) for e in d["environments"]]
        # back-compat: state files written before portainer_password was added
        d.setdefault("portainer_password", "")
        return DeployConfig(**d)


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  CONFIG & PATHS                                                             ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

class Config:
    BASE_DIR:   Path = Path("/opt/frappe-deploy")
    STACKS_DIR: Path = BASE_DIR / "stacks"
    LOGS_DIR:   Path = BASE_DIR / "logs"
    STATE_FILE: Path = BASE_DIR / ".deploy_state.json"

    @classmethod
    def initialize(cls, base_dir: Optional[str] = None):
        if base_dir:
            cls.BASE_DIR = Path(base_dir).resolve()
        else:
            # Place everything next to this script
            cls.BASE_DIR = Path(__file__).resolve().parent

        cls.STACKS_DIR = cls.BASE_DIR / "stacks"
        cls.LOGS_DIR   = cls.BASE_DIR / "logs"
        cls.STATE_FILE = cls.BASE_DIR / ".deploy_state.json"

        cls.STACKS_DIR.mkdir(parents=True, exist_ok=True)
        cls.LOGS_DIR.mkdir(parents=True, exist_ok=True)


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  LOGGING                                                                    ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

logger = logging.getLogger("Deploy")


def init_logging():
    fmt = logging.Formatter("%(asctime)s  %(levelname)-7s  %(message)s",
                            datefmt="%H:%M:%S")
    fh = logging.FileHandler(
        Config.LOGS_DIR / f"deploy-{datetime.now().strftime('%Y%m%d-%H%M%S')}.log"
    )
    fh.setFormatter(fmt)
    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    logger.setLevel(logging.INFO)
    logger.addHandler(fh)
    logger.addHandler(sh)


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  STATE MANAGER                                                              ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

class State:
    _data: Dict = {}

    @classmethod
    def load(cls):
        if Config.STATE_FILE.exists():
            try:
                with open(Config.STATE_FILE) as f:
                    cls._data = json.load(f)
                return
            except Exception:
                pass
        cls._data = {"started_at": None, "done": [], "config": None, "errors": []}

    @classmethod
    def save(cls):
        with open(Config.STATE_FILE, "w") as f:
            json.dump(cls._data, f, indent=2)

    @classmethod
    def done(cls, step: str) -> bool:
        return step in cls._data.get("done", [])

    @classmethod
    def mark(cls, step: str):
        if step not in cls._data["done"]:
            cls._data["done"].append(step)
        cls.save()
        logger.info(f"✓ {step}")

    @classmethod
    def error(cls, step: str, msg: str):
        cls._data["errors"].append({"step": step, "msg": msg,
                                    "at": datetime.now().isoformat()})
        cls.save()

    @classmethod
    def reset(cls):
        cls._data = {"started_at": None, "done": [], "config": None, "errors": []}
        if Config.STATE_FILE.exists():
            Config.STATE_FILE.unlink()
        logger.info("State cleared — starting fresh")


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  SHELL HELPERS                                                              ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

def sh(cmd: str, check=True, env: Dict = None,
       silent=False) -> Tuple[int, str, str]:
    run_env = {**os.environ, **(env or {})}
    r = subprocess.run(cmd, shell=True, capture_output=True,
                       text=True, executable="/bin/bash", env=run_env)
    if not silent:
        logger.debug(f"$ {cmd}")
    if check and r.returncode != 0:
        raise RuntimeError(
            f"Command failed (exit {r.returncode}):\n"
            f"  {cmd}\n  {r.stderr.strip()}"
        )
    return r.returncode, r.stdout.strip(), r.stderr.strip()


def sh_live(cmd: str, env: Dict = None) -> int:
    run_env = {**os.environ, **(env or {})}
    logger.info(f"$ {cmd}")
    return subprocess.run(cmd, shell=True, executable="/bin/bash",
                          env=run_env).returncode


def ask(prompt: str, default: str = "", required=False) -> str:
    hint = f" [{default}]" if default else (" (required)" if required else "")
    while True:
        val = input(f"  {prompt}{hint}: ").strip()
        if val:
            return val
        if default:
            return default
        if not required:
            return ""
        print("    ↑ this field is required")


def yn(prompt: str) -> bool:
    return input(f"  {prompt} (y/n): ").strip().lower() == "y"


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  DOCKER SETUP                                                               ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

class Docker:

    @staticmethod
    def ensure_installed():
        rc, _, _ = sh("docker --version", check=False, silent=True)
        if rc == 0:
            _, ver, _ = sh("docker --version", silent=True)
            logger.info(f"✓ {ver}")
            return

        logger.info("Docker not found — installing...")
        _, osinfo, _ = sh("cat /etc/os-release 2>/dev/null",
                          check=False, silent=True)
        if not any(x in osinfo.lower() for x in ("ubuntu", "debian")):
            sys.exit(
                "❌  Auto-install only supports Ubuntu/Debian.\n"
                "    Install Docker manually: https://docs.docker.com/engine/install/"
            )

        rc = sh_live("curl -fsSL https://get.docker.com | sh")
        if rc != 0:
            sys.exit("❌  Docker installation failed")

        # Add the sudoing user to docker group
        _, sudo_user, _ = sh("echo ${SUDO_USER:-}", check=False, silent=True)
        if sudo_user and sudo_user != "root":
            sh(f"usermod -aG docker {sudo_user}", check=False)
            logger.info(f"  Added {sudo_user} to docker group (re-login to apply)")

        logger.info("✅ Docker installed")

    @staticmethod
    def ensure_swarm():
        _, info, _ = sh("docker info 2>/dev/null", check=False, silent=True)
        if "Swarm: active" in info:
            logger.info("✓ Docker Swarm active")
            return
        logger.info("Initializing Docker Swarm...")
        sh("docker swarm init")
        logger.info("✅ Docker Swarm initialized")

    @staticmethod
    def create_networks():
        for net in ("traefik-public", "shared-services"):
            rc, _, _ = sh(f"docker network inspect {net}",
                          check=False, silent=True)
            if rc != 0:
                sh(f"docker network create --driver overlay --attachable {net}")
            logger.info(f"  ✓ network: {net}")

    @staticmethod
    def login(username: str, token: str):
        logger.info(f"Logging in to ghcr.io as {username} ...")
        rc = sh_live(
            f"echo '{token}' | docker login ghcr.io -u '{username}' --password-stdin"
        )
        if rc != 0:
            sys.exit("❌  GHCR login failed — check username and PAT token")
        logger.info("✅ Logged in to ghcr.io")


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  INTERACTIVE SETUP                                                          ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

class Setup:

    @staticmethod
    def gather() -> Tuple[DeployConfig, str]:
        """Interactively collect all config. Returns (DeployConfig, github_token)."""
        saved = State._data.get("config")
        if saved:
            cfg = DeployConfig.from_dict(saved)
            print(f"\n✓ Saved config found:")
            print(f"  Environments : {[e.name for e in cfg.environments]}")
            print(f"  Image        : {cfg.frappe_image}:{cfg.tag_name}")
            print(f"  Optional     : {cfg.optional_services or 'none'}")
            if yn("Use saved config?"):
                token = getpass.getpass("  GitHub PAT (for docker login): ")
                return cfg, token

        print("\n" + "━"*60)
        print("  HOW MANY ENVIRONMENTS?")
        print("━"*60)
        print("\n  Each environment = its own isolated stack")
        print("  (Frappe + MariaDB + Redis, fully self-contained)\n")

        while True:
            try:
                n = int(input("  Number of environments (1-5): ").strip())
                if 1 <= n <= 5:
                    break
            except ValueError:
                pass
            print("  Enter a number between 1 and 5")

        environments: List[EnvConfig] = []
        print(f"\n  Name each environment (common: dev, staging, prod, uat, demo)\n")

        for i in range(n):
            print(f"  ── Environment {i+1} of {n} ──")
            name = ""
            while not name or not name.replace("-", "").replace("_", "").isalnum():
                name = input("    Name (letters/numbers/hyphens): ").strip().lower()
                if not name:
                    print("    ↑ required")
            domain = ask(f"    Domain for '{name}'", required=True)
            environments.append(EnvConfig(name=name, domain=domain))
            print()

        print("━"*60)
        print("  OPTIONAL SHARED SERVICES")
        print("━"*60 + "\n")

        optional: List[str] = []
        if yn("📧 Mailpit  — shared email catcher for all environments"):
            optional.append("mailpit")
        if yn("💾 Backup   — daily scheduled backups via Ofelia cron"):
            optional.append("backup")

        mailpit_domain = ""
        if "mailpit" in optional:
            mailpit_domain = ask("\n  Mailpit domain (e.g. mailpit.example.com)",
                                 required=True)

        print("\n" + "━"*60)
        print("  CORE CONFIGURATION")
        print("━"*60 + "\n")

        frappe_image      = ask("Frappe image (no tag)",
                                "ghcr.io/brandclub/brand-club-erp")
        tag_name          = ask("Image tag", "main")
        db_root_password  = ask("MariaDB root password", "StrongPass@123!")
        letsencrypt_email = ask("Let's Encrypt email", required=True)
        traefik_domain    = ask("Traefik domain    e.g. traefik.example.com",
                                required=True)
        portainer_domain  = ask("Portainer domain  e.g. portainer.example.com",
                                required=True)
        print("  Portainer admin password (set automatically via API after deploy):")
        portainer_password = ""
        while len(portainer_password) < 12:
            portainer_password = getpass.getpass("    Password (min 12 chars): ").strip()
            if len(portainer_password) < 12:
                print("    ↑ minimum 12 characters required by Portainer")

        print("\n" + "━"*60)
        print("  GITHUB CONTAINER REGISTRY")
        print("━"*60 + "\n")

        github_username = ask("GitHub username", required=True)
        token = ""
        while not token:
            token = getpass.getpass("  GitHub PAT (read:packages scope): ").strip()
            if not token:
                print("  ↑ required")

        cfg = DeployConfig(
            environments=environments,
            optional_services=optional,
            frappe_image=frappe_image,
            tag_name=tag_name,
            db_root_password=db_root_password,
            letsencrypt_email=letsencrypt_email,
            traefik_domain=traefik_domain,
            portainer_domain=portainer_domain,
            portainer_password=portainer_password,
            mailpit_domain=mailpit_domain,
            github_username=github_username,
        )

        State._data["config"] = cfg.to_dict()
        State.save()
        print(f"\n✅ Config saved → {Config.STATE_FILE}\n")
        return cfg, token


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  COMPOSE GENERATOR  (all YMLs produced from Python — no template files)    ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

class Compose:

    @staticmethod
    def _img(cfg: DeployConfig) -> str:
        return (f"${{FRAPPE_IMAGE:-{cfg.frappe_image}}}"
                f":${{TAG_NAME:-{cfg.tag_name}}}")

    # ── Per-environment stack (Frappe + MariaDB + Redis) ──────────────────────
    @staticmethod
    def env_stack(env: EnvConfig, cfg: DeployConfig) -> str:
        n   = env.name
        img = Compose._img(cfg)
        has_mail   = "mailpit" in cfg.optional_services
        has_backup = "backup"  in cfg.optional_services

        mail_env = textwrap.dedent("""
            MAIL_SERVER: mailpit
            MAIL_PORT: "1025"
            MAIL_USE_TLS: "0"
        """).rstrip() if has_mail else ""

        # indent mail_env to sit inside environment block
        if mail_env:
            mail_env = "\n" + textwrap.indent(mail_env.strip(), "      ")

        mail_net   = "\n      - shared-services" if has_mail else ""
        shared_net_def = (
            "\n  shared-services:\n"
            "    external: true\n"
            "    name: shared-services"
        ) if has_mail else ""

        backup_svc = textwrap.dedent(f"""
          # ── Backup (replicas:0, started by Ofelia on schedule) ──────────
          backup:
            image: {img}
            deploy:
              mode: replicated
              replicas: 0
              restart_policy:
                condition: none
              placement:
                constraints:
                  - node.role == manager
              labels:
                ofelia.enabled: "true"
                ofelia.job-run.{n}-backup.schedule: "0 2 * * *"
                ofelia.job-run.{n}-backup.container: "{n}-frappe_backup"
                ofelia.job-run.{n}-backup.no-overlap: "true"
            entrypoint: ["/bin/bash", "-c"]
            command:
              - |
                set -e
                SITE="${{SITE_DOMAIN:-{env.domain}}}"
                echo "=== Backup $SITE at $(date) ==="
                cd /home/frappe/frappe-bench
                bench --site "$SITE" backup --with-files
                SRC="/home/frappe/frappe-bench/sites/$SITE/private/backups"
                DST="/backups/$SITE"
                mkdir -p "$DST"
                cp "$SRC"/*.* "$DST/" 2>/dev/null || true
                ls -t "$DST"/*-database* 2>/dev/null | tail -n +8 | while read f; do
                  rm -f "${{f%-database*}}-"* || true
                done
                echo "=== Backup done $(date) ==="
            environment:
              SITE_DOMAIN: "{env.domain}"
              DB_HOST: mariadb
              REDIS_CACHE: redis-cache:6379
              REDIS_QUEUE: redis-queue:6379
            volumes:
              - sites:/home/frappe/frappe-bench/sites
              - backups:/backups
            networks:
              - {n}-network
        """) if has_backup else ""

        backup_vol = (
            f"\n  backups:\n"
            f"    driver: local\n"
            f"    driver_opts:\n"
            f"      type: none\n"
            f"      o: bind\n"
            f"      device: ${{BACKUP_DIR:-/backups}}\n"
            f"    name: {n}-backups"
        ) if has_backup else ""

        return f"""\
version: "3.8"

# =====================================================
# FRAPPE STACK: {n.upper()}   domain: {env.domain}
# Generated by deploy-vps.py
# =====================================================

services:

  # ── Backend (Gunicorn) ──────────────────────────────────
  backend:
    image: {img}
    deploy:
      restart_policy:
        condition: on-failure
        delay: 5s
    environment:
      REDIS_CACHE: redis-cache:6379
      REDIS_QUEUE: redis-queue:6379
      DB_HOST: mariadb
      DB_PORT: "3306"
      FRAPPE_SITE_NAME_HEADER: $$host
      SOCKETIO_PORT: "9000"{mail_env}
    volumes:
      - sites:/home/frappe/frappe-bench/sites
      - logs:/home/frappe/frappe-bench/logs
    networks:
      - {n}-network{mail_net}

  # ── Frontend (Nginx + Traefik routing) ─────────────────
  frontend:
    image: {img}
    command: ["nginx-entrypoint.sh"]
    deploy:
      restart_policy:
        condition: on-failure
      labels:
        - traefik.enable=true
        - traefik.docker.network=traefik-public
        - traefik.constraint-label=traefik-public
        - traefik.http.routers.{n}-http.rule=Host(`${{{n.upper()}_DOMAIN:-{env.domain}}}`)
        - traefik.http.routers.{n}-http.entrypoints=http
        - traefik.http.routers.{n}-http.middlewares=https-redirect
        - traefik.http.routers.{n}-https.rule=Host(`${{{n.upper()}_DOMAIN:-{env.domain}}}`)
        - traefik.http.routers.{n}-https.entrypoints=https
        - traefik.http.routers.{n}-https.tls=true
        - traefik.http.routers.{n}-https.tls.certresolver=le
        - traefik.http.services.{n}-svc.loadbalancer.server.port=8080
    environment:
      BACKEND: backend:8000
      FRAPPE_SITE_NAME_HEADER: $$host
      SOCKETIO: websocket:9000
      UPSTREAM_REAL_IP_ADDRESS: 127.0.0.1
      UPSTREAM_REAL_IP_HEADER: X-Forwarded-For
      UPSTREAM_REAL_IP_RECURSIVE: "off"
      CLIENT_MAX_BODY_SIZE: ${{CLIENT_MAX_BODY_SIZE:-50m}}
    volumes:
      - sites:/home/frappe/frappe-bench/sites:ro
      - logs:/home/frappe/frappe-bench/logs
    networks:
      - {n}-network
      - traefik-public

  # ── WebSocket ────────────────────────────────────────────
  websocket:
    image: {img}
    command: ["node", "/home/frappe/frappe-bench/apps/frappe/socketio.js"]
    deploy:
      restart_policy:
        condition: on-failure
    environment:
      REDIS_QUEUE: redis-queue:6379
    volumes:
      - sites:/home/frappe/frappe-bench/sites:ro
      - logs:/home/frappe/frappe-bench/logs
    networks:
      - {n}-network

  # ── Queue Workers ─────────────────────────────────────────
  queue-default:
    image: {img}
    command: ["bench", "worker", "--queue", "default"]
    deploy:
      restart_policy:
        condition: on-failure
    environment:
      REDIS_CACHE: redis-cache:6379
      REDIS_QUEUE: redis-queue:6379
      DB_HOST: mariadb
    volumes:
      - sites:/home/frappe/frappe-bench/sites
      - logs:/home/frappe/frappe-bench/logs
    networks:
      - {n}-network

  queue-short:
    image: {img}
    command: ["bench", "worker", "--queue", "short"]
    deploy:
      restart_policy:
        condition: on-failure
    environment:
      REDIS_CACHE: redis-cache:6379
      REDIS_QUEUE: redis-queue:6379
      DB_HOST: mariadb
    volumes:
      - sites:/home/frappe/frappe-bench/sites
      - logs:/home/frappe/frappe-bench/logs
    networks:
      - {n}-network

  queue-long:
    image: {img}
    command: ["bench", "worker", "--queue", "long"]
    deploy:
      restart_policy:
        condition: on-failure
    environment:
      REDIS_CACHE: redis-cache:6379
      REDIS_QUEUE: redis-queue:6379
      DB_HOST: mariadb
    volumes:
      - sites:/home/frappe/frappe-bench/sites
      - logs:/home/frappe/frappe-bench/logs
    networks:
      - {n}-network

  # ── Scheduler ─────────────────────────────────────────────
  scheduler:
    image: {img}
    command: ["bench", "schedule"]
    deploy:
      restart_policy:
        condition: on-failure
      placement:
        constraints:
          - node.role == manager
    environment:
      REDIS_CACHE: redis-cache:6379
      REDIS_QUEUE: redis-queue:6379
      DB_HOST: mariadb
    volumes:
      - sites:/home/frappe/frappe-bench/sites
      - logs:/home/frappe/frappe-bench/logs
    networks:
      - {n}-network

  # ── Migration (run once on deploy/update, then exits) ────
  # Trigger manually: docker service scale {n}-frappe_migration=1
  migration:
    image: {img}
    deploy:
      restart_policy:
        condition: none
      placement:
        constraints:
          - node.role == manager
    entrypoint: ["bash", "-c"]
    command:
      - |
        bench --site all set-config -p maintenance_mode 1
        bench --site all set-config -p pause_scheduler 1
        bench --site all migrate
        bench --site all set-config -p maintenance_mode 0
        bench --site all set-config -p pause_scheduler 0
    environment:
      REDIS_CACHE: redis-cache:6379
      REDIS_QUEUE: redis-queue:6379
      DB_HOST: mariadb
    volumes:
      - sites:/home/frappe/frappe-bench/sites
      - logs:/home/frappe/frappe-bench/logs
    networks:
      - {n}-network
{backup_svc}
  # ── Redis Cache ───────────────────────────────────────────
  redis-cache:
    image: redis:6.2-alpine
    command: ["redis-server", "--maxmemory", "256mb",
              "--maxmemory-policy", "allkeys-lru"]
    deploy:
      restart_policy:
        condition: on-failure
    volumes:
      - redis-cache:/data
    networks:
      - {n}-network
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 5s
      retries: 3

  # ── Redis Queue ───────────────────────────────────────────
  redis-queue:
    image: redis:6.2-alpine
    command: ["redis-server", "--appendonly", "yes"]
    deploy:
      restart_policy:
        condition: on-failure
    volumes:
      - redis-queue:/data
    networks:
      - {n}-network
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 5s
      retries: 3

  # ── MariaDB (isolated per environment) ───────────────────
  mariadb:
    image: mariadb:10.6
    command:
      - --character-set-server=utf8mb4
      - --collation-server=utf8mb4_unicode_ci
      - --skip-character-set-client-handshake
      - --skip-innodb-read-only-compressed
      - --max-connections=200
      - --innodb-buffer-pool-size=512M
    deploy:
      replicas: 1
      restart_policy:
        condition: on-failure
      placement:
        constraints:
          - node.role == manager
    environment:
      MYSQL_ROOT_PASSWORD: ${{DB_ROOT_PASSWORD}}
    volumes:
      - mariadb:/var/lib/mysql
    networks:
      - {n}-network
    healthcheck:
      test: ["CMD", "mysqladmin", "ping", "-h", "localhost",
             "-p${{DB_ROOT_PASSWORD}}"]
      interval: 10s
      timeout: 5s
      retries: 5

# ── Volumes ──────────────────────────────────────────────────
volumes:
  sites:
    name: {n}-sites
  logs:
    name: {n}-logs
  redis-cache:
    name: {n}-redis-cache
  redis-queue:
    name: {n}-redis-queue
  mariadb:
    name: {n}-mariadb{backup_vol}

# ── Networks ─────────────────────────────────────────────────
networks:
  {n}-network:
    driver: overlay
    attachable: true
    name: {n}-network
  traefik-public:
    external: true
    name: traefik-public{shared_net_def}
"""

    # ── Shared services stack (Mailpit) ────────────────────────────────────────
    @staticmethod
    def shared_services(cfg: DeployConfig) -> Optional[str]:
        if "mailpit" not in cfg.optional_services:
            return None
        md = cfg.mailpit_domain
        return f"""\
version: "3.8"

# =====================================================
# SHARED SERVICES STACK
# Generated by deploy-vps.py
# =====================================================

services:

  # ── Mailpit — catches all outgoing email ─────────────────
  mailpit:
    image: axllent/mailpit:latest
    deploy:
      restart_policy:
        condition: on-failure
      placement:
        constraints:
          - node.role == manager
      labels:
        - traefik.enable=true
        - traefik.docker.network=traefik-public
        - traefik.constraint-label=traefik-public
        - traefik.http.routers.mailpit-http.rule=Host(`{md}`)
        - traefik.http.routers.mailpit-http.entrypoints=http
        - traefik.http.routers.mailpit-http.middlewares=https-redirect
        - traefik.http.routers.mailpit-https.rule=Host(`{md}`)
        - traefik.http.routers.mailpit-https.entrypoints=https
        - traefik.http.routers.mailpit-https.tls=true
        - traefik.http.routers.mailpit-https.tls.certresolver=le
        - traefik.http.services.mailpit.loadbalancer.server.port=8025
    environment:
      MP_MAX_MESSAGES: "5000"
      MP_SMTP_AUTH_ACCEPT_ANY: "1"
      MP_SMTP_AUTH_ALLOW_INSECURE: "1"
    ports:
      - target: 1025
        published: 1025
        protocol: tcp
        mode: host
    networks:
      - traefik-public
      - shared-services

networks:
  traefik-public:
    external: true
    name: traefik-public
  shared-services:
    external: true
    name: shared-services
"""

    # ── Ofelia ────────────────────────────────────────────────────────────────
    @staticmethod
    def ofelia() -> str:
        return """\
version: "3.8"

# =====================================================
# OFELIA — Docker-native cron scheduler
# Reads backup job definitions from service labels
# =====================================================

services:
  ofelia:
    image: mcuadros/ofelia:latest
    command: daemon --docker
    user: "root"
    deploy:
      restart_policy:
        condition: on-failure
      placement:
        constraints:
          - node.role == manager
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
      - ofelia-logs:/var/log/ofelia

volumes:
  ofelia-logs:
    name: ofelia-logs
"""

    # ── Traefik ────────────────────────────────────────────────────────────────
    @staticmethod
    def traefik(cfg: DeployConfig) -> str:
        return f"""\
version: "3.8"

# =====================================================
# TRAEFIK — Reverse Proxy + Let's Encrypt SSL
# =====================================================

services:
  traefik:
    image: traefik:v2.11
    command:
      - --api=true
      - --api.dashboard=true
      - --providers.docker=true
      - --providers.docker.swarmMode=true
      - --providers.docker.network=traefik-public
      - --providers.docker.exposedByDefault=false
      - --providers.docker.constraints=Label(`traefik.constraint-label`,`traefik-public`)
      - --entrypoints.http.address=:80
      - --entrypoints.https.address=:443
      - --certificatesresolvers.le.acme.email={cfg.letsencrypt_email}
      - --certificatesresolvers.le.acme.storage=/certificates/acme.json
      - --certificatesresolvers.le.acme.tlschallenge=true
      - --log.level=INFO
    deploy:
      placement:
        constraints:
          - node.role == manager
      restart_policy:
        condition: on-failure
      labels:
        - traefik.enable=true
        - traefik.docker.network=traefik-public
        - traefik.constraint-label=traefik-public
        - traefik.http.routers.traefik-dash.rule=Host(`{cfg.traefik_domain}`) && (PathPrefix(`/api`) || PathPrefix(`/dashboard`))
        - traefik.http.routers.traefik-dash.entrypoints=https
        - traefik.http.routers.traefik-dash.tls=true
        - traefik.http.routers.traefik-dash.tls.certresolver=le
        - traefik.http.routers.traefik-dash.service=api@internal
        - traefik.http.middlewares.https-redirect.redirectscheme.scheme=https
        - traefik.http.middlewares.https-redirect.redirectscheme.permanent=true
        - traefik.http.services.traefik-svc.loadbalancer.server.port=8080
    ports:
      - target: 80
        published: 80
        mode: host
      - target: 443
        published: 443
        mode: host
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
      - traefik-certs:/certificates
    networks:
      - traefik-public

volumes:
  traefik-certs:
    name: traefik-certificates

networks:
  traefik-public:
    external: true
    name: traefik-public
"""

    # ── Portainer ──────────────────────────────────────────────────────────────
    @staticmethod
    def portainer(cfg: DeployConfig) -> str:
        return f"""\
version: "3.8"

# =====================================================
# PORTAINER CE — Docker Swarm Management UI
# =====================================================

services:
  agent:
    image: portainer/agent:latest
    deploy:
      mode: global
      restart_policy:
        condition: on-failure
    environment:
      AGENT_CLUSTER_ADDR: tasks.agent
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
      - /var/lib/docker/volumes:/var/lib/docker/volumes
    networks:
      - portainer-agent

  portainer:
    image: portainer/portainer-ce:latest
    command: -H tcp://tasks.agent:9001 --tlsskipverify
    deploy:
      mode: replicated
      replicas: 1
      restart_policy:
        condition: on-failure
      placement:
        constraints:
          - node.role == manager
      labels:
        - traefik.enable=true
        - traefik.docker.network=traefik-public
        - traefik.constraint-label=traefik-public
        - traefik.http.routers.portainer-http.rule=Host(`{cfg.portainer_domain}`)
        - traefik.http.routers.portainer-http.entrypoints=http
        - traefik.http.routers.portainer-http.middlewares=https-redirect
        - traefik.http.routers.portainer-https.rule=Host(`{cfg.portainer_domain}`)
        - traefik.http.routers.portainer-https.entrypoints=https
        - traefik.http.routers.portainer-https.tls=true
        - traefik.http.routers.portainer-https.tls.certresolver=le
        - traefik.http.services.portainer.loadbalancer.server.port=9000
    volumes:
      - portainer-data:/data
    networks:
      - portainer-agent
      - traefik-public

volumes:
  portainer-data:
    name: portainer-data

networks:
  portainer-agent:
    driver: overlay
    attachable: true
    name: portainer-agent
  traefik-public:
    external: true
    name: traefik-public
"""


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  PORTAINER / CLEANUP / VALIDATION HELPERS                                   ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

def portainer_init_password(domain: str, password: str) -> bool:
    """
    Set the Portainer admin password via its initialisation API.
    Only works before the first login (endpoint returns 409 if already set).
    Uses HTTP to port 9000 directly to avoid waiting for SSL cert.
    """
    import urllib.request, urllib.error, ssl

    # Try HTTPS first (cert might be ready), fall back to insecure
    urls = [
        f"https://{domain}/api/users/admin/init",
        # Direct port access in case Traefik isn't routing yet
    ]

    data    = json.dumps({"Username": "admin", "Password": password}).encode()
    ctx     = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode    = ssl.CERT_NONE

    logger.info(f"  Setting Portainer admin password via API ...")
    deadline = datetime.now().timestamp() + 180   # 3 min for portainer to start

    while datetime.now().timestamp() < deadline:
        for url in urls:
            req = urllib.request.Request(
                url, data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, context=ctx, timeout=8) as resp:
                    if resp.status in (200, 204):
                        logger.info("  ✓ Portainer admin password set via API")
                        return True
            except urllib.error.HTTPError as e:
                if e.code == 409:
                    logger.info("  ✓ Portainer already initialised (password exists)")
                    return True
                logger.debug(f"  Portainer API {e.code}: {e.reason}")
            except Exception as e:
                logger.debug(f"  Portainer not ready yet: {type(e).__name__}")
        sleep(6)

    logger.warning(
        f"  ⚠  Could not reach Portainer API after 3min.\n"
        f"  Set the password manually at: https://{domain}\n"
        f"  You have 5 minutes from when Portainer first starts."
    )
    return False


def cleanup_existing_stacks():
    """
    Detect existing Docker stacks and offer to remove them.
    Requires typed confirmation to prevent accidental deletion.
    """
    _, out, _ = sh("docker stack ls --format '{{.Name}}'",
                   check=False, silent=True)
    if not out:
        return   # nothing to clean

    stacks = [s for s in out.splitlines() if s.strip()]
    if not stacks:
        return

    print(f"\n  ⚠  Existing Docker stacks detected:")
    for s in stacks:
        _, svc_count, _ = sh(
            f"docker stack services {s} --format '{{{{.Name}}}}' 2>/dev/null | wc -l",
            check=False, silent=True,
        )
        print(f"    • {s}  ({svc_count.strip()} services)")

    print()
    if not yn("Remove ALL existing stacks before deploying?"):
        logger.info("  Keeping existing stacks — continuing")
        return

    print(
        f"\n  ⚠  WARNING: This will stop and remove all listed stacks.\n"
        f"  Named volumes (your database and site data) will NOT be deleted.\n"
        f"\n  Type exactly the following to confirm:\n"
        f"    yes, remove all stacks\n"
    )
    typed = input("  > ").strip()

    if typed != "yes, remove all stacks":
        print("  Confirmation did not match — skipping cleanup.")
        return

    print()
    for stack in stacks:
        logger.info(f"  Removing stack: {stack} ...")
        sh(f"docker stack rm {stack}", check=False)

    logger.info("  ⏳ Waiting 20s for all services to stop ...")
    sleep(20)
    logger.info("  ✓ Cleanup complete")


def validate_no_conflicts(cfg: DeployConfig) -> bool:
    """
    Check that none of the configured stack names or site domains
    already exist before attempting deployment.
    Returns True if clean, False if conflicts found.
    """
    _, stack_out, _ = sh("docker stack ls --format '{{.Name}}'",
                         check=False, silent=True)
    existing_stacks = set(stack_out.splitlines()) if stack_out else set()

    _, vol_out, _ = sh("docker volume ls --format '{{.Name}}'",
                       check=False, silent=True)
    existing_vols = set(vol_out.splitlines()) if vol_out else set()

    conflicts: List[str] = []

    for env in cfg.environments:
        app_stack  = f"{env.name}-frappe"
        sites_vol  = f"{env.name}-sites"

        if app_stack in existing_stacks:
            conflicts.append(
                f"Stack '{app_stack}' already exists — "
                f"use --reset or clean up first"
            )
        if sites_vol in existing_vols:
            conflicts.append(
                f"Volume '{sites_vol}' already exists — "
                f"site '{env.domain}' may already be deployed"
            )

    for shared in ("traefik", "portainer"):
        if shared in existing_stacks:
            conflicts.append(
                f"Stack '{shared}' already exists — "
                f"it will be updated in place (not an error)"
            )

    if conflicts:
        print(f"\n  ⚠  CONFLICTS DETECTED before deployment:")
        for c in conflicts:
            flag = "ERROR" if "already exists — use" in c else "NOTE"
            print(f"    [{flag}] {c}")

        errors = [c for c in conflicts if "ERROR" in c]
        if errors:
            print(
                f"\n  Re-run with --reset to wipe state, or answer 'y' at the\n"
                f"  cleanup prompt at startup to remove conflicting stacks."
            )
            return False

    return True




class Deployer:

    def __init__(self, cfg: DeployConfig):
        self.cfg = cfg
        # Environment variables passed to every `docker stack deploy`
        self.env = {
            "FRAPPE_IMAGE":      cfg.frappe_image,
            "TAG_NAME":          cfg.tag_name,
            "DB_ROOT_PASSWORD":  cfg.db_root_password,
            "BACKUP_DIR":        "/backups",
        }
        for e in cfg.environments:
            self.env[f"{e.name.upper()}_DOMAIN"] = e.domain

    # ── Write a YML and deploy it as a stack ──────────────────────────────────
    def deploy_stack(self, stack_name: str, yml: str,
                     filename: str, wait: int = 8):
        path = Config.STACKS_DIR / filename
        path.write_text(yml)
        logger.info(f"  Wrote {path.name} → deploying as '{stack_name}' ...")

        rc = sh_live(
            f"docker stack deploy --with-registry-auth -c {path} {stack_name}",
            env=self.env,
        )
        if rc != 0:
            raise RuntimeError(f"Stack deploy failed: {stack_name}")

        logger.info(f"  ⏳ Settling ({wait}s) ...")
        sleep(wait)

    # ── Poll until service reaches 1/1 replicas ────────────────────────────────
    def wait_for(self, service: str, timeout: int = 900) -> bool:
        logger.info(f"  Waiting for {service} (up to {timeout//60}min) ...")
        deadline = datetime.now().timestamp() + timeout
        bad_state_count = 0   # consecutive checks showing terminal state
        last_reported   = ""

        while datetime.now().timestamp() < deadline:
            # ── Check desired vs running replicas ──────────────────────────
            _, replicas, _ = sh(
                f"docker service ls --filter name={service} "
                f"--format '{{{{.Replicas}}}}'",
                check=False, silent=True,
            )
            if replicas.startswith("1/1"):
                logger.info(f"  ✓ {service} ready")
                return True

            # ── Check individual task state ────────────────────────────────
            # In Swarm, container names are dynamic, but task state is stable.
            # "Complete" for a long-running service = process exited (bad).
            # "Preparing/Starting/Running" = normal startup.
            _, task_state, _ = sh(
                f"docker service ps {service} --no-trunc "
                f"--format '{{{{.CurrentState}}}}' 2>/dev/null | head -1",
                check=False, silent=True,
            )
            state_lower = task_state.lower()

            if any(s in state_lower for s in ("complete", "failed", "rejected")):
                bad_state_count += 1
                if bad_state_count >= 3:
                    # Consistently in terminal state — not going to self-heal
                    logger.error(
                        f"\n  ✗ {service} is in '{task_state}' state — "
                        f"it started and exited instead of staying running.\n"
                        f"  This usually means the container CMD failed or no site exists yet.\n"
                        f"  Last 30 lines of logs:"
                    )
                    sh_live(f"docker service logs {service} --tail 30 2>&1")
                    return False
            else:
                bad_state_count = 0   # reset on any non-terminal state

            # ── Progress indicator (throttled) ────────────────────────────
            if task_state and task_state != last_reported:
                remaining = int(deadline - datetime.now().timestamp())
                logger.info(f"  ... {service}: {task_state}  ({remaining}s remaining)")
                last_reported = task_state

            sleep(8)

        logger.warning(f"  ⚠  {service} not ready after {timeout}s")
        return False

    # ── Get backend container ID for a stack ──────────────────────────────────
    def get_backend(self, stack: str) -> str:
        _, cid, _ = sh(
            f"docker ps "
            f"--filter 'label=com.docker.swarm.service.name={stack}_backend' "
            f"--format '{{{{.ID}}}}' | head -1",
            silent=True,
        )
        if not cid:
            raise RuntimeError(f"No running backend found in stack '{stack}'")
        return cid

    # ── Create Frappe site and install apps ────────────────────────────────────
    def setup_site(self, env: EnvConfig):
        stack = f"{env.name}-frappe"
        site  = env.domain

        if State.done(f"site_{env.name}"):
            logger.info(f"  ↩  {site} already set up — skipping")
            return

        if not self.wait_for(f"{stack}_backend"):
            raise RuntimeError(f"Backend never came up for {env.name}")

        cid = self.get_backend(stack)

        def bench_exec(cmd: str):
            sh(f'docker exec {cid} bash -c '
               f'"cd /home/frappe/frappe-bench && {cmd}"',
               check=False)

        # ── Global config (MUST happen before bench new-site) ────────────────
        logger.info("  Setting global bench config ...")
        for key, val in [
            ("db_host",       "mariadb"),
            ("redis_cache",   "redis://redis-cache:6379"),
            ("redis_queue",   "redis://redis-queue:6379"),
            ("socketio_port", "9000"),
        ]:
            bench_exec(f'bench set-config -g {key} "{val}"')

        if "mailpit" in self.cfg.optional_services:
            for key, val in [
                ("mail_server", "mailpit"),
                ("mail_port",   "1025"),
                ("use_tls",     "0"),
            ]:
                bench_exec(f'bench set-config -g {key} "{val}"')

        sleep(2)

        # ── Create site ───────────────────────────────────────────────────────
        logger.info(f"  Creating site {site} ...")
        rc, _, stderr = sh(
            f'docker exec {cid} bash -c '
            f'"cd /home/frappe/frappe-bench && '
            f'bench new-site {site} --db-host=mariadb --db-port=3306"',
            check=False,
        )
        if rc != 0 and "already exists" not in stderr.lower():
            raise RuntimeError(f"bench new-site failed:\n{stderr[:400]}")

        # ── Install apps ──────────────────────────────────────────────────────
        # Edit this list to match your apps
        apps = "insights drive brand_club"
        logger.info(f"  Installing apps: {apps} ...")
        sh(
            f'docker exec {cid} bash -c '
            f'"cd /home/frappe/frappe-bench && '
            f'bench install-app --site {site} {apps}"',
            check=False,
        )

        State.mark(f"site_{env.name}")
        logger.info(f"  ✅ {env.name.upper()} → https://{site}")

    # ── Main orchestration ────────────────────────────────────────────────────
    def run(self):
        cfg = self.cfg

        # Guard: refuse to deploy over existing stacks (unless user cleaned up)
        if not validate_no_conflicts(cfg):
            logger.error("Resolve conflicts above before continuing.")
            sys.exit(1)

        # Step 1 — Traefik
        if not State.done("traefik"):
            logger.info("\n── 1  Traefik ────────────────────────────────────────")
            self.deploy_stack("traefik", Compose.traefik(cfg),
                              "traefik.yml", wait=12)
            State.mark("traefik")

        # Step 2 — Portainer
        if not State.done("portainer"):
            logger.info("\n── 2  Portainer ──────────────────────────────────────")
            self.deploy_stack("portainer", Compose.portainer(cfg),
                              "portainer.yml", wait=15)
            logger.info(f"  📍 https://{cfg.portainer_domain}")

        if not State.done("portainer_password"):
            portainer_init_password(cfg.portainer_domain, cfg.portainer_password)
            State.mark("portainer_password")

        if not State.done("portainer"):
            State.mark("portainer")

        # Step 3 — Environment stacks (all-in-one per env)
        logger.info("\n── 3  Environment stacks (Frappe + MariaDB + Redis) ─────")
        for env in cfg.environments:
            step = f"stack_{env.name}"
            if State.done(step):
                logger.info(f"  ↩  {env.name} already deployed")
                continue
            self.deploy_stack(
                f"{env.name}-frappe",
                Compose.env_stack(env, cfg),
                f"{env.name}.yml",
                wait=10,
            )
            State.mark(step)

        logger.info("  ⏳ Waiting 30s for MariaDB to finish initialising ...")
        sleep(30)

        # Step 4 — Shared services (Mailpit)
        if not State.done("shared_services"):
            logger.info("\n── 4  Shared services ────────────────────────────────")
            yml = Compose.shared_services(cfg)
            if yml:
                self.deploy_stack("shared-services", yml,
                                  "shared-services.yml", wait=10)
            State.mark("shared_services")

        # Step 5 — Ofelia (backup cron)
        if "backup" in cfg.optional_services and not State.done("ofelia"):
            logger.info("\n── 5  Ofelia cron ────────────────────────────────────")
            self.deploy_stack("ofelia", Compose.ofelia(),
                              "ofelia.yml", wait=10)
            State.mark("ofelia")
        elif "backup" not in cfg.optional_services:
            State.mark("ofelia")

        # Step 6 — Frappe sites
        logger.info("\n── 6  Frappe site setup ──────────────────────────────────")
        for env in cfg.environments:
            try:
                self.setup_site(env)
            except Exception as e:
                logger.error(f"  ❌ {env.name}: {e}")
                State.error(f"site_{env.name}", str(e))

        self._summary()

    def _summary(self):
        cfg = self.cfg
        opt = cfg.optional_services
        lines = [
            f"\n{'═'*62}",
            "🎉  DEPLOYMENT COMPLETE",
            f"{'═'*62}\n",
            f"  Traefik   → https://{cfg.traefik_domain}",
            f"  Portainer → https://{cfg.portainer_domain}",
        ]
        if "mailpit" in opt:
            lines.append(f"  Mailpit   → https://{cfg.mailpit_domain}")
        lines.append("\n  Environments:")
        for e in cfg.environments:
            lines.append(f"    {e.name:12s} → https://{e.domain}")
        lines += [
            f"\n  Image: {cfg.frappe_image}:{cfg.tag_name}",
            "  (set FRAPPE_IMAGE or TAG_NAME to swap image/fork/version)\n",
            "  Generated stack YMLs:",
        ]
        for p in sorted(Config.STACKS_DIR.glob("*.yml")):
            lines.append(f"    {p}")
        lines += [
            f"\n  State → {Config.STATE_FILE}",
            f"  Logs  → {Config.LOGS_DIR}",
            f"{'═'*62}",
        ]
        logger.info("\n".join(lines))


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  STATUS COMMAND                                                             ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

def print_status():
    State.load()
    d = State._data
    print(f"\nStarted   : {d.get('started_at', 'never')}")
    print(f"Completed : {d.get('done', [])}")
    if d.get("errors"):
        print("\nErrors:")
        for e in d["errors"]:
            print(f"  [{e['step']}] {e['msg'][:120]}")
    print("\n── Docker stacks ──")
    sh_live("docker stack ls")
    print("\n── Services ──")
    sh_live("docker service ls")


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  ENTRY POINT                                                                ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

BANNER = r"""
╔══════════════════════════════════════════════════════════════╗
║        Frappe ERP Flexible VPS Deployment                   ║
║                                                             ║
║  • Generates all compose YMLs dynamically                   ║
║  • Auto-installs Docker • Auto GHCR login                   ║
║  • MariaDB isolated per environment                         ║
║  • Optional: Mailpit, Backup                                ║
╚══════════════════════════════════════════════════════════════╝
"""


def main():
    p = argparse.ArgumentParser(description="Frappe ERP multi-env VPS deployer")
    p.add_argument("--reset",    action="store_true",
                   help="Clear state and start fresh")
    p.add_argument("--status",   action="store_true",
                   help="Show current deployment status and exit")
    p.add_argument("--base-dir", default=None,
                   help="Override base directory (default: directory of this script)")
    args = p.parse_args()

    Config.initialize(args.base_dir)
    init_logging()

    if args.status:
        print_status()
        return

    print(BANNER)
    State.load()

    if args.reset:
        State.reset()

    # ── Offer to clean up before we touch anything ─────────────────────────
    cleanup_existing_stacks()

    if not State._data.get("started_at"):
        State._data["started_at"] = datetime.now().isoformat()
        State.save()

    # Docker setup (install + swarm + networks)
    if not State.done("docker_setup"):
        logger.info("── Docker prerequisites ──────────────────────────────────")
        Docker.ensure_installed()
        Docker.ensure_swarm()
        Docker.create_networks()
        State.mark("docker_setup")

    # Gather config interactively
    cfg, token = Setup.gather()

    # GHCR login (token not stored — always required fresh)
    if not State.done("ghcr_login"):
        Docker.login(cfg.github_username, token)
        State.mark("ghcr_login")

    # Deploy everything
    deployer = Deployer(cfg)
    try:
        deployer.run()
    except KeyboardInterrupt:
        logger.info("\n⚠  Interrupted — re-run to resume from last completed step")
        sys.exit(0)
    except Exception as e:
        logger.error(f"\n❌  Fatal: {e}")
        logger.exception("Traceback:")
        sys.exit(1)


if __name__ == "__main__":
    main()