#!/usr/bin/env python3
"""
Frappe ERP — Complete Interactive VPS Setup
Handles everything: packages → Docker → Swarm → Traefik → Portainer → Environments → Sites

Run as root:  sudo python3 setup.py
Resume:       sudo python3 setup.py
Reset:        sudo python3 setup.py --reset
Status:       sudo python3 setup.py --status
"""

import os, sys, json, subprocess, getpass, argparse
from pathlib import Path
from time import sleep
from datetime import datetime
from typing import List
from dataclasses import dataclass, asdict

# ─── Terminal colours ──────────────────────────────────────────────────────────

BOLD   = "\033[1m"
GREEN  = "\033[92m"
CYAN   = "\033[96m"
YELLOW = "\033[93m"
RED    = "\033[91m"
DIM    = "\033[2m"
RESET  = "\033[0m"

W = 64  # line width for headers

def header(title: str, subtitle: str = ""):
    print(f"\n{CYAN}{'═' * W}{RESET}")
    print(f"{BOLD}{CYAN}  {title}{RESET}")
    if subtitle:
        print(f"{DIM}  {subtitle}{RESET}")
    print(f"{CYAN}{'─' * W}{RESET}\n")

def ok(msg):    print(f"  {GREEN}✓{RESET}  {msg}")
def warn(msg):  print(f"  {YELLOW}⚠{RESET}  {msg}")
def fail(msg):  print(f"  {RED}✗{RESET}  {msg}")
def info(msg):  print(f"  {DIM}·{RESET}  {msg}")
def step(msg):  print(f"\n  {BOLD}▶{RESET}  {BOLD}{msg}{RESET}")


# ─── Interactive prompts ───────────────────────────────────────────────────────

def ask(prompt: str, default: str = "", secret: bool = False) -> str:
    suffix = f" {DIM}[{default}]{RESET}" if default else ""
    display = f"  {BOLD}{prompt}{RESET}{suffix}: "
    while True:
        val = (getpass.getpass(display) if secret else input(display).strip())
        result = val if val else default
        if result:
            return result
        print(f"  {RED}Required — cannot be empty.{RESET}")


def confirm(prompt: str, default: bool = True) -> bool:
    yn = f"{GREEN}Y{RESET}/n" if default else f"y/{RED}N{RESET}"
    raw = input(f"  {BOLD}{prompt}{RESET} ({yn}): ").strip().lower()
    return default if not raw else raw in ("y", "yes")


# ─── Shell execution ───────────────────────────────────────────────────────────

CMD_TIMEOUT = 900  # 15 minutes

def run(cmd: str, check: bool = True, silent: bool = False, timeout: int = CMD_TIMEOUT) -> tuple:
    if not silent:
        print(f"  {DIM}$ {cmd}{RESET}")
    try:
        r = subprocess.run(
            cmd, shell=True, capture_output=True, text=True,
            executable="/bin/bash", timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"Command timed out after {timeout}s:\n  {cmd[:120]}")
    if check and r.returncode != 0:
        raise RuntimeError(f"Command failed (exit {r.returncode}):\n  {r.stderr.strip()}")
    return r.returncode, r.stdout.strip(), r.stderr.strip()


def run_live(cmd: str, timeout: int = CMD_TIMEOUT) -> int:
    print(f"  {DIM}$ {cmd}{RESET}")
    try:
        return subprocess.run(cmd, shell=True, executable="/bin/bash", timeout=timeout).returncode
    except subprocess.TimeoutExpired:
        fail(f"Live command timed out after {timeout}s")
        return 1


# ─── Version management ────────────────────────────────────────────────────────

# Pinned versions — confirmed on Docker Hub (Feb 2026)
# Traefik:  v3.6.9 — https://hub.docker.com/_/traefik/tags
# Portainer: 2.33.6 — https://hub.docker.com/r/portainer/portainer-ce/tags
# resolve_versions() will auto-upgrade these if a newer tag is found at runtime.
_TRAEFIK_MIN   = "v3.6.9"
_PORTAINER_MIN = "2.33.6"

# Runtime resolved versions (updated by resolve_versions())
TRAEFIK_VERSION   = _TRAEFIK_MIN
PORTAINER_VERSION = _PORTAINER_MIN


def _parse_ver(v: str) -> tuple:
    """Convert 'v3.6.1' or '2.21.5' to comparable tuple."""
    try:
        parts = v.lstrip("v").split(".")
        nums  = [int(x) for x in parts[:3]]
        return tuple(nums + [0] * (3 - len(nums)))
    except Exception:
        return (0, 0, 0)


def _github_latest(repo: str) -> str:
    """Fetch latest release tag from GitHub API. Returns '' on any failure."""
    rc, out, _ = run(
        f"curl -sf --max-time 8 "
        f"'https://api.github.com/repos/{repo}/releases/latest' | "
        f"python3 -c \"import sys,json; print(json.load(sys.stdin).get('tag_name',''))\" 2>/dev/null",
        check=False, silent=True, timeout=20,
    )
    return out.strip() if (rc == 0 and out.strip()) else ""


def resolve_versions():
    """Best-effort: fetch latest Traefik/Portainer releases. Never downgrade."""
    global TRAEFIK_VERSION, PORTAINER_VERSION

    info("Checking for newer Traefik / Portainer releases (best-effort)…")

    t = _github_latest("traefik/traefik")
    if t and _parse_ver(t) > _parse_ver(_TRAEFIK_MIN):
        TRAEFIK_VERSION = t if t.startswith("v") else f"v{t}"
        ok(f"Traefik:   {TRAEFIK_VERSION}  (upgraded from {_TRAEFIK_MIN})")
    else:
        TRAEFIK_VERSION = _TRAEFIK_MIN
        info(f"Traefik:   {TRAEFIK_VERSION}  (pinned — no newer release found)")

    p = _github_latest("portainer/portainer-ce")
    if p and _parse_ver(p) > _parse_ver(_PORTAINER_MIN):
        PORTAINER_VERSION = p.lstrip("v")
        ok(f"Portainer: {PORTAINER_VERSION}  (upgraded from {_PORTAINER_MIN})")
    else:
        PORTAINER_VERSION = _PORTAINER_MIN
        info(f"Portainer: {PORTAINER_VERSION}  (pinned — no newer release found)")


# ─── Data classes ─────────────────────────────────────────────────────────────

@dataclass
class TraefikConfig:
    domain: str
    email: str
    hashed_password: str   # already $$ escaped for YAML


@dataclass
class PortainerConfig:
    enabled: bool
    domain: str = ""
    admin_password: str = ""   # plain-text; used once via API, not stored long-term


@dataclass
class EnvConfig:
    stack_name: str           # user-supplied, e.g. "prod"
    domain: str               # Traefik routing domain, e.g. "erp.example.com"
    image: str                # registry/org/repo  (no tag)
    tag: str                  # image tag
    db_root_password: str
    site_name: str = ""       # Frappe bench site name — MUST match domain (HTTP Host header)
    site_admin_password: str = ""  # Frappe site admin login password
    has_mailpit: bool = False
    mailpit_domain: str = ""
    has_backup: bool = False
    backup_dir: str = "/backups"

    @property
    def db_stack_name(self) -> str:   return f"{self.stack_name}-mariadb"
    @property
    def db_network(self) -> str:      return f"{self.stack_name}-mariadb"
    @property
    def app_network(self) -> str:     return f"{self.stack_name}-network"
    @property
    def full_image(self) -> str:      return f"{self.image}:{self.tag}"


# ─── State management ─────────────────────────────────────────────────────────

BASE_DIR   = Path("/opt/frappe-deploy")
STATE_FILE = BASE_DIR / ".setup_state.json"
STACKS_DIR = BASE_DIR / "stacks"
LOGS_DIR   = BASE_DIR / "logs"

EMPTY_STATE: dict = {
    "started_at": None,
    "completed": [],
    "errors": [],
    "traefik": {},
    "portainer": {},
    "environments": [],
    "github_username": "",
}


def state_load() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except json.JSONDecodeError:
            warn("State file corrupted — starting fresh.")
    s = dict(EMPTY_STATE)
    s["started_at"] = datetime.now().isoformat()
    return s


def state_save(s: dict):
    STATE_FILE.write_text(json.dumps(s, indent=2))


def state_done(s: dict, key: str):
    if key not in s["completed"]:
        s["completed"].append(key)
    state_save(s)
    ok(f"Step '{key}' complete")


def state_error(s: dict, key: str, msg: str):
    s["errors"].append({"step": key, "error": msg, "time": datetime.now().isoformat()})
    state_save(s)


def is_done(s: dict, key: str) -> bool:
    return key in s["completed"]


# ─── System setup ─────────────────────────────────────────────────────────────

def check_root():
    if os.geteuid() != 0:
        fail("This script must be run as root.  Try:  sudo python3 setup.py")
        sys.exit(1)


def install_packages():
    step("Installing system packages")
    packages = "curl openssl ca-certificates gnupg lsb-release apt-transport-https"
    run_live(f"apt-get update -qq && apt-get install -y {packages}")
    ok("System packages installed")


def install_docker():
    step("Installing Docker CE")
    rc, out, _ = run("docker --version", check=False, silent=True)
    if rc == 0:
        ok(f"Docker already installed: {out}")
        return
    info("Adding Docker GPG key and repository…")
    run("install -m 0755 -d /etc/apt/keyrings")
    run("curl -fsSL https://download.docker.com/linux/ubuntu/gpg | "
        "gpg --dearmor -o /etc/apt/keyrings/docker.gpg && chmod a+r /etc/apt/keyrings/docker.gpg")
    run(
        'echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] '
        'https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" | '
        'tee /etc/apt/sources.list.d/docker.list > /dev/null'
    )
    run_live("apt-get update -qq && apt-get install -y "
             "docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin")
    run("systemctl enable docker && systemctl start docker")
    ok("Docker CE installed and started")


def add_user_to_docker_group():
    """Add the invoking (sudo) user to the docker group so they can run docker without sudo."""
    step("Adding user to docker group")
    sudo_user = os.environ.get("SUDO_USER", "").strip()
    if not sudo_user:
        warn("SUDO_USER not set — cannot determine which user to add. Skipping.")
        warn("Run manually:  usermod -aG docker <your-username>")
        return
    rc, _, err = run(f"usermod -aG docker {sudo_user}", check=False)
    if rc == 0:
        ok(f"User '{sudo_user}' added to 'docker' group")
        info("Changes take effect after the user logs out and back in (or: newgrp docker)")
    else:
        warn(f"Could not add '{sudo_user}' to docker group: {err[:120]}")


def init_swarm():
    step("Initialising Docker Swarm")
    _, info_out, _ = run("docker info 2>/dev/null", silent=True, check=False)
    if "Swarm: active" in info_out:
        ok("Docker Swarm already active")
        return
    run("docker swarm init")
    ok("Docker Swarm initialised")


def create_shared_networks():
    step("Creating shared overlay networks")
    for net in ("traefik-public",):
        rc, _, _ = run(f"docker network inspect {net}", check=False, silent=True)
        if rc == 0:
            ok(f"Network '{net}' already exists")
        else:
            run(f"docker network create --driver overlay --attachable {net}")
            ok(f"Network '{net}' created")


def docker_login(username: str, token: str):
    step("Logging in to GitHub Container Registry")
    result = subprocess.run(
        ["docker", "login", "ghcr.io", "-u", username, "--password-stdin"],
        input=token, capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"docker login failed: {result.stderr.strip()}")
    ok(f"Logged in to ghcr.io as '{username}'")


# ─── Startup: detect & clean existing stacks ──────────────────────────────────

def check_and_cleanup_existing_stacks(state: dict):
    """If Docker stacks already exist, offer a full teardown with typed confirmation."""
    rc, out, _ = run("docker stack ls --format '{{.Name}}' 2>/dev/null", check=False, silent=True)
    if rc != 0 or not out.strip():
        return  # nothing running or Docker not up yet

    existing = [s.strip() for s in out.splitlines() if s.strip()]
    if not existing:
        return

    print(f"\n  {YELLOW}{'─' * 60}{RESET}")
    warn(f"Existing Docker stacks detected:")
    for s in existing:
        print(f"      {DIM}•{RESET}  {s}")
    print(f"  {YELLOW}{'─' * 60}{RESET}\n")

    if not confirm("Do you want to remove ALL existing stacks and start completely fresh?",
                   default=False):
        info("Keeping existing stacks. Continuing…")
        return

    # ── Typed double-confirmation ──────────────────────────────────────────────
    CONFIRM_PHRASE = "yes delete everything"
    print(f"\n  {RED}{BOLD}⚠  DANGER ZONE  ⚠{RESET}")
    print(f"  {RED}This will permanently destroy all stacks, containers, and their data.{RESET}")
    print(f"  To proceed, type exactly (case-sensitive):  {BOLD}{CONFIRM_PHRASE}{RESET}\n")
    typed = input(f"  Your confirmation: ").strip()

    if typed != CONFIRM_PHRASE:
        warn(f"Phrase did not match — cleanup cancelled. Existing stacks preserved.")
        return

    # ── Proceed with teardown ──────────────────────────────────────────────────
    step("Removing all existing stacks…")
    for s in existing:
        run(f"docker stack rm {s}", check=False)
        ok(f"Removed stack: {s}")

    info("Waiting 25s for containers to fully shut down…")
    sleep(25)

    # Clean up any dangling volumes if user wants
    if confirm("Also prune unused Docker volumes?", default=False):
        run("docker volume prune -f", check=False)
        ok("Unused volumes pruned")

    # Reset state file
    if STATE_FILE.exists():
        STATE_FILE.unlink()
    state.clear()
    state.update(dict(EMPTY_STATE))
    state["started_at"] = datetime.now().isoformat()
    state_save(state)
    ok("State reset — starting fresh")
    print()


# ─── Validation ───────────────────────────────────────────────────────────────

def validate_env_uniqueness(envs: List[EnvConfig]) -> bool:
    """
    Enforce:
      - No two environments share a stack_name
      - No two environments share a site domain
      - No two environments share a mailpit domain (if enabled)
      - None of the above clash with currently deployed Docker stacks
    Returns True if all checks pass, False otherwise.
    """
    all_ok = True

    # ── Check within the collected list ───────────────────────────────────────
    seen_stacks:  dict = {}
    seen_domains: dict = {}
    seen_mailpit: dict = {}

    for e in envs:
        # stack_name
        if e.stack_name in seen_stacks:
            fail(f"Duplicate stack name '{e.stack_name}' — each environment must be unique.")
            all_ok = False
        else:
            seen_stacks[e.stack_name] = True

        # site domain
        if e.domain in seen_domains:
            fail(f"Duplicate site domain '{e.domain}' — each environment needs its own domain.")
            all_ok = False
        else:
            seen_domains[e.domain] = e.stack_name

        # mailpit domain
        if e.has_mailpit and e.mailpit_domain:
            if e.mailpit_domain in seen_mailpit:
                fail(f"Duplicate mailpit domain '{e.mailpit_domain}'.")
                all_ok = False
            elif e.mailpit_domain in seen_domains:
                fail(f"Mailpit domain '{e.mailpit_domain}' conflicts with a site domain.")
                all_ok = False
            else:
                seen_mailpit[e.mailpit_domain] = e.stack_name

        # mailpit domain must not equal site domain
        if e.has_mailpit and e.mailpit_domain == e.domain:
            fail(f"Mailpit domain cannot be the same as the site domain for '{e.stack_name}'.")
            all_ok = False

    # ── Check against live Docker stacks ──────────────────────────────────────
    rc, out, _ = run("docker stack ls --format '{{.Name}}' 2>/dev/null", check=False, silent=True)
    if rc == 0 and out.strip():
        live_stacks = set(out.splitlines())
        for e in envs:
            if e.stack_name in live_stacks:
                warn(f"App stack '{e.stack_name}' already exists in Docker Swarm. "
                     f"It will be updated (re-deployed).")
            if e.db_stack_name in live_stacks:
                warn(f"DB stack '{e.db_stack_name}' already exists in Docker Swarm. "
                     f"It will be updated (re-deployed).")

    return all_ok


# ─── Interactive configuration collectors ─────────────────────────────────────

def collect_traefik() -> TraefikConfig:
    header("Traefik Setup", "Reverse proxy and automatic SSL certificates")

    domain = ask("Dashboard domain", "traefik.example.com")
    email  = ask("Let's Encrypt email", "admin@example.com")

    print(f"\n  {BOLD}Dashboard password{RESET}  (protects the Traefik UI)")
    while True:
        pw  = ask("Password", secret=True)
        pw2 = ask("Confirm", secret=True)
        if pw == pw2:
            break
        print(f"  {RED}Passwords do not match — try again.{RESET}")

    r = subprocess.run(["openssl", "passwd", "-apr1", pw], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError("openssl passwd failed — is openssl installed?")

    hashed = r.stdout.strip().replace("$", "$$")
    ok(f"Domain:  {domain}")
    ok(f"Email:   {email}")
    ok("Password hashed with APR1-MD5")
    print(f"\n  {YELLOW}⚠  Note your Traefik dashboard credentials:{RESET}")
    print(f"       Username:  admin")
    print(f"       Password:  {BOLD}(the password you just entered){RESET}")
    print(f"  {DIM}  These cannot be recovered from state. If lost, --reset and re-run.{RESET}\n")
    return TraefikConfig(domain=domain, email=email, hashed_password=hashed)


def collect_portainer() -> PortainerConfig:
    header("Portainer Setup", "Optional web UI for managing Docker Swarm stacks")
    if not confirm("Install Portainer?", default=True):
        info("Skipping Portainer.")
        return PortainerConfig(enabled=False)

    domain = ask("Portainer domain", "portainer.example.com")

    print(f"\n  {BOLD}Admin password{RESET}  (will be set automatically via API after deployment)")
    while True:
        pw  = ask("Admin password", secret=True)
        pw2 = ask("Confirm password", secret=True)
        if pw == pw2:
            break
        print(f"  {RED}Passwords do not match — try again.{RESET}")

    ok(f"Domain: {domain}")
    ok("Admin password will be configured automatically after Portainer starts")
    return PortainerConfig(enabled=True, domain=domain, admin_password=pw)


DEFAULT_IMAGE = "ghcr.io/frappe/frappe-docker"


def collect_environments() -> tuple:
    """Returns (List[EnvConfig], github_username, github_token)."""
    header("Docker Image & Registry", "Used for all Frappe app containers")

    image = ask("Frappe image  (registry/org/repo, no tag)", DEFAULT_IMAGE)
    tag   = ask("Image tag", "main")

    print(f"\n  {BOLD}GitHub Container Registry credentials{RESET}")
    print(f"  {DIM}Needed to pull private images from ghcr.io{RESET}")
    github_user  = ask("GitHub username")
    github_token = ask("GitHub PAT (read:packages)", secret=True)

    print(f"\n  {BOLD}Database{RESET}")
    while True:
        db_pass  = ask("MariaDB root password", secret=True)
        db_pass2 = ask("Confirm password", secret=True)
        if db_pass == db_pass2:
            break
        print(f"  {RED}Passwords do not match.{RESET}")

    header("Environments", "Configure each deployment environment (e.g. prod, staging, dev)")

    while True:
        try:
            n = int(ask("Number of environments to deploy (1–4)", "1"))
            if 1 <= n <= 4:
                break
            print(f"  {RED}Enter a number between 1 and 4.{RESET}")
        except ValueError:
            print(f"  {RED}Please enter a valid number.{RESET}")

    envs: List[EnvConfig] = []
    used_names:   set = set()
    used_domains: set = set()

    for i in range(n):
        print(f"\n  {CYAN}{'─' * 50}{RESET}")
        print(f"  {BOLD}Environment {i + 1} of {n}{RESET}\n")

        # ── Stack name — must be unique ────────────────────────────────────────
        while True:
            name = ask("  Stack name (e.g. prod, staging, dev)").lower().replace(" ", "-")
            if name in used_names:
                print(f"  {RED}Stack name '{name}' already used in this session.{RESET}")
            else:
                used_names.add(name)
                break

        # ── Site domain — must be unique ───────────────────────────────────────
        while True:
            domain_default = f"erp-{name}.example.com"
            domain = ask("  Routing domain (Traefik Host rule)", domain_default)
            if domain in used_domains:
                print(f"  {RED}Domain '{domain}' is already assigned to another environment.{RESET}")
            else:
                used_domains.add(domain)
                break

        # ── Frappe site name — defaults to domain, must match HTTP Host header ──
        print(f"  {DIM}  Site name is what bench uses as the site folder name.{RESET}")
        print(f"  {DIM}  It must match the domain above (browsers send it as the Host header).{RESET}")
        site_name = ask("  Frappe site name", domain)
        if site_name != domain:
            warn(f"  Site name '{site_name}' differs from domain '{domain}'.")
            warn(f"  Make sure FRAPPE_SITE_NAME_HEADER in your image config handles this.")

        # ── Frappe site admin password ─────────────────────────────────────────
        print(f"\n  {BOLD}Frappe site admin password{RESET}  (for logging in to the ERP at {domain})")
        while True:
            sp  = ask("  Site admin password", secret=True)
            sp2 = ask("  Confirm password", secret=True)
            if sp == sp2:
                site_admin_password = sp
                break
            print(f"  {RED}Passwords do not match.{RESET}")

        print(f"\n  {BOLD}Optional services for '{name}':{RESET}")

        has_mailpit    = confirm("  Add Mailpit (SMTP testing UI)?", default=False)
        mailpit_domain = ""
        if has_mailpit:
            while True:
                md = ask("    Mailpit domain", f"mail-{name}.example.com")
                if md == domain:
                    print(f"  {RED}Mailpit domain cannot be the same as the site domain.{RESET}")
                elif md in used_domains:
                    print(f"  {RED}Domain '{md}' already in use.{RESET}")
                else:
                    used_domains.add(md)
                    mailpit_domain = md
                    break

        print(f"  {DIM}  Backup uses Ofelia (shared cron scheduler) — deployed once if any env enables it.{RESET}")
        has_backup  = confirm("  Add automated daily backup?",
                              default=(name in ("prod", "main", "production")))
        backup_dir  = ask("    Backup directory on host", "/backups") if has_backup else "/backups"

        envs.append(EnvConfig(
            stack_name=name,
            domain=domain,
            site_name=site_name,
            site_admin_password=site_admin_password,
            image=image,
            tag=tag,
            db_root_password=db_pass,
            has_mailpit=has_mailpit,
            mailpit_domain=mailpit_domain,
            has_backup=has_backup,
            backup_dir=backup_dir,
        ))
        site_label = f" site={site_name}" if site_name != domain else ""
        ok(f"'{name}' → {domain}{site_label}"
           + (f" + mailpit @ {mailpit_domain}" if has_mailpit else "")
           + (" + backup" if has_backup else ""))

    return envs, github_user, github_token


# ─── YAML generators ──────────────────────────────────────────────────────────

def gen_traefik_yml(cfg: TraefikConfig) -> str:
    return f"""\
version: "3.8"
services:
  traefik:
    image: traefik:{TRAEFIK_VERSION}
    deploy:
      replicas: 1
      restart_policy:
        condition: on-failure
      placement:
        constraints:
          - node.role == manager
      labels:
        - "traefik.enable=true"
        - "traefik.constraint-label=traefik-public"
        - "traefik.swarm.network=traefik-public"
        - "traefik.http.middlewares.admin-auth.basicauth.users=admin:{cfg.hashed_password}"
        - "traefik.http.middlewares.https-redirect.redirectscheme.scheme=https"
        - "traefik.http.middlewares.https-redirect.redirectscheme.permanent=true"
        - "traefik.http.routers.traefik-http.rule=Host(`{cfg.domain}`)"
        - "traefik.http.routers.traefik-http.entrypoints=http"
        - "traefik.http.routers.traefik-http.middlewares=https-redirect"
        - "traefik.http.routers.traefik-https.rule=Host(`{cfg.domain}`)"
        - "traefik.http.routers.traefik-https.entrypoints=https"
        - "traefik.http.routers.traefik-https.tls=true"
        - "traefik.http.routers.traefik-https.tls.certresolver=le"
        - "traefik.http.routers.traefik-https.service=api@internal"
        - "traefik.http.routers.traefik-https.middlewares=admin-auth"
        - "traefik.http.services.traefik.loadbalancer.server.port=8080"
    command:
      # Swarm provider — the only provider needed in a Swarm-mode deployment.
      # Do NOT mix --providers.docker here; that is the standalone Docker provider
      # and causes duplicate-route noise in v3.6.x when Swarm mode is active.
      - --providers.swarm.endpoint=unix:///var/run/docker.sock
      - --providers.swarm.exposedbydefault=false
      - --providers.swarm.constraints=Label(`traefik.constraint-label`,`traefik-public`)
      - --entrypoints.http.address=:80
      - --entrypoints.https.address=:443
      - --certificatesresolvers.le.acme.email={cfg.email}
      - --certificatesresolvers.le.acme.storage=/certificates/acme.json
      - --certificatesresolvers.le.acme.tlschallenge=true
      - --log.level=INFO
      - --accesslog
      - --api
    ports:
      - target: 80
        published: 80
        mode: host
      - target: 443
        published: 443
        mode: host
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
      - traefik-certificates:/certificates
    networks:
      - traefik-public

volumes:
  traefik-certificates:
    name: traefik-certificates

networks:
  traefik-public:
    external: true
    name: traefik-public
"""


def gen_portainer_yml(cfg: PortainerConfig) -> str:
    pv = PORTAINER_VERSION
    return f"""\
version: "3.8"
services:
  agent:
    image: portainer/agent:{pv}
    deploy:
      mode: global
      restart_policy:
        condition: on-failure
      placement:
        constraints:
          - node.platform.os == linux
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
      - /var/lib/docker/volumes:/var/lib/docker/volumes
    networks:
      - portainer-agent

  portainer:
    image: portainer/portainer-ce:{pv}
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
        - "traefik.enable=true"
        - "traefik.swarm.network=traefik-public"
        - "traefik.constraint-label=traefik-public"
        - "traefik.http.routers.portainer-http.rule=Host(`{cfg.domain}`)"
        - "traefik.http.routers.portainer-http.entrypoints=http"
        - "traefik.http.routers.portainer-http.middlewares=https-redirect"
        - "traefik.http.routers.portainer-https.rule=Host(`{cfg.domain}`)"
        - "traefik.http.routers.portainer-https.entrypoints=https"
        - "traefik.http.routers.portainer-https.tls=true"
        - "traefik.http.routers.portainer-https.tls.certresolver=le"
        - "traefik.http.services.portainer.loadbalancer.server.port=9000"
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


def gen_database_yml(cfg: EnvConfig) -> str:
    is_prod     = cfg.stack_name in ("prod", "main", "production", "live")
    mem_limit   = "2G"   if is_prod else "1G"
    mem_reserve = "1G"   if is_prod else "256M"
    buffer_pool = "1G"   if is_prod else "256M"
    log_size    = "512M" if is_prod else "128M"

    return f"""\
version: "3.8"
# Database stack for environment: {cfg.stack_name}
services:
  mariadb:
    image: mariadb:10.6
    deploy:
      replicas: 1
      restart_policy:
        condition: on-failure
      placement:
        constraints:
          - node.role == manager
      resources:
        limits:
          memory: {mem_limit}
        reservations:
          memory: {mem_reserve}
    command:
      - --character-set-server=utf8mb4
      - --collation-server=utf8mb4_unicode_ci
      - --skip-character-set-client-handshake
      - --skip-innodb-read-only-compressed
      - --max-connections=500
      - --innodb-buffer-pool-size={buffer_pool}
      - --innodb-log-file-size={log_size}
      - --innodb-flush-log-at-trx-commit=2
      - --innodb-flush-method=O_DIRECT
      - --slow-query-log=1
      - --slow-query-log-file=/var/lib/mysql/slow.log
      - --long-query-time=2
    environment:
      MYSQL_ROOT_PASSWORD: {cfg.db_root_password}
    volumes:
      - mariadb-data:/var/lib/mysql
    networks:
      - {cfg.db_network}
    healthcheck:
      test: ["CMD", "mysqladmin", "ping", "-h", "localhost", "-p{cfg.db_root_password}"]
      interval: 10s
      timeout: 5s
      retries: 5

volumes:
  mariadb-data:
    name: {cfg.stack_name}-mariadb-data

networks:
  {cfg.db_network}:
    name: {cfg.db_network}
    driver: overlay
    attachable: true
"""


def _backup_script(domain: str) -> str:
    return (
        "set -e\n"
        f'SITE="{domain}"\n'
        'TARGET="/backups/$$SITE"\n'
        'mkdir -p "$$TARGET"\n'
        'echo "=== Backup started: $$(date) ==="\n'
        "cd /home/frappe/frappe-bench\n"
        'bench --site "$$SITE" backup --with-files || {{ echo "ERROR: bench backup failed" >&2; exit 1; }}\n'
        'SRC="/home/frappe/frappe-bench/sites/$$SITE/private/backups"\n'
        'LATEST=$$(ls -t "$$SRC" | grep database | head -1)\n'
        '[ -z "$$LATEST" ] && echo "ERROR: No backup file produced" >&2 && exit 1\n'
        'PREFIX=$$(echo "$$LATEST" | sed \'s/-database.*//\')\n'
        'cp "$$SRC/$$PREFIX-"* "$$TARGET/"\n'
        'cd "$$TARGET"\n'
        'ls -t *-database* 2>/dev/null | tail -n +8 | while read OLD; do\n'
        '  P=$$(echo "$$OLD" | sed \'s/-database.*//\')\n'
        '  rm -f "$$P-"* 2>/dev/null || true\n'
        'done\n'
        'echo "Current backups:"\n'
        'ls -lh "$$TARGET" | grep database | tail -10 || true\n'
        'echo "=== Backup complete: $$(date) ==="'
    )


def _mailpit_service(cfg: EnvConfig) -> str:
    sn = cfg.stack_name
    return f"""
  # ── Mailpit SMTP Testing UI ──
  mailpit:
    image: axllent/mailpit:latest
    deploy:
      restart_policy:
        condition: on-failure
      labels:
        - "traefik.enable=true"
        - "traefik.swarm.network=traefik-public"
        - "traefik.constraint-label=traefik-public"
        - "traefik.http.routers.{sn}-mailpit-http.rule=Host(`{cfg.mailpit_domain}`)"
        - "traefik.http.routers.{sn}-mailpit-http.entrypoints=http"
        - "traefik.http.routers.{sn}-mailpit-http.middlewares=https-redirect"
        - "traefik.http.routers.{sn}-mailpit-https.rule=Host(`{cfg.mailpit_domain}`)"
        - "traefik.http.routers.{sn}-mailpit-https.entrypoints=https"
        - "traefik.http.routers.{sn}-mailpit-https.tls=true"
        - "traefik.http.routers.{sn}-mailpit-https.tls.certresolver=le"
        - "traefik.http.services.{sn}-mailpit.loadbalancer.server.port=8025"
    networks:
      - {cfg.app_network}
      - traefik-public
"""


def _backup_service(cfg: EnvConfig) -> str:
    sn  = cfg.stack_name
    img = cfg.full_image
    script_lines = _backup_script(cfg.domain).split("\n")
    indented = "\n".join("        " + ln for ln in script_lines)
    return f"""
  # ── Backup Service (triggered by Ofelia — normally replicas=0) ──
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
        ofelia.job-run.{sn}-backup.schedule: "0 2 * * *"
        ofelia.job-run.{sn}-backup.container: "{sn}_backup"
        ofelia.job-run.{sn}-backup.no-overlap: "true"
    entrypoint: ["/bin/bash", "-c"]
    command:
      - |
{indented}
    environment:
      REDIS_CACHE: redis-cache:6379
      REDIS_QUEUE: redis-queue:6379
      DB_HOST: mariadb
    volumes:
      - sites:/home/frappe/frappe-bench/sites
      - backups:/backups
    networks:
      - {cfg.app_network}
      - {cfg.db_network}
"""


def gen_app_yml(cfg: EnvConfig) -> str:
    sn  = cfg.stack_name
    an  = cfg.app_network
    dn  = cfg.db_network
    img = cfg.full_image

    optional_services = ""
    if cfg.has_mailpit:
        optional_services += _mailpit_service(cfg)
    if cfg.has_backup:
        optional_services += _backup_service(cfg)

    backup_volume = (
        f"\n  backups:\n"
        f"    driver: local\n"
        f"    driver_opts:\n"
        f"      type: none\n"
        f"      o: bind\n"
        f"      device: {cfg.backup_dir}\n"
        f"    name: {sn}-backups\n"
    ) if cfg.has_backup else ""

    return f"""\
version: "3.8"
# ── Application stack: {sn} ──────────────────────────────────────────
# Domain:  {cfg.domain}
# Image:   {img}
# DB:      {dn}
# Mailpit: {'yes → ' + cfg.mailpit_domain if cfg.has_mailpit else 'no'}
# Backup:  {'daily 02:00 → ' + cfg.backup_dir if cfg.has_backup else 'no'}
# ─────────────────────────────────────────────────────────────────────

services:

  # ── Gunicorn / Frappe backend ──
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
      SOCKETIO_PORT: "9000"
    volumes:
      - sites:/home/frappe/frappe-bench/sites
      - logs:/home/frappe/frappe-bench/logs
    networks:
      - {an}
      - {dn}

  # ── Nginx frontend — exposed via Traefik ──
  frontend:
    image: {img}
    command: ["nginx-entrypoint.sh"]
    deploy:
      restart_policy:
        condition: on-failure
      labels:
        - "traefik.enable=true"
        - "traefik.swarm.network=traefik-public"
        - "traefik.constraint-label=traefik-public"
        - "traefik.http.routers.{sn}-http.rule=Host(`{cfg.domain}`)"
        - "traefik.http.routers.{sn}-http.entrypoints=http"
        - "traefik.http.routers.{sn}-http.middlewares=https-redirect"
        - "traefik.http.routers.{sn}-https.rule=Host(`{cfg.domain}`)"
        - "traefik.http.routers.{sn}-https.entrypoints=https"
        - "traefik.http.routers.{sn}-https.tls=true"
        - "traefik.http.routers.{sn}-https.tls.certresolver=le"
        - "traefik.http.routers.{sn}-https.middlewares={sn}-sec"
        - "traefik.http.services.{sn}.loadbalancer.server.port=8080"
        - "traefik.http.services.{sn}.loadbalancer.sticky.cookie=true"
        - "traefik.http.services.{sn}.loadbalancer.sticky.cookie.name={sn}_lb"
        - "traefik.http.middlewares.{sn}-sec.headers.stsSeconds=31536000"
        - "traefik.http.middlewares.{sn}-sec.headers.stsIncludeSubdomains=true"
        - "traefik.http.middlewares.{sn}-sec.headers.stsPreload=true"
        - "traefik.http.middlewares.{sn}-sec.headers.frameDeny=true"
        - "traefik.http.middlewares.{sn}-sec.headers.contentTypeNosniff=true"
        - "traefik.http.middlewares.{sn}-sec.headers.browserXssFilter=true"
    environment:
      BACKEND: backend:8000
      FRAPPE_SITE_NAME_HEADER: $$host
      SOCKETIO: websocket:9000
      UPSTREAM_REAL_IP_ADDRESS: 127.0.0.1
      UPSTREAM_REAL_IP_HEADER: X-Forwarded-For
      UPSTREAM_REAL_IP_RECURSIVE: "off"
      CLIENT_MAX_BODY_SIZE: 100m
    volumes:
      - sites:/home/frappe/frappe-bench/sites:ro
      - logs:/home/frappe/frappe-bench/logs
    networks:
      - {an}
      - traefik-public

  # ── WebSocket (real-time) ──
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
      - {an}

  # ── Background workers ──
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
      - {an}
      - {dn}

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
      - {an}
      - {dn}

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
      - {an}
      - {dn}

  # ── Frappe scheduler ──
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
      - {an}
      - {dn}

  # ── One-shot migration runner (restart_policy: none = runs once, then done) ──
  migration:
    image: {img}
    deploy:
      replicas: 1
      restart_policy:
        condition: none
      placement:
        constraints:
          - node.role == manager
    entrypoint: ["/bin/bash", "-c"]
    command:
      - |
        bench --site all set-config -p maintenance_mode 1
        bench --site all set-config -p pause_scheduler 1
        bench --site all migrate
        bench --site all set-config -p maintenance_mode 0
        bench --site all set-config -p pause_scheduler 0
    volumes:
      - sites:/home/frappe/frappe-bench/sites
      - logs:/home/frappe/frappe-bench/logs
    networks:
      - {an}
      - {dn}

  # ── Redis cache ──
  redis-cache:
    image: redis:6.2-alpine
    command: ["redis-server", "--maxmemory", "512mb", "--maxmemory-policy", "allkeys-lru"]
    deploy:
      restart_policy:
        condition: on-failure
    volumes:
      - redis-cache-data:/data
    networks:
      - {an}
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 5s
      retries: 3

  # ── Redis queue (persistent) ──
  redis-queue:
    image: redis:6.2-alpine
    command: ["redis-server", "--appendonly", "yes", "--appendfsync", "everysec"]
    deploy:
      restart_policy:
        condition: on-failure
    volumes:
      - redis-queue-data:/data
    networks:
      - {an}
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 5s
      retries: 3
{optional_services}
volumes:
  sites:
    name: {sn}-sites
  logs:
    name: {sn}-logs
  redis-cache-data:
    name: {sn}-redis-cache
  redis-queue-data:
    name: {sn}-redis-queue
{backup_volume}
networks:
  {an}:
    name: {an}
    driver: overlay
    attachable: true

  {dn}:
    external: true
    name: {dn}

  traefik-public:
    external: true
    name: traefik-public
"""


def gen_ofelia_yml() -> str:
    return """\
version: "3.8"
# Ofelia — Docker-native cron scheduler
services:
  ofelia:
    image: mcuadros/ofelia:latest
    command: daemon --docker
    user: "root"
    deploy:
      replicas: 1
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


# ─── File writing ──────────────────────────────────────────────────────────────

def write_stacks(
    traefik_cfg: TraefikConfig,
    portainer_cfg: PortainerConfig,
    envs: List[EnvConfig],
) -> dict:
    STACKS_DIR.mkdir(parents=True, exist_ok=True)
    files = {}

    def write(name: str, content: str) -> Path:
        path = STACKS_DIR / name
        path.write_text(content)
        ok(f"Generated {path.relative_to(BASE_DIR)}")
        files[name] = path
        return path

    step("Generating stack YAML files")
    write("traefik.yml", gen_traefik_yml(traefik_cfg))

    if portainer_cfg.enabled:
        write("portainer.yml", gen_portainer_yml(portainer_cfg))

    needs_ofelia = any(cfg.has_backup for cfg in envs)
    for cfg in envs:
        write(f"database-{cfg.stack_name}.yml", gen_database_yml(cfg))
        write(f"{cfg.stack_name}.yml",           gen_app_yml(cfg))
        if cfg.has_backup:
            Path(cfg.backup_dir).mkdir(parents=True, exist_ok=True)

    if needs_ofelia:
        write("ofelia.yml", gen_ofelia_yml())
        ok("Ofelia shared scheduler: will be deployed (≥1 environment uses backup)")
    else:
        info("Ofelia shared scheduler: NOT generated — no environment uses backup")

    return files


# ─── Stack deployment ──────────────────────────────────────────────────────────

def deploy_stack(stack_name: str, yml_path: Path, wait: int = 8):
    if not yml_path.exists():
        raise FileNotFoundError(f"Stack file missing: {yml_path}")
    run(f"docker stack deploy --with-registry-auth -c {yml_path} {stack_name}")
    info(f"Waiting {wait}s for '{stack_name}' to stabilise…")
    sleep(wait)
    ok(f"Stack '{stack_name}' deployed")


def wait_for_service(stack_name: str, service: str, timeout: int = 120) -> bool:
    info(f"Waiting for {stack_name}_{service} to be ready (max {timeout}s)…")
    deadline = datetime.now().timestamp() + timeout
    while datetime.now().timestamp() < deadline:
        _, out, _ = run(
            f"docker service ls --filter name={stack_name}_{service} --format '{{{{.Replicas}}}}'",
            check=False, silent=True,
        )
        if out.startswith("1/1"):
            ok(f"{service} is ready")
            return True
        sleep(6)
    warn(f"{service} not ready after {timeout}s — check: docker service logs {stack_name}_{service}")
    return False


def get_backend_container(stack_name: str) -> str:
    _, cid, _ = run(
        f"docker ps --filter 'label=com.docker.swarm.service.name={stack_name}_backend' "
        f"--format '{{{{.ID}}}}' | head -1",
        silent=True,
    )
    if not cid:
        raise RuntimeError(f"No running backend container for '{stack_name}'")
    return cid


# ─── Portainer password via API ────────────────────────────────────────────────

def set_portainer_admin_password(domain: str, password: str):
    """
    Set Portainer admin password by calling the init API from INSIDE the container.

    Why inside the container:
      - Calling via https://domain requires DNS to resolve + Let's Encrypt cert to
        be issued, neither of which is guaranteed immediately after deploy.
      - The portainer container is Alpine-based and has busybox wget available.
      - We docker-cp a JSON payload in, then wget to localhost:9000 from inside.
    """
    step("Configuring Portainer admin password via API")

    # ── 1. Wait for the portainer container to be running (up to 15 min) ──────
    info("Waiting for Portainer container to start (up to 15 min)…")
    cid = ""
    deadline = datetime.now().timestamp() + 900
    while datetime.now().timestamp() < deadline:
        _, out, _ = run(
            "docker ps --filter 'label=com.docker.swarm.service.name=portainer_portainer' "
            "--format '{{.ID}}' | head -1",
            check=False, silent=True,
        )
        cid = out.strip()
        if cid:
            ok(f"Portainer container found: {cid[:12]}")
            break
        sleep(10)

    if not cid:
        warn("Portainer container did not start within 15 min.")
        warn(f"Set the admin password manually at: https://{domain}")
        return

    # ── 2. Wait for Portainer's internal HTTP API on localhost:9000 ───────────
    info("Waiting for Portainer API to be ready inside container…")
    api_ready = False
    api_deadline = datetime.now().timestamp() + 120
    while datetime.now().timestamp() < api_deadline:
        rc, _, _ = run(
            f"docker exec {cid} sh -c "
            f"'wget -q -O /dev/null --timeout=4 http://localhost:9000/api/status'",
            check=False, silent=True, timeout=12,
        )
        if rc == 0:
            api_ready = True
            ok("Portainer API is responding")
            break
        sleep(8)

    if not api_ready:
        warn("Portainer API still not responding after 2 min — attempting password set anyway…")

    # ── 3. Copy JSON payload into container, POST via wget inside container ───
    payload_host = Path("/tmp/portainer_init.json")
    payload_host.write_text(json.dumps({"Username": "admin", "Password": password}))

    try:
        run(f"docker cp {payload_host} {cid}:/tmp/portainer_init.json",
            check=False, silent=True)

        rc, out, err = run(
            f"docker exec {cid} sh -c "
            f"'wget -q -O- "
            f"--post-file=/tmp/portainer_init.json "
            f"--header=\"Content-Type: application/json\" "
            f"http://localhost:9000/api/users/admin/init'",
            check=False, timeout=30,
        )
    finally:
        payload_host.unlink(missing_ok=True)

    if out and '"jwt"' in out:
        ok("Portainer admin password set successfully")
    elif "409" in (out + err) or "already" in out.lower() or "already" in err.lower():
        info("Portainer admin already initialised — password unchanged")
    elif rc == 0 and out.strip():
        ok("Portainer password API responded (password configured)")
    else:
        warn(f"Automatic password set failed (rc={rc}): {(err or out or 'no response')[:160]}")
        warn(f"Please set it manually at: https://{domain}")


# ─── Frappe site setup ─────────────────────────────────────────────────────────

FRAPPE_APPS = ["erpnext"]


def frappe_set_config(container: str):
    bench = "cd /home/frappe/frappe-bench && bench"
    configs = [
        ("db_host",       "mariadb"),
        ("redis_cache",   "redis://redis-cache:6379"),
        ("redis_queue",   "redis://redis-queue:6379"),
        ("socketio_port", "9000"),
    ]
    for key, val in configs:
        run(f'docker exec {container} bash -c \'{bench} set-config -g {key} "{val}"\'',
            check=False, silent=True)
    ok("Bench global config set")


def frappe_site_exists(container: str, site: str) -> bool:
    """Verify the site directory actually exists inside the container."""
    rc, out, _ = run(
        f'docker exec {container} bash -c '
        f'"[ -d /home/frappe/frappe-bench/sites/{site} ] && echo SITE_EXISTS || echo SITE_MISSING"',
        check=False, silent=True,
    )
    return "SITE_EXISTS" in out


def frappe_create_site(container: str, site: str,
                       db_root_password: str, site_admin_password: str) -> bool:
    info(f"Creating site: {site}")

    # If the site directory already exists, skip creation
    if frappe_site_exists(container, site):
        ok(f"Site '{site}' already exists — skipping creation")
        return True

    # Build --install-app flags for every app in FRAPPE_APPS
    # bench new-site installs 'frappe' automatically; list additional apps here.
    install_flags = " ".join(f"--install-app {app}" for app in FRAPPE_APPS) if FRAPPE_APPS else ""

    # Full bench new-site command:
    #   --db-host / --db-port       → point at the mariadb container
    #   --db-root-password          → needed to create the site DB and user
    #   --admin-password            → sets the Frappe /login admin password
    #   --mariadb-user-host-login-scope=% → allow DB user to connect from any container IP
    #   --install-app <app>         → install apps atomically during site creation
    bench_cmd = (
        f"cd /home/frappe/frappe-bench && "
        f"bench new-site {site} "
        f"--db-host mariadb "
        f"--db-port 3306 "
        f"--db-root-password {db_root_password} "
        f"--admin-password {site_admin_password} "
        f"--mariadb-user-host-login-scope=% "
        f"{install_flags}"
    ).strip()

    rc, _, err = run(
        f"docker exec {container} bash -c \"{bench_cmd}\"",
        check=False,
    )

    if rc != 0:
        fail(f"bench new-site failed (exit {rc}): {err[:300]}")
        # Double-check — sometimes bench exits non-zero but site dir is there
        if frappe_site_exists(container, site):
            warn("Exit code was non-zero but site directory exists — treating as success")
            return True
        return False

    # Verify the site directory actually landed on disk
    if not frappe_site_exists(container, site):
        fail(f"bench new-site exited 0 but site directory '{site}' is missing — something went wrong")
        return False

    app_list = ", ".join(FRAPPE_APPS) if FRAPPE_APPS else "none"
    ok(f"Site '{site}' created and verified  (apps installed: frappe, {app_list})")
    return True


def setup_frappe_site(cfg: EnvConfig, state: dict):
    step_key = f"site_{cfg.stack_name}"
    if is_done(state, step_key):
        info(f"Site for '{cfg.stack_name}' already set up — skipping")
        return

    step(f"Setting up Frappe site: {cfg.stack_name}  →  {cfg.site_name}")
    sn = cfg.stack_name

    # Wait up to 15 minutes for the backend service to have 1/1 replicas
    if not wait_for_service(sn, "backend", timeout=900):
        fail(f"Backend not ready for '{sn}' after 15 min — skipping site creation")
        state_error(state, step_key, "Backend 15-min timeout")
        return

    container = get_backend_container(sn)
    frappe_set_config(container)
    sleep(2)

    # site_name is the bench site folder name; must match HTTP Host header (= domain)
    site = cfg.site_name or cfg.domain

    if not frappe_create_site(container, site, cfg.db_root_password, cfg.site_admin_password):
        state_error(state, step_key, "Site creation failed or could not be verified")
        warn(f"Site '{site}' was NOT created successfully.")
        warn(f"Re-run the script to retry (this step is NOT marked done).")
        return

    # site creation already installed all apps via --install-app flags
    state_done(state, step_key)


# ─── Deployment summary ────────────────────────────────────────────────────────

def print_summary(traefik_cfg: TraefikConfig, portainer_cfg: PortainerConfig,
                  envs: List[EnvConfig]):
    print(f"\n{GREEN}{'═' * W}{RESET}")
    print(f"{BOLD}{GREEN}  🎉  DEPLOYMENT COMPLETE{RESET}")
    print(f"{GREEN}{'═' * W}{RESET}\n")

    print(f"  {BOLD}Access points{RESET}")
    print(f"    Traefik dashboard   →  https://{traefik_cfg.domain}")
    print(f"    {DIM}login: admin / <password you set during setup>{RESET}")
    if portainer_cfg.enabled:
        print(f"    Portainer           →  https://{portainer_cfg.domain}")
        print(f"    {DIM}login: admin / <Portainer password you set>{RESET}")
    for env in envs:
        sn = env.site_name or env.domain
        print(f"    {env.stack_name:14s}        →  https://{env.domain}  (site: {sn})")
        print(f"    {DIM}login: Administrator / <site admin password you set for '{env.stack_name}'>{RESET}")
        if env.has_mailpit:
            print(f"    {env.stack_name + ' mailpit':14s}  →  https://{env.mailpit_domain}")

    has_backup = any(e.has_backup for e in envs)
    print(f"\n  {BOLD}Shared services{RESET}")
    if has_backup:
        print(f"    Ofelia (cron scheduler)  →  running")
        for env in envs:
            if env.has_backup:
                print(f"      {env.stack_name}: daily 02:00 → {env.backup_dir}/{env.domain}")
        print(f"    Manual test:   docker service scale <stack>_backup=1")
        print(f"    Check logs:    docker service logs <stack>_backup -f")
    else:
        print(f"    Ofelia  →  not deployed (no environment uses backup)")

    print(f"\n  {BOLD}Migration service note{RESET}")
    print(f"    The 'migration' service in each app stack runs once on deploy then exits.")
    print(f"    This is expected — Docker will show it as 'complete' (0/1). That's correct.")
    print(f"    To re-run migrations:  docker service scale <stack>_migration=1")

    print(f"\n  {BOLD}Useful commands{RESET}")
    print(f"    docker stack ls                          # list all stacks")
    print(f"    docker service ls                        # all services & replica counts")
    print(f"    docker service logs <stack>_backend -f   # follow backend logs")
    print(f"    docker service logs <stack>_migration    # check migration output")
    print(f"    sudo python3 setup.py --status           # show deployment state")
    print(f"\n{GREEN}{'═' * W}{RESET}\n")


# ─── Status command ────────────────────────────────────────────────────────────

def print_status():
    BASE_DIR.mkdir(parents=True, exist_ok=True)
    state = state_load()
    header("Deployment Status")
    print(f"  Started:   {state.get('started_at', 'never')}")
    print(f"  Completed: {state.get('completed', [])}")
    if state.get("errors"):
        print(f"\n  {YELLOW}Errors:{RESET}")
        for e in state["errors"]:
            print(f"    [{e['step']}] {e['error'][:100]}")
    print(f"\n  {BOLD}Docker stacks:{RESET}")
    run_live("docker stack ls 2>/dev/null || echo '  (Docker not running)'")
    print(f"\n  {BOLD}Services:{RESET}")
    run_live("docker service ls 2>/dev/null || echo '  (Docker not running)'")


# ─── Main orchestrator ─────────────────────────────────────────────────────────

BANNER = f"""
{CYAN}╔{'═' * 62}╗
║{BOLD}   Frappe ERP — Complete Interactive VPS Setup              {RESET}{CYAN} ║
║   Packages → Docker → Swarm → Traefik → Stacks → Sites     ║
╚{'═' * 62}╝{RESET}
"""


def main():
    parser = argparse.ArgumentParser(description="Frappe ERP VPS setup")
    parser.add_argument("--reset",  action="store_true", help="Clear state and start over")
    parser.add_argument("--status", action="store_true", help="Show deployment status")
    args = parser.parse_args()

    if args.status:
        print_status()
        return

    check_root()
    print(BANNER)

    BASE_DIR.mkdir(parents=True, exist_ok=True)
    LOGS_DIR.mkdir(parents=True, exist_ok=True)

    if args.reset and STATE_FILE.exists():
        STATE_FILE.unlink()
        ok("State cleared — starting fresh")

    state = state_load()

    # ── Startup: detect existing stacks ─────────────────────────────────────
    check_and_cleanup_existing_stacks(state)

    # ── Phase 1: System setup ────────────────────────────────────────────────

    header("Phase 1 — System Setup")

    if not is_done(state, "versions"):
        resolve_versions()
        state_done(state, "versions")
    else:
        info(f"Versions already resolved — Traefik: {TRAEFIK_VERSION}, Portainer: {PORTAINER_VERSION}")

    if not is_done(state, "packages"):
        install_packages()
        state_done(state, "packages")
    else:
        info("Packages already installed")

    if not is_done(state, "docker"):
        install_docker()
        state_done(state, "docker")
    else:
        info("Docker already installed")

    if not is_done(state, "docker_group"):
        add_user_to_docker_group()
        state_done(state, "docker_group")
    else:
        info("Docker group membership already configured")

    if not is_done(state, "swarm"):
        init_swarm()
        state_done(state, "swarm")
    else:
        info("Swarm already initialised")

    if not is_done(state, "networks"):
        create_shared_networks()
        state_done(state, "networks")
    else:
        info("Shared networks already exist")

    # ── Phase 2: Gather configuration ────────────────────────────────────────

    header("Phase 2 — Configuration")

    if state.get("traefik") and is_done(state, "config"):
        print(f"  {DIM}Previously saved configuration found.{RESET}")
        if confirm("Use saved configuration?", default=True):
            t_cfg = TraefikConfig(**state["traefik"])
            # Re-build PortainerConfig — admin_password not stored (security)
            p_raw = dict(state["portainer"])
            p_raw.setdefault("admin_password", "")
            p_cfg = PortainerConfig(**p_raw)
            # Backwards-compat: older states may not have site_name / site_admin_password
            raw_envs = []
            for e in state["environments"]:
                e = dict(e)
                e.setdefault("site_name", e.get("domain", ""))
                e.setdefault("site_admin_password", "")
                raw_envs.append(e)
            envs  = [EnvConfig(**e) for e in raw_envs]
            github_user  = state.get("github_username", "")
            github_token = ask("GitHub PAT (to authenticate Docker pull)", secret=True)

            # Re-collect Portainer password if enabled and not set
            if p_cfg.enabled and not p_cfg.admin_password:
                if not is_done(state, "portainer_password"):
                    print(f"\n  {BOLD}Re-enter Portainer admin password (not stored in state){RESET}")
                    p_cfg.admin_password = ask("Portainer admin password", secret=True)

            # Re-collect site admin passwords for envs whose site step isn't done
            for cfg in envs:
                if not is_done(state, f"site_{cfg.stack_name}") and not cfg.site_admin_password:
                    print(f"\n  {BOLD}Re-enter site admin password for '{cfg.stack_name}' ({cfg.domain}){RESET}")
                    cfg.site_admin_password = ask("  Site admin password", secret=True)
        else:
            state["completed"] = [s for s in state["completed"]
                                   if s in ("packages", "docker", "docker_group", "swarm",
                                             "networks", "versions")]
            state_save(state)
            t_cfg, p_cfg, envs, github_user, github_token = _collect_all()
            _save_config(state, t_cfg, p_cfg, envs, github_user)
    else:
        t_cfg, p_cfg, envs, github_user, github_token = _collect_all()
        _save_config(state, t_cfg, p_cfg, envs, github_user)
        state_done(state, "config")

    # ── Phase 3: Validate uniqueness ─────────────────────────────────────────

    header("Phase 3 — Validation")
    step("Validating environment configuration")

    if not validate_env_uniqueness(envs):
        fail("Validation failed — please re-run and correct the configuration.")
        sys.exit(1)
    ok("All environment names and domains are unique")

    # ── Phase 4: Confirm and generate files ──────────────────────────────────

    header("Phase 4 — Review & Generate")
    _print_plan(t_cfg, p_cfg, envs)

    if not confirm("Proceed with deployment?", default=True):
        print("  Aborted. Re-run to resume from current state.")
        sys.exit(0)

    if not is_done(state, "files"):
        write_stacks(t_cfg, p_cfg, envs)
        state_done(state, "files")
    else:
        info("Stack files already generated")

    # ── Phase 5: Docker login ────────────────────────────────────────────────

    if not is_done(state, "docker_login"):
        docker_login(github_user, github_token)
        state_done(state, "docker_login")
    else:
        info("Docker login already done")

    # ── Phase 6: Traefik ─────────────────────────────────────────────────────

    header("Phase 6 — Traefik")

    if not is_done(state, "traefik"):
        step("Deploying Traefik")
        deploy_stack("traefik", STACKS_DIR / "traefik.yml", wait=12)
        info("Confirming Traefik service is running (1/1 replicas)…")
        if wait_for_service("traefik", "traefik", timeout=120):
            ok(f"Traefik dashboard live → https://{t_cfg.domain}  (login: admin / <your password>)")
        else:
            warn("Traefik replica count not 1/1 yet — check: docker service logs traefik_traefik")
        state_done(state, "traefik")
    else:
        info("Traefik already deployed")

    # ── Phase 7: Portainer ───────────────────────────────────────────────────

    header("Phase 7 — Portainer")

    if p_cfg.enabled:
        if not is_done(state, "portainer"):
            step("Deploying Portainer")
            deploy_stack("portainer", STACKS_DIR / "portainer.yml", wait=15)
            state_done(state, "portainer")
        else:
            info("Portainer already deployed")

        if not is_done(state, "portainer_password") and p_cfg.admin_password:
            set_portainer_admin_password(p_cfg.domain, p_cfg.admin_password)
            state_done(state, "portainer_password")
        elif is_done(state, "portainer_password"):
            info("Portainer admin password already configured")
    else:
        info("Portainer skipped")

    # ── Phase 8: MariaDB → App stacks (per environment) ──────────────────────
    #    Order: MariaDB first, then its associated app stack. Always.

    header("Phase 8 — Environment Stacks  (MariaDB → App)")

    for cfg in envs:
        sn      = cfg.stack_name
        db_key  = f"db_{sn}"
        app_key = f"app_{sn}"

        # 8a. MariaDB
        if not is_done(state, db_key):
            step(f"Deploying database stack: {cfg.db_stack_name}")
            deploy_stack(cfg.db_stack_name, STACKS_DIR / f"database-{sn}.yml", wait=5)
            info("Waiting 30s for MariaDB to initialise…")
            sleep(30)
            state_done(state, db_key)
        else:
            info(f"Database '{cfg.db_stack_name}' already deployed")

        # 8b. App stack
        if not is_done(state, app_key):
            step(f"Deploying app stack: {sn}")
            deploy_stack(sn, STACKS_DIR / f"{sn}.yml", wait=15)
            info("Note: 'migration' service will run once then show as 'complete' — that is expected.")
            state_done(state, app_key)
        else:
            info(f"App stack '{sn}' already deployed")

    # ── Phase 9: Ofelia (shared — only if at least one env uses backup) ──────

    if any(e.has_backup for e in envs):
        header("Phase 9 — Ofelia Shared Scheduler")
        if not is_done(state, "ofelia"):
            step("Deploying Ofelia cron scheduler")
            deploy_stack("ofelia", STACKS_DIR / "ofelia.yml", wait=10)
            sleep(15)
            _verify_ofelia(envs)
            state_done(state, "ofelia")
        else:
            info("Ofelia already deployed")
    else:
        info("Phase 9 — Ofelia: skipped (no environment has backup enabled)")

    # ── Phase 10: Frappe site creation ────────────────────────────────────────

    header("Phase 10 — Frappe Site Creation")

    for cfg in envs:
        try:
            setup_frappe_site(cfg, state)
        except Exception as e:
            fail(f"Site setup failed for '{cfg.stack_name}': {e}")
            state_error(state, f"site_{cfg.stack_name}", str(e))
            if not confirm("Continue with remaining environments?", default=True):
                sys.exit(1)

    # ── Done ─────────────────────────────────────────────────────────────────

    state_done(state, "complete")
    print_summary(t_cfg, p_cfg, envs)


# ─── Helpers used by main ──────────────────────────────────────────────────────

def _collect_all():
    t_cfg = collect_traefik()
    p_cfg = collect_portainer()
    envs, github_user, github_token = collect_environments()
    return t_cfg, p_cfg, envs, github_user, github_token


def _save_config(state: dict, t_cfg: TraefikConfig, p_cfg: PortainerConfig,
                 envs: List[EnvConfig], github_user: str):
    # Save portainer config but NOT the admin password (security)
    p_dict = asdict(p_cfg)
    p_dict["admin_password"] = ""    # never persist in plaintext

    state["traefik"]        = asdict(t_cfg)
    state["portainer"]      = p_dict
    state["environments"]   = [asdict(e) for e in envs]
    state["github_username"] = github_user
    state_save(state)


def _print_plan(t_cfg: TraefikConfig, p_cfg: PortainerConfig, envs: List[EnvConfig]):
    print(f"  {BOLD}What will be deployed:{RESET}\n")
    print(f"    Traefik  ({TRAEFIK_VERSION})    →  https://{t_cfg.domain}")
    if p_cfg.enabled:
        print(f"    Portainer ({PORTAINER_VERSION})  →  https://{p_cfg.domain}  [password: auto-set via API]")
    print()
    for e in envs:
        extras = []
        if e.has_mailpit: extras.append(f"mailpit @ {e.mailpit_domain}")
        if e.has_backup:  extras.append(f"backup → {e.backup_dir}")
        extra_str = f"  [{', '.join(extras)}]" if extras else ""
        sn_note   = f"  site={e.site_name}" if e.site_name and e.site_name != e.domain else ""
        apps_note = f"  apps: frappe, {', '.join(FRAPPE_APPS)}" if FRAPPE_APPS else "  apps: frappe"
        print(f"    {e.stack_name:12s}  DB: {e.db_stack_name:22s}  {e.domain}{sn_note}{extra_str}")
        print(f"    {' ' * 12}  {DIM}{apps_note}{RESET}")
    print()
    needs_ofelia = any(e.has_backup for e in envs)
    if needs_ofelia:
        backup_envs = [e.stack_name for e in envs if e.has_backup]
        print(f"  {BOLD}Shared services:{RESET}")
        print(f"    Ofelia (cron scheduler)  →  deployed  {DIM}[used by: {', '.join(backup_envs)}]{RESET}")
    else:
        print(f"  {BOLD}Shared services:{RESET}")
        print(f"    Ofelia (cron scheduler)  →  {DIM}NOT deployed (no environment uses backup){RESET}")
    print()
    print(f"  {DIM}Deployment order: Traefik → Portainer → [MariaDB → App] × {len(envs)}{RESET}")
    print(f"  {DIM}Site creation:    waits up to 15 min for backend to be healthy{RESET}")
    print()


def _verify_ofelia(envs: List[EnvConfig]):
    info("Verifying Ofelia registered backup jobs…")
    deadline = datetime.now().timestamp() + 30
    while datetime.now().timestamp() < deadline:
        rc, out, _ = run(
            "docker service logs ofelia_ofelia --tail 80 2>&1 | grep -i 'job'",
            check=False, silent=True,
        )
        if rc == 0 and out:
            ok("Ofelia jobs detected:")
            for line in out.splitlines()[:5]:
                print(f"    {DIM}{line}{RESET}")
            return
        sleep(5)
    warn("Could not verify Ofelia jobs. Check manually: docker service logs ofelia_ofelia")


# ─── Entry point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n\n  {YELLOW}Interrupted.{RESET} Re-run the script to resume from where you left off.")
        sys.exit(0)
    except Exception as exc:
        fail(f"Fatal: {exc}")
        import traceback; traceback.print_exc()
        sys.exit(1)