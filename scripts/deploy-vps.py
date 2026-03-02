#!/usr/bin/env python3
"""
Frappe ERP — Complete Interactive VPS Setup
Handles everything: packages → Docker → Swarm → Traefik → Portainer → Stacks → Sites

Usage:
  sudo ./deploy-vps.py                # fresh install or resume
  sudo ./deploy-vps.py --add-env     # add environments to existing deployment
  sudo ./deploy-vps.py --wipe-env    # remove one environment interactively
  sudo ./deploy-vps.py --status      # show deployment state and running services
  sudo ./deploy-vps.py --reset       # clear saved state and start from scratch

Architecture:
  - Stack YAML is loaded from templates/ directory (alongside this script)
  - Placeholders use __UPPER_SNAKE_CASE__ syntax — no conflict with Docker's $VAR
  - Backup scheduling: swarm-cronjob (shared-services stack) scales each
    env's backup-sites service (replicas:0) to 1 on cron schedule
  - Mailpit: single shared service joining every env's overlay network
"""

import os
import sys
import re
import json
import shutil
import subprocess
import getpass
import argparse
from pathlib import Path
from time import sleep
from datetime import datetime
from typing import List, Optional, Tuple
from dataclasses import dataclass, asdict


# ── Terminal output ────────────────────────────────────────────────────────────

BOLD   = "\033[1m"
GREEN  = "\033[92m"
CYAN   = "\033[96m"
YELLOW = "\033[93m"
RED    = "\033[91m"
DIM    = "\033[2m"
RESET  = "\033[0m"

_W = 64  # header line width


def header(title: str, subtitle: str = ""):
    print(f"\n{CYAN}{'═' * _W}{RESET}")
    print(f"{BOLD}{CYAN}  {title}{RESET}")
    if subtitle:
        print(f"{DIM}  {subtitle}{RESET}")
    print(f"{CYAN}{'─' * _W}{RESET}\n")


def ok(msg):   print(f"  {GREEN}✓{RESET}  {msg}")
def warn(msg): print(f"  {YELLOW}⚠{RESET}  {msg}")
def fail(msg): print(f"  {RED}✗{RESET}  {msg}")
def info(msg): print(f"  {DIM}·{RESET}  {msg}")
def step(msg): print(f"\n  {BOLD}▶{RESET}  {BOLD}{msg}{RESET}")


# ── Interactive prompts ────────────────────────────────────────────────────────

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


# ── Shell execution ────────────────────────────────────────────────────────────

_CMD_TIMEOUT = 900   # 15 minutes


def run(cmd: str, check: bool = True, silent: bool = False,
        timeout: int = _CMD_TIMEOUT) -> Tuple[int, str, str]:
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


def run_live(cmd: str, timeout: int = _CMD_TIMEOUT) -> int:
    print(f"  {DIM}$ {cmd}{RESET}")
    try:
        return subprocess.run(cmd, shell=True, executable="/bin/bash",
                              timeout=timeout).returncode
    except subprocess.TimeoutExpired:
        fail(f"Live command timed out after {timeout}s")
        return 1


# ── Version management ─────────────────────────────────────────────────────────

_TRAEFIK_MIN   = "v3.6.9"
_PORTAINER_MIN = "2.33.6"

TRAEFIK_VERSION   = _TRAEFIK_MIN
PORTAINER_VERSION = _PORTAINER_MIN


def _parse_semver(v: str) -> Tuple[int, int, int]:
    try:
        parts = v.lstrip("v").split(".")
        nums  = [int(x) for x in parts[:3]]
        return tuple(nums + [0] * (3 - len(nums)))
    except Exception:
        return (0, 0, 0)


def _fetch_github_latest_tag(repo: str) -> str:
    rc, out, _ = run(
        f"curl -sf --max-time 8 "
        f"'https://api.github.com/repos/{repo}/releases/latest' | "
        f"python3 -c \"import sys,json; print(json.load(sys.stdin).get('tag_name',''))\" 2>/dev/null",
        check=False, silent=True, timeout=20,
    )
    return out.strip() if (rc == 0 and out.strip()) else ""


def resolve_versions():
    global TRAEFIK_VERSION, PORTAINER_VERSION
    info("Checking for newer Traefik / Portainer releases (best-effort)…")

    latest_t = _fetch_github_latest_tag("traefik/traefik")
    if latest_t and _parse_semver(latest_t) > _parse_semver(_TRAEFIK_MIN):
        TRAEFIK_VERSION = latest_t if latest_t.startswith("v") else f"v{latest_t}"
        ok(f"Traefik:   {TRAEFIK_VERSION}  (upgraded from {_TRAEFIK_MIN})")
    else:
        TRAEFIK_VERSION = _TRAEFIK_MIN
        info(f"Traefik:   {TRAEFIK_VERSION}  (pinned)")

    latest_p = _fetch_github_latest_tag("portainer/portainer-ce")
    if latest_p and _parse_semver(latest_p) > _parse_semver(_PORTAINER_MIN):
        PORTAINER_VERSION = latest_p.lstrip("v")
        ok(f"Portainer: {PORTAINER_VERSION}  (upgraded from {_PORTAINER_MIN})")
    else:
        PORTAINER_VERSION = _PORTAINER_MIN
        info(f"Portainer: {PORTAINER_VERSION}  (pinned)")


# ── Data models ────────────────────────────────────────────────────────────────

@dataclass
class TraefikConfig:
    domain: str
    email: str
    hashed_password: str   # $$ escaped for YAML interpolation


@dataclass
class PortainerConfig:
    enabled: bool
    domain: str = ""
    admin_password: str = ""


@dataclass
class SharedServicesConfig:
    """Configuration for the single shared-services stack."""
    mailpit_enabled: bool = False
    mailpit_domain:  str  = ""


@dataclass
class EnvConfig:
    stack_name:          str
    domain:              str
    image:               str
    tag:                 str
    db_root_password:    str
    site_name:           str  = ""
    site_admin_password: str  = ""
    has_backup:          bool = False
    backup_dir:          str  = "/backups"
    backup_schedule:     str  = "0 2 * * *"
    backup_keep:         int  = 7

    @property
    def db_stack_name(self) -> str: return f"{self.stack_name}-mariadb"
    @property
    def db_network(self) -> str:    return f"{self.stack_name}-mariadb"
    @property
    def app_network(self) -> str:   return f"{self.stack_name}-network"
    @property
    def full_image(self) -> str:    return f"{self.image}:{self.tag}"


# ── State persistence ──────────────────────────────────────────────────────────

BASE_DIR   = Path("/opt/frappe-deploy")
STATE_FILE = BASE_DIR / ".setup_state.json"
STACKS_DIR = BASE_DIR / "stacks"
LOGS_DIR   = BASE_DIR / "logs"

_EMPTY_STATE: dict = {
    "started_at":    None,
    "completed":     [],
    "errors":        [],
    "traefik":       {},
    "portainer":     {},
    "shared_services": {},
    "environments":  [],
    "github_username": "",
}


def state_load() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except json.JSONDecodeError:
            warn("State file corrupted — starting fresh.")
    s = dict(_EMPTY_STATE)
    s["started_at"] = datetime.now().isoformat()
    return s


def state_save(s: dict):
    STATE_FILE.write_text(json.dumps(s, indent=2))


def state_mark_done(s: dict, key: str):
    if key not in s["completed"]:
        s["completed"].append(key)
    state_save(s)
    ok(f"Step '{key}' complete")


def state_mark_error(s: dict, key: str, msg: str):
    s["errors"].append({"step": key, "error": msg, "time": datetime.now().isoformat()})
    state_save(s)


def is_done(s: dict, key: str) -> bool:
    return key in s["completed"]


def _load_envs_from_state(state: dict) -> List[EnvConfig]:
    """Deserialise environment list from state dict, filling in defaults for older state files."""
    result = []
    for raw in state.get("environments", []):
        e = dict(raw)
        e.setdefault("site_name",           e.get("domain", ""))
        e.setdefault("site_admin_password", "")
        e.setdefault("backup_schedule",     "0 2 * * *")
        e.setdefault("backup_keep",         7)
        result.append(EnvConfig(**e))
    return result


# ── Template engine ────────────────────────────────────────────────────────────

TEMPLATES_DIR = Path(__file__).parent / "templates"


def render_template(template_name: str, variables: dict) -> str:
    """
    Load a template file and substitute __PLACEHOLDER__ markers.

    Markers use __UPPER_SNAKE_CASE__ format which never conflicts with:
      - Docker Compose variable interpolation ($VAR, ${VAR})
      - YAML syntax
      - Bash commands in block scalars

    Raises FileNotFoundError if the template does not exist.
    Raises ValueError if any marker remains unsubstituted after rendering.
    """
    template_path = TEMPLATES_DIR / template_name
    if not template_path.exists():
        raise FileNotFoundError(
            f"Template '{template_name}' not found in {TEMPLATES_DIR}\n"
            f"Ensure templates/ directory is alongside deploy-vps.py."
        )
    text = template_path.read_text()
    for key, value in variables.items():
        text = text.replace(f"__{key}__", str(value))

    remaining = re.findall(r'__[A-Z][A-Z0-9_]+__', text)
    if remaining:
        raise ValueError(
            f"Unsubstituted placeholders in '{template_name}': {sorted(set(remaining))}"
        )
    return text


def _write_stack_file(file_name: str, content: str) -> Path:
    """Write rendered content to STACKS_DIR and log it."""
    STACKS_DIR.mkdir(parents=True, exist_ok=True)
    path = STACKS_DIR / file_name
    path.write_text(content)
    ok(f"Generated stacks/{file_name}")
    return path


# ── Stack file renderers ───────────────────────────────────────────────────────

def _render_traefik_stack(cfg: TraefikConfig) -> str:
    return render_template("traefik.yml", {
        "TRAEFIK_VERSION":   TRAEFIK_VERSION,
        "TRAEFIK_DOMAIN":    cfg.domain,
        "TRAEFIK_EMAIL":     cfg.email,
        "TRAEFIK_HASHED_PW": cfg.hashed_password,
    })


def _render_portainer_stack(cfg: PortainerConfig) -> str:
    return render_template("portainer.yml", {
        "PORTAINER_VERSION": PORTAINER_VERSION,
        "PORTAINER_DOMAIN":  cfg.domain,
    })


def _render_database_stack(cfg: EnvConfig) -> str:
    is_prod = cfg.stack_name in ("prod", "main", "production", "live")
    return render_template("database.yml", {
        "STACK_NAME":       cfg.stack_name,
        "DB_NETWORK":       cfg.db_network,
        "DB_ROOT_PASSWORD": cfg.db_root_password,
        "MEM_LIMIT":        "2G"   if is_prod else "1G",
        "MEM_RESERVE":      "1G"   if is_prod else "256M",
        "BUFFER_POOL":      "1G"   if is_prod else "256M",
        "LOG_SIZE":         "512M" if is_prod else "128M",
    })


def _render_backup_service(cfg: EnvConfig) -> str:
    """
    Render the backup-sites service fragment (2-space indent, no leading newline).
    This is injected into the app-stack template at __BACKUP_SERVICE__.
    """
    return render_template("backup-service.yml", {
        "IMAGE":            cfg.full_image,
        "BACKUP_SCHEDULE":  cfg.backup_schedule,
        "SITE":             cfg.domain,
        "KEEP_PLUS_ONE":    str(cfg.backup_keep + 1),
        "KEEP":             str(cfg.backup_keep),
        "APP_NETWORK":      cfg.app_network,
        "DB_NETWORK":       cfg.db_network,
    })


def _render_app_stack(cfg: EnvConfig) -> str:
    """
    Render the full application stack YAML.
    Injects the backup service fragment and backup volume when cfg.has_backup is True.
    """
    if cfg.has_backup:
        backup_service = _render_backup_service(cfg)
        backup_volume  = (
            "\n"
            "  backups:\n"
            "    driver: local\n"
            "    driver_opts:\n"
            "      type: none\n"
            "      o: bind\n"
            f"      device: {cfg.backup_dir}\n"
            f"    name: {cfg.stack_name}-backups\n"
        )
        backup_header = (
            f"swarm-cronjob  schedule={cfg.backup_schedule}"
            f"  keep={cfg.backup_keep}  dir={cfg.backup_dir}"
        )
    else:
        backup_service = ""
        backup_volume  = ""
        backup_header  = "disabled"

    return render_template("app-stack.yml", {
        "STACK_NAME":      cfg.stack_name,
        "DOMAIN":          cfg.domain,
        "IMAGE":           cfg.full_image,
        "APP_NETWORK":     cfg.app_network,
        "DB_NETWORK":      cfg.db_network,
        "BACKUP_SERVICE":  backup_service,
        "BACKUP_VOLUME":   backup_volume,
        "BACKUP_HEADER":   backup_header,
    })


def _render_shared_services_stack(all_envs: List[EnvConfig],
                                  ss_cfg: SharedServicesConfig) -> str:
    """
    Render the shared-services stack YAML.

    Services included:
      - mailpit:       if ss_cfg.mailpit_enabled — single shared SMTP tester
      - swarm-cronjob: if any env has_backup — Swarm-native cron scheduler

    Returns empty string when neither service is needed (caller skips file creation).

    swarm-cronjob uses the Docker SERVICE API (not container API), so it works
    correctly with replicas:0 backup-sites services across all stacks.
    """
    backup_envs  = [e for e in all_envs if e.has_backup]
    has_mailpit  = ss_cfg.mailpit_enabled
    has_cronjob  = bool(backup_envs)

    if not has_mailpit and not has_cronjob:
        return ""

    services_block = ""
    extra_nets:dict = {}   # app_network → app_network, for networks section

    if has_mailpit:
        # Build per-env network aliases block for mailpit
        net_lines = ""
        for e in all_envs:
            extra_nets[e.app_network] = e.app_network
            net_lines += f"      {e.app_network}:\n"
            net_lines += f"        aliases:\n"
            net_lines += f"          - mailpit\n"
        net_lines += "      traefik-public: {}\n"

        md = ss_cfg.mailpit_domain
        services_block += (
            "  # ── Mailpit — shared SMTP tester, all envs reach as mailpit:1025 ──\n"
            "  mailpit:\n"
            "    image: axllent/mailpit:latest\n"
            "    deploy:\n"
            "      restart_policy:\n"
            "        condition: on-failure\n"
            "      labels:\n"
            '        - "traefik.enable=true"\n'
            '        - "traefik.swarm.network=traefik-public"\n'
            '        - "traefik.constraint-label=traefik-public"\n'
            f'        - "traefik.http.routers.mailpit-http.rule=Host(`{md}`)"\n'
            '        - "traefik.http.routers.mailpit-http.entrypoints=http"\n'
            '        - "traefik.http.routers.mailpit-http.middlewares=https-redirect"\n'
            f'        - "traefik.http.routers.mailpit-https.rule=Host(`{md}`)"\n'
            '        - "traefik.http.routers.mailpit-https.entrypoints=https"\n'
            '        - "traefik.http.routers.mailpit-https.tls=true"\n'
            '        - "traefik.http.routers.mailpit-https.tls.certresolver=le"\n'
            '        - "traefik.http.services.mailpit.loadbalancer.server.port=8025"\n'
            "    environment:\n"
            '      MP_SMTP_AUTH_ALLOW_INSECURE: "true"\n'
            '      MP_SMTP_AUTH_ACCEPT_ANY: "true"\n'
            "    networks:\n"
            + net_lines
        )

    if has_cronjob:
        services_block += (
            "\n"
            "  # ── swarm-cronjob — scales backup-sites services on schedule ────────\n"
            "  # Uses Docker SERVICE API (not container API), so replicas:0 is valid.\n"
            "  swarm-cronjob:\n"
            "    image: crazymax/swarm-cronjob:latest\n"
            "    deploy:\n"
            "      placement:\n"
            "        constraints:\n"
            "          - node.role == manager\n"
            "      restart_policy:\n"
            "        condition: on-failure\n"
            "    volumes:\n"
            "      - /var/run/docker.sock:/var/run/docker.sock:ro\n"
            "    environment:\n"
            "      TZ: Asia/Kolkata\n"
            "      LOG_LEVEL: info\n"
            '      LOG_JSON: "false"\n'
        )

    # Build networks block
    networks_block  = "  traefik-public:\n    external: true\n    name: traefik-public\n"
    for net in extra_nets:
        networks_block += f"  {net}:\n    external: true\n    name: {net}\n"

    mailpit_note  = ss_cfg.mailpit_domain if has_mailpit else "disabled"
    cronjob_stacks = ", ".join(e.stack_name for e in backup_envs) if has_cronjob else "none"

    return render_template("shared-services.yml", {
        "MAILPIT_NOTE":    mailpit_note,
        "CRONJOB_NOTE":    cronjob_stacks,
        "SERVICES_BLOCK":  services_block,
        "NETWORKS_BLOCK":  networks_block,
    })


# ── System setup ───────────────────────────────────────────────────────────────

def _check_root():
    if os.geteuid() != 0:
        fail("This script must be run as root.  Try:  sudo ./deploy-vps.py")
        sys.exit(1)


def _ensure_packages(state: dict):
    if is_done(state, "packages"):
        info("Packages already installed")
        return
    step("Installing system packages")
    packages = "curl openssl ca-certificates gnupg lsb-release apt-transport-https"
    run_live(f"apt-get update -qq && apt-get install -y {packages}")
    ok("System packages installed")
    state_mark_done(state, "packages")


def _ensure_docker(state: dict):
    if is_done(state, "docker"):
        info("Docker already installed")
        return
    step("Installing Docker CE")
    rc, out, _ = run("docker --version", check=False, silent=True)
    if rc == 0:
        ok(f"Docker already installed: {out}")
        state_mark_done(state, "docker")
        return
    info("Adding Docker GPG key and repository…")
    run("install -m 0755 -d /etc/apt/keyrings")
    run("curl -fsSL https://download.docker.com/linux/ubuntu/gpg | "
        "gpg --dearmor -o /etc/apt/keyrings/docker.gpg && chmod a+r /etc/apt/keyrings/docker.gpg")
    run('echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] '
        'https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" | '
        'tee /etc/apt/sources.list.d/docker.list > /dev/null')
    run_live("apt-get update -qq && apt-get install -y "
             "docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin")
    run("systemctl enable docker && systemctl start docker")
    ok("Docker CE installed and started")
    state_mark_done(state, "docker")


def _configure_docker_group(state: dict):
    if is_done(state, "docker_group"):
        info("Docker group already configured")
        return
    step("Adding user to docker group")
    sudo_user = os.environ.get("SUDO_USER", "").strip()
    if not sudo_user:
        warn("SUDO_USER not set — skipping.")
        state_mark_done(state, "docker_group")
        return
    rc, _, err = run(f"usermod -aG docker {sudo_user}", check=False)
    if rc == 0:
        ok(f"User '{sudo_user}' added to 'docker' group (re-login to activate)")
    else:
        warn(f"Could not add '{sudo_user}' to docker group: {err[:120]}")
    state_mark_done(state, "docker_group")


def _ensure_swarm(state: dict):
    if is_done(state, "swarm"):
        info("Docker Swarm already initialised")
        return
    step("Initialising Docker Swarm")
    _, info_out, _ = run("docker info 2>/dev/null", silent=True, check=False)
    if "Swarm: active" in info_out:
        ok("Docker Swarm already active")
    else:
        run("docker swarm init")
        ok("Docker Swarm initialised")
    state_mark_done(state, "swarm")


def _ensure_shared_networks(state: dict):
    if is_done(state, "networks"):
        info("Shared networks already exist")
        return
    step("Creating shared overlay networks")
    for net in ("traefik-public",):
        rc, _, _ = run(f"docker network inspect {net}", check=False, silent=True)
        if rc == 0:
            ok(f"Network '{net}' already exists")
        else:
            run(f"docker network create --driver overlay --attachable {net}")
            ok(f"Network '{net}' created")
    state_mark_done(state, "networks")


def phase_system_setup(state: dict):
    header("Phase 1 — System Setup")

    if not is_done(state, "versions"):
        resolve_versions()
        state_mark_done(state, "versions")
    else:
        info(f"Versions resolved — Traefik: {TRAEFIK_VERSION}, Portainer: {PORTAINER_VERSION}")

    _ensure_packages(state)
    _ensure_docker(state)
    _configure_docker_group(state)
    _ensure_swarm(state)
    _ensure_shared_networks(state)


# ── Startup: detect and offer to wipe existing stacks ─────────────────────────

def _get_live_stacks() -> List[str]:
    rc, out, _ = run("docker stack ls --format '{{.Name}}' 2>/dev/null",
                     check=False, silent=True)
    return [s.strip() for s in out.splitlines() if s.strip()] if rc == 0 else []


def _cleanup_existing_stacks(state: dict):
    """
    If Docker stacks already exist, offer a typed-confirmation wipe before proceeding.
    Safe to skip — the rest of the script handles re-deploys cleanly.
    """
    existing = _get_live_stacks()
    if not existing:
        return

    print(f"\n  {YELLOW}{'─' * 60}{RESET}")
    warn("Existing Docker stacks detected:")
    for s in existing:
        print(f"      {DIM}•{RESET}  {s}")
    print(f"  {YELLOW}{'─' * 60}{RESET}\n")

    if not confirm("Wipe ALL existing stacks and start completely fresh?", default=False):
        info("Keeping existing stacks — use --add-env to add environments.")
        return

    confirm_phrase = "yes delete everything"
    print(f"\n  {RED}{BOLD}⚠  DANGER ZONE  ⚠{RESET}")
    print(f"  {RED}This permanently destroys all stacks, containers and data.{RESET}")
    print(f"  Type exactly (case-sensitive):  {BOLD}{confirm_phrase}{RESET}\n")
    typed = input("  Your confirmation: ").strip()

    if typed != confirm_phrase:
        warn("Phrase did not match — cleanup cancelled.")
        return

    step("Removing all existing stacks…")
    for s in existing:
        run(f"docker stack rm {s}", check=False)
        ok(f"Removed stack: {s}")

    info("Waiting 25s for containers to fully shut down…")
    sleep(25)

    if confirm("Also prune unused Docker volumes?", default=False):
        run("docker volume prune -f", check=False)
        ok("Unused volumes pruned")

    if STATE_FILE.exists():
        STATE_FILE.unlink()
    state.clear()
    state.update(dict(_EMPTY_STATE))
    state["started_at"] = datetime.now().isoformat()
    state_save(state)
    ok("State reset — starting fresh")


# ── Configuration collectors ───────────────────────────────────────────────────

_DEFAULT_IMAGE = "ghcr.io/frappe/frappe-docker"


def _collect_traefik() -> TraefikConfig:
    header("Traefik Setup", "Reverse proxy and automatic SSL certificates")
    domain = ask("Dashboard domain", "traefik.example.com")
    email  = ask("Let's Encrypt email", "admin@example.com")

    print(f"\n  {BOLD}Dashboard password{RESET}  (protects the Traefik UI)")
    while True:
        pw  = ask("Password", secret=True)
        pw2 = ask("Confirm",  secret=True)
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
    return TraefikConfig(domain=domain, email=email, hashed_password=hashed)


def _collect_portainer() -> PortainerConfig:
    header("Portainer Setup", "Optional web UI for managing Docker Swarm stacks")
    if not confirm("Install Portainer?", default=True):
        info("Skipping Portainer.")
        return PortainerConfig(enabled=False)
    domain = ask("Portainer domain", "portainer.example.com")
    print(f"\n  {BOLD}Admin password{RESET}  (set after deploy via helper image)")
    while True:
        pw  = ask("Admin password",  secret=True)
        pw2 = ask("Confirm password", secret=True)
        if pw == pw2:
            break
        print(f"  {RED}Passwords do not match — try again.{RESET}")
    ok(f"Domain: {domain}")
    return PortainerConfig(enabled=True, domain=domain, admin_password=pw)


def _collect_single_env(index: int, total: int,
                        used_names: set, used_domains: set,
                        image: str, tag: str, db_pass: str) -> EnvConfig:
    """Collect and validate configuration for one environment."""
    print(f"\n  {CYAN}{'─' * 50}{RESET}")
    print(f"  {BOLD}Environment {index} of {total}{RESET}\n")

    while True:
        name = ask("  Stack name (e.g. prod, staging, dev)").lower().replace(" ", "-")
        if name in used_names:
            print(f"  {RED}Stack name '{name}' already used.{RESET}")
        else:
            used_names.add(name)
            break

    while True:
        domain = ask("  Domain / site name  (e.g. erp.mycompany.com)",
                     f"erp-{name}.example.com")
        if domain in used_domains:
            print(f"  {RED}Domain '{domain}' already assigned.{RESET}")
        else:
            used_domains.add(domain)
            break

    print(f"\n  {BOLD}Frappe site admin password{RESET}  (login at https://{domain})")
    while True:
        sp  = ask("  Site admin password", secret=True)
        sp2 = ask("  Confirm password",    secret=True)
        if sp == sp2:
            break
        print(f"  {RED}Passwords do not match.{RESET}")

    print(f"\n  {BOLD}Optional services for '{name}':{RESET}")
    print(f"  {DIM}  Backup: swarm-cronjob triggers backup-sites in this stack on schedule.{RESET}")
    has_backup      = confirm("  Add automated backup?",
                              default=(name in ("prod", "main", "production")))
    backup_dir      = "/backups"
    backup_schedule = "0 2 * * *"
    backup_keep     = 7
    if has_backup:
        backup_dir      = ask("    Backup directory on host", "/backups")
        backup_schedule = ask("    Backup cron schedule", "0 2 * * *")
        try:
            backup_keep = int(ask("    Number of backup sets to keep", "7"))
        except ValueError:
            backup_keep = 7
            warn("Invalid number — defaulting to 7")

    env = EnvConfig(
        stack_name=name, domain=domain, site_name=domain,
        site_admin_password=sp, image=image, tag=tag,
        db_root_password=db_pass,
        has_backup=has_backup, backup_dir=backup_dir,
        backup_schedule=backup_schedule, backup_keep=backup_keep,
    )
    ok(f"'{name}' → {domain}"
       + (f"  + backup [{backup_schedule}, keep={backup_keep}]" if has_backup else ""))
    return env


def _collect_environments(existing_envs: List[EnvConfig] = None
                          ) -> Tuple[List[EnvConfig], str, str]:
    """
    Collect image, registry credentials, DB password, and N environment configs.
    Returns (envs, github_username, github_token).
    existing_envs pre-seeds uniqueness sets so new envs cannot clash.
    """
    existing_envs = existing_envs or []
    header("Docker Image & Registry", "Used for all Frappe app containers")

    image        = ask("Frappe image  (registry/org/repo, no tag)", _DEFAULT_IMAGE)
    tag          = ask("Image tag", "main")

    print(f"\n  {BOLD}GitHub Container Registry credentials{RESET}")
    github_user  = ask("GitHub username")
    github_token = ask("GitHub PAT (read:packages)", secret=True)

    print(f"\n  {BOLD}Database{RESET}")
    while True:
        db_pass  = ask("MariaDB root password", secret=True)
        db_pass2 = ask("Confirm password",      secret=True)
        if db_pass == db_pass2:
            break
        print(f"  {RED}Passwords do not match.{RESET}")

    header("Environments", "Configure each deployment environment")
    while True:
        try:
            n = int(ask("Number of environments to deploy (1–4)", "1"))
            if 1 <= n <= 4:
                break
            print(f"  {RED}Enter a number between 1 and 4.{RESET}")
        except ValueError:
            print(f"  {RED}Please enter a valid number.{RESET}")

    used_names   = {e.stack_name for e in existing_envs}
    used_domains = {e.domain     for e in existing_envs}

    envs: List[EnvConfig] = []
    for i in range(n):
        env = _collect_single_env(i + 1, n, used_names, used_domains, image, tag, db_pass)
        envs.append(env)

    return envs, github_user, github_token


def _collect_shared_services(all_envs: List[EnvConfig],
                              existing: SharedServicesConfig = None) -> SharedServicesConfig:
    """Collect configuration for the single shared-services stack."""
    header("Shared Services", "One shared Mailpit SMTP tester for all environments")

    if existing and existing.mailpit_enabled:
        info(f"Existing shared mailpit at: {existing.mailpit_domain}")
        if confirm("Keep existing shared mailpit config?", default=True):
            return existing

    if not confirm("Enable shared Mailpit?", default=True):
        info("Shared mailpit disabled.")
        return SharedServicesConfig(mailpit_enabled=False)

    used_domains = {e.domain for e in all_envs}
    while True:
        md = ask("Mailpit domain", "mail.example.com")
        if md in used_domains:
            print(f"  {RED}Domain '{md}' is already used by an env site.{RESET}")
        else:
            break

    ok(f"Shared mailpit  →  https://{md}")
    info("All containers reach SMTP as  mailpit:1025  (overlay alias on each app network)")
    return SharedServicesConfig(mailpit_enabled=True, mailpit_domain=md)


def _collect_all_configuration() -> Tuple[TraefikConfig, PortainerConfig,
                                           SharedServicesConfig, List[EnvConfig], str, str]:
    t_cfg  = _collect_traefik()
    p_cfg  = _collect_portainer()
    envs, github_user, github_token = _collect_environments()
    ss_cfg = _collect_shared_services(envs)
    return t_cfg, p_cfg, ss_cfg, envs, github_user, github_token


def _persist_configuration(state: dict, t_cfg: TraefikConfig, p_cfg: PortainerConfig,
                            ss_cfg: SharedServicesConfig, envs: List[EnvConfig],
                            github_user: str):
    p_dict = asdict(p_cfg)
    p_dict["admin_password"] = ""    # never persist plaintext credentials
    state["traefik"]          = asdict(t_cfg)
    state["portainer"]        = p_dict
    state["shared_services"]  = asdict(ss_cfg)
    state["environments"]     = [asdict(e) for e in envs]
    state["github_username"]  = github_user
    state_save(state)


def _load_saved_configuration(state: dict
                               ) -> Optional[Tuple[TraefikConfig, PortainerConfig,
                                                   SharedServicesConfig, List[EnvConfig], str]]:
    """
    Attempt to reload previously saved configuration.
    Returns (t_cfg, p_cfg, ss_cfg, envs, github_user) or None if not available.
    """
    if not state.get("traefik") or not is_done(state, "config"):
        return None

    t_cfg = TraefikConfig(**state["traefik"])

    p_raw = dict(state["portainer"])
    p_raw.setdefault("admin_password", "")
    p_cfg = PortainerConfig(**p_raw)

    ss_raw = dict(state.get("shared_services", {}))
    ss_raw.setdefault("mailpit_enabled", False)
    ss_raw.setdefault("mailpit_domain",  "")
    ss_cfg = SharedServicesConfig(**ss_raw)

    envs        = _load_envs_from_state(state)
    github_user = state.get("github_username", "")
    return t_cfg, p_cfg, ss_cfg, envs, github_user


def phase_gather_configuration(state: dict
                                ) -> Tuple[TraefikConfig, PortainerConfig,
                                           SharedServicesConfig, List[EnvConfig], str, str]:
    header("Phase 2 — Configuration")

    saved = _load_saved_configuration(state)
    if saved:
        t_cfg, p_cfg, ss_cfg, envs, github_user = saved
        print(f"  {DIM}Previously saved configuration found.{RESET}")
        if confirm("Use saved configuration?", default=True):
            github_token = ask("GitHub PAT (to authenticate Docker pull)", secret=True)

            if p_cfg.enabled and not p_cfg.admin_password and not is_done(state, "portainer_password"):
                print(f"\n  {BOLD}Re-enter Portainer admin password (not stored in state){RESET}")
                p_cfg.admin_password = ask("Portainer admin password", secret=True)

            for cfg in envs:
                if not is_done(state, f"site_{cfg.stack_name}") and not cfg.site_admin_password:
                    print(f"\n  {BOLD}Re-enter site admin password for '{cfg.stack_name}'{RESET}")
                    cfg.site_admin_password = ask("  Site admin password", secret=True)

            return t_cfg, p_cfg, ss_cfg, envs, github_user, github_token
        else:
            # User chose to reconfigure — clear everything except system steps
            state["completed"] = [s for s in state["completed"]
                                  if s in ("packages", "docker", "docker_group",
                                            "swarm", "networks", "versions")]
            state_save(state)

    t_cfg, p_cfg, ss_cfg, envs, github_user, github_token = _collect_all_configuration()
    _persist_configuration(state, t_cfg, p_cfg, ss_cfg, envs, github_user)
    state_mark_done(state, "config")
    return t_cfg, p_cfg, ss_cfg, envs, github_user, github_token


# ── Validation ─────────────────────────────────────────────────────────────────

def _validate_env_uniqueness(envs: List[EnvConfig],
                             existing_envs: List[EnvConfig] = None) -> bool:
    all_ok        = True
    existing_envs = existing_envs or []
    existing_stacks  = {e.stack_name for e in existing_envs}
    existing_domains = {e.domain     for e in existing_envs}

    seen_stacks:  dict = {}
    seen_domains: dict = {}

    for e in envs:
        if e.stack_name in seen_stacks:
            fail(f"Duplicate stack name '{e.stack_name}' in new environments.")
            all_ok = False
        else:
            seen_stacks[e.stack_name] = True

        if e.stack_name in existing_stacks:
            warn(f"Stack '{e.stack_name}' already exists — will be re-deployed (updated).")

        if e.domain in seen_domains:
            fail(f"Duplicate domain '{e.domain}' in new environments.")
            all_ok = False
        else:
            seen_domains[e.domain] = e.stack_name

        if e.domain in existing_domains:
            fail(f"Domain '{e.domain}' is already used by an existing environment.")
            all_ok = False

    live_stacks = set(_get_live_stacks())
    for e in envs:
        if e.stack_name    in live_stacks: warn(f"App stack '{e.stack_name}' exists — will be updated.")
        if e.db_stack_name in live_stacks: warn(f"DB stack  '{e.db_stack_name}' exists — will be updated.")

    return all_ok


def phase_validate_configuration(envs: List[EnvConfig],
                                  existing_envs: List[EnvConfig] = None):
    header("Phase 3 — Validation")
    step("Validating environment configuration")
    if not _validate_env_uniqueness(envs, existing_envs):
        fail("Validation failed — please re-run and correct the configuration.")
        sys.exit(1)
    ok("All environment names and domains are unique")


# ── Review and confirm ─────────────────────────────────────────────────────────

def _print_deployment_plan(t_cfg: TraefikConfig, p_cfg: PortainerConfig,
                            ss_cfg: SharedServicesConfig, envs: List[EnvConfig]):
    print(f"  {BOLD}What will be deployed:{RESET}\n")
    print(f"    Traefik  ({TRAEFIK_VERSION})    →  https://{t_cfg.domain}")
    if p_cfg.enabled:
        print(f"    Portainer ({PORTAINER_VERSION})  →  https://{p_cfg.domain}")
    print()
    for e in envs:
        extras    = [f"backup → {e.backup_dir}"] if e.has_backup else []
        extra_str = f"  [{', '.join(extras)}]" if extras else ""
        print(f"    {e.stack_name:12s}  DB: {e.db_stack_name:22s}  {e.domain}{extra_str}")
        print(f"    {' ' * 12}  {DIM}apps: auto-detected from bench image{RESET}")
    print()
    print(f"  {BOLD}Shared services stack:{RESET}")
    if ss_cfg.mailpit_enabled:
        print(f"    Mailpit (shared): https://{ss_cfg.mailpit_domain}")
        print(f"    {DIM}Joins all {len(envs)} env network(s) with alias 'mailpit:1025'{RESET}")
    else:
        print(f"    Mailpit:  disabled")

    backup_stacks = [e.stack_name for e in envs if e.has_backup]
    if backup_stacks:
        print(f"    swarm-cronjob: backup-sites for {', '.join(backup_stacks)}")
    if not ss_cfg.mailpit_enabled and not backup_stacks:
        print(f"    {DIM}None — mailpit disabled and no backup configured{RESET}")
    else:
        print(f"    {DIM}Deployed AFTER app stacks (joins their overlay networks){RESET}")
    print()
    print(f"  {DIM}Deploy order: Traefik → Portainer → [MariaDB → App] × {len(envs)} → shared-services{RESET}")
    print()


def phase_review_and_confirm(t_cfg: TraefikConfig, p_cfg: PortainerConfig,
                              ss_cfg: SharedServicesConfig, envs: List[EnvConfig]):
    header("Phase 4 — Review & Generate")
    _print_deployment_plan(t_cfg, p_cfg, ss_cfg, envs)
    if not confirm("Proceed with deployment?", default=True):
        print("  Aborted. Re-run to resume from current state.")
        sys.exit(0)


# ── Stack file generation ──────────────────────────────────────────────────────

def _write_infrastructure_stacks(t_cfg: TraefikConfig, p_cfg: PortainerConfig):
    _write_stack_file("traefik.yml",   _render_traefik_stack(t_cfg))
    if p_cfg.enabled:
        _write_stack_file("portainer.yml", _render_portainer_stack(p_cfg))


def _write_env_stacks(envs: List[EnvConfig]):
    for cfg in envs:
        _write_stack_file(f"database-{cfg.stack_name}.yml", _render_database_stack(cfg))
        _write_stack_file(f"{cfg.stack_name}.yml",          _render_app_stack(cfg))
        if cfg.has_backup:
            Path(cfg.backup_dir).mkdir(parents=True, exist_ok=True)
            ok(f"Backup dir ensured: {cfg.backup_dir}")


def _write_shared_services_stack(all_envs: List[EnvConfig],
                                  ss_cfg: SharedServicesConfig):
    shared_yml = _render_shared_services_stack(all_envs, ss_cfg)
    stale_path = STACKS_DIR / "shared-services.yml"

    if shared_yml:
        _write_stack_file("shared-services.yml", shared_yml)
        backup_envs = [e for e in all_envs if e.has_backup]
        parts = []
        if ss_cfg.mailpit_enabled: parts.append("mailpit")
        if backup_envs:            parts.append("swarm-cronjob")
        ok(f"shared-services.yml: {' + '.join(parts)}")
    else:
        info("shared-services.yml skipped — mailpit disabled and no backup configured")
        if stale_path.exists():
            stale_path.unlink()
            info("Removed stale shared-services.yml")


def _install_helper_scripts():
    """Copy backup.sh and restore.sh from scripts/ dir to /opt/frappe-deploy/."""
    scripts_src = Path(__file__).parent
    for script in ("backup.sh", "restore.sh"):
        src = scripts_src / script
        dst = BASE_DIR / script
        if src.exists():
            shutil.copy2(str(src), str(dst))
            dst.chmod(0o750)
            ok(f"Installed {script} → {dst}")
        else:
            warn(f"{script} not found alongside deploy-vps.py — skipping")


def phase_generate_stack_files(t_cfg: TraefikConfig, p_cfg: PortainerConfig,
                                ss_cfg: SharedServicesConfig,
                                all_envs: List[EnvConfig],
                                new_envs: List[EnvConfig] = None):
    """
    Write all stack YAML files to STACKS_DIR.

    all_envs:  complete env list — used for shared-services (which lists all networks)
    new_envs:  if provided, only these env stacks are (re)written (--add-env flow)
               if None, all envs are written along with infrastructure stacks
    """
    STACKS_DIR.mkdir(parents=True, exist_ok=True)
    step("Generating stack YAML files")

    write_all = new_envs is None
    target_envs = all_envs if write_all else new_envs

    if write_all:
        _write_infrastructure_stacks(t_cfg, p_cfg)

    _write_env_stacks(target_envs)
    _write_shared_services_stack(all_envs, ss_cfg)
    _install_helper_scripts()


# ── Docker operations ──────────────────────────────────────────────────────────

def _docker_login(username: str, token: str):
    step("Logging in to GitHub Container Registry")
    result = subprocess.run(
        ["docker", "login", "ghcr.io", "-u", username, "--password-stdin"],
        input=token, capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"docker login failed: {result.stderr.strip()}")
    ok(f"Logged in to ghcr.io as '{username}'")


def _deploy_stack(stack_name: str, yml_path: Path, wait: int = 8):
    if not yml_path.exists():
        raise FileNotFoundError(f"Stack file missing: {yml_path}")
    run(f"docker stack deploy --with-registry-auth -c {yml_path} {stack_name}")
    info(f"Waiting {wait}s for '{stack_name}' to stabilise…")
    sleep(wait)
    ok(f"Stack '{stack_name}' deployed")


def _wait_for_service(stack_name: str, service: str, timeout: int = 120) -> bool:
    info(f"Waiting for {stack_name}_{service} to be ready (max {timeout}s)…")
    deadline = datetime.now().timestamp() + timeout
    while datetime.now().timestamp() < deadline:
        _, out, _ = run(
            f"docker service ls --filter name={stack_name}_{service}"
            f" --format '{{{{.Replicas}}}}'",
            check=False, silent=True,
        )
        if out.startswith("1/1"):
            ok(f"{service} is ready")
            return True
        sleep(6)
    warn(f"{service} not ready after {timeout}s — check: docker service logs {stack_name}_{service}")
    return False


def _get_backend_container(stack_name: str) -> str:
    _, cid, _ = run(
        f"docker ps --filter 'label=com.docker.swarm.service.name={stack_name}_backend'"
        f" --format '{{{{.ID}}}}' | head -1",
        silent=True,
    )
    if not cid:
        raise RuntimeError(f"No running backend container for '{stack_name}'")
    return cid


def phase_registry_login(github_user: str, github_token: str, state: dict):
    if is_done(state, "docker_login"):
        info("Docker login already done")
        return
    _docker_login(github_user, github_token)
    state_mark_done(state, "docker_login")


# ── Traefik deployment ─────────────────────────────────────────────────────────

def phase_deploy_traefik(t_cfg: TraefikConfig, state: dict):
    header("Phase 6 — Traefik")
    if is_done(state, "traefik"):
        info("Traefik already deployed")
        return
    step("Deploying Traefik")
    _deploy_stack("traefik", STACKS_DIR / "traefik.yml", wait=12)
    if _wait_for_service("traefik", "traefik", timeout=120):
        ok(f"Traefik dashboard → https://{t_cfg.domain}")
    else:
        warn("Traefik not 1/1 yet — check: docker service logs traefik_traefik")
    state_mark_done(state, "traefik")


# ── Portainer deployment ───────────────────────────────────────────────────────

def _reset_portainer_admin_password(domain: str, password: str):
    step("Setting Portainer admin password via helper image")
    _, out, _ = run(
        "docker service ls --filter name=portainer_portainer --format '{{.Name}}'",
        check=False, silent=True,
    )
    if "portainer_portainer" not in out:
        warn("Portainer service not found — skipping password setup.")
        return

    info("Waiting for Portainer to reach 1/1 replicas (volume init)…")
    deadline = datetime.now().timestamp() + 600
    ready = False
    while datetime.now().timestamp() < deadline:
        _, replicas, _ = run(
            "docker service ls --filter name=portainer_portainer --format '{{.Replicas}}'",
            check=False, silent=True,
        )
        if replicas.strip().startswith("1/1"):
            ready = True
            ok("Portainer is running (1/1)")
            break
        sleep(10)

    if not ready:
        warn("Portainer did not reach 1/1 within 10 min — attempting reset anyway.")

    info("Scaling Portainer to 0 for exclusive volume access…")
    run("docker service scale portainer_portainer=0", check=False)
    sleep(8)

    info("Running portainer/helper-reset-password…")
    rc, out, err = run(
        f'docker run --rm -v portainer-data:/data portainer/helper-reset-password'
        f' --password "{password}"',
        check=False,
    )

    info("Scaling Portainer back to 1…")
    run("docker service scale portainer_portainer=1", check=False)

    if rc == 0:
        ok("Portainer admin password set successfully")
        ok(f"Login at https://{domain}  →  admin / <password you entered>")
    else:
        warn(f"Helper exited with code {rc}: {(err or out or 'no output')[:200]}")
        warn("Reset manually:  docker run --rm -v portainer-data:/data "
             "portainer/helper-reset-password --password 'yourpassword'")


def phase_deploy_portainer(p_cfg: PortainerConfig, state: dict):
    header("Phase 7 — Portainer")
    if not p_cfg.enabled:
        info("Portainer skipped")
        return

    if not is_done(state, "portainer"):
        step("Deploying Portainer")
        _deploy_stack("portainer", STACKS_DIR / "portainer.yml", wait=15)
        state_mark_done(state, "portainer")
    else:
        info("Portainer already deployed")

    if not is_done(state, "portainer_password") and p_cfg.admin_password:
        _reset_portainer_admin_password(p_cfg.domain, p_cfg.admin_password)
        state_mark_done(state, "portainer_password")
    elif is_done(state, "portainer_password"):
        info("Portainer password already configured")


# ── Environment deployment ─────────────────────────────────────────────────────

def _deploy_database_stack(cfg: EnvConfig, state: dict):
    key = f"db_{cfg.stack_name}"
    if is_done(state, key):
        info(f"Database '{cfg.db_stack_name}' already deployed")
        return
    step(f"Deploying database stack: {cfg.db_stack_name}")
    _deploy_stack(cfg.db_stack_name, STACKS_DIR / f"database-{cfg.stack_name}.yml", wait=5)
    info("Waiting 30s for MariaDB to initialise…")
    sleep(30)
    state_mark_done(state, key)


def _deploy_app_stack(cfg: EnvConfig, state: dict):
    key = f"app_{cfg.stack_name}"
    if is_done(state, key):
        info(f"App stack '{cfg.stack_name}' already deployed")
        return
    step(f"Deploying app stack: {cfg.stack_name}")
    _deploy_stack(cfg.stack_name, STACKS_DIR / f"{cfg.stack_name}.yml", wait=15)
    info("Note: 'migration' service runs once then shows 0/1 — that is correct.")
    state_mark_done(state, key)


def _deploy_single_environment(cfg: EnvConfig, state: dict):
    _deploy_database_stack(cfg, state)
    _deploy_app_stack(cfg, state)


def phase_deploy_environments(envs: List[EnvConfig], state: dict):
    header("Phase 8 — Environment Stacks  (MariaDB → App)")
    for cfg in envs:
        _deploy_single_environment(cfg, state)


# ── Shared services deployment ─────────────────────────────────────────────────

def _verify_backup_services(all_envs: List[EnvConfig]):
    """Confirm swarm-cronjob is running and backup-sites services are registered."""
    backup_envs = [e for e in all_envs if e.has_backup]
    if not backup_envs:
        return
    info("Verifying backup services…")
    _, out, _ = run(
        "docker service ls --filter name=shared-services_swarm-cronjob"
        " --format '{{.Replicas}}'",
        check=False, silent=True,
    )
    if out.startswith("1/1"):
        ok("swarm-cronjob is running (1/1)")
    else:
        warn("swarm-cronjob not yet 1/1 — check: docker service logs shared-services_swarm-cronjob")

    for e in backup_envs:
        _, svc, _ = run(
            f"docker service ls --filter name={e.stack_name}_backup-sites"
            f" --format '{{{{.Name}}}}'",
            check=False, silent=True,
        )
        if svc:
            ok(f"backup-sites/{e.stack_name}: registered  schedule={e.backup_schedule}")
        else:
            warn(f"backup-sites/{e.stack_name}: service not found in Swarm")


def phase_deploy_shared_services(ss_cfg: SharedServicesConfig,
                                  all_envs: List[EnvConfig], state: dict):
    shared_yml = STACKS_DIR / "shared-services.yml"
    if not shared_yml.exists():
        info("Phase 9 — Shared services: skipped (mailpit disabled, no backup configured)")
        return

    header("Phase 9 — Shared Services")
    if is_done(state, "shared_services"):
        info("shared-services already deployed")
        return

    step("Deploying shared-services stack")
    info("Waiting 10s for app overlay networks to be ready…")
    sleep(10)
    _deploy_stack("shared-services", shared_yml, wait=10)
    sleep(15)
    _verify_backup_services(all_envs)
    state_mark_done(state, "shared_services")


# ── Frappe site creation ───────────────────────────────────────────────────────

def _detect_available_apps(container: str) -> List[str]:
    """List all apps in the bench image except 'frappe' (installed automatically by new-site)."""
    rc, out, _ = run(
        f"docker exec {container} bash -c"
        f" 'ls /home/frappe/frappe-bench/apps/ 2>/dev/null'",
        check=False, silent=True,
    )
    if rc != 0 or not out.strip():
        warn("Could not list bench apps directory — no extra apps will be installed.")
        return []
    apps = [a.strip() for a in out.splitlines() if a.strip() and a.strip() != "frappe"]
    if apps:
        ok(f"Detected {len(apps)} extra app(s) to install: {', '.join(apps)}")
    else:
        info("No extra apps found in bench (only frappe will be installed).")
    return apps


def _configure_bench_globals(container: str):
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


def _site_exists(container: str, site: str) -> bool:
    rc, out, _ = run(
        f'docker exec {container} bash -c '
        f'"[ -d /home/frappe/frappe-bench/sites/{site} ] && echo SITE_EXISTS || echo SITE_MISSING"',
        check=False, silent=True,
    )
    return "SITE_EXISTS" in out


def _create_frappe_site(container: str, site: str,
                        db_root_password: str, site_admin_password: str) -> bool:
    info(f"Creating site: {site}")

    if _site_exists(container, site):
        ok(f"Site '{site}' already exists — skipping creation")
        return True

    apps = _detect_available_apps(container)
    install_flags = " ".join(f"--install-app {app}" for app in apps) if apps else ""

    # --mariadb-user-host-login-scope=% MUST come before the site name (positional)
    bench_cmd = (
        f"cd /home/frappe/frappe-bench && bench new-site "
        f"--mariadb-user-host-login-scope=% "
        f"{site} "
        f"--admin-password {site_admin_password} "
        f"--db-host mariadb "
        f"--db-port 3306 "
        f"--db-root-password {db_root_password} "
        f"{install_flags}"
    ).strip()

    rc, _, err = run(f'docker exec {container} bash -c "{bench_cmd}"', check=False)

    if rc != 0:
        fail(f"bench new-site failed (exit {rc}): {err[:300]}")
        if _site_exists(container, site):
            warn("Exit code non-zero but site directory exists — treating as success")
            return True
        return False

    if not _site_exists(container, site):
        fail(f"bench new-site exited 0 but site directory '{site}' is missing")
        return False

    ok(f"Site '{site}' created  (extra apps: {', '.join(apps) if apps else 'none'})")
    return True


def _setup_single_frappe_site(cfg: EnvConfig, state: dict):
    key = f"site_{cfg.stack_name}"
    if is_done(state, key):
        info(f"Site for '{cfg.stack_name}' already set up — skipping")
        return

    step(f"Setting up Frappe site: {cfg.stack_name}  →  {cfg.site_name or cfg.domain}")

    if not _wait_for_service(cfg.stack_name, "backend", timeout=900):
        fail(f"Backend not ready for '{cfg.stack_name}' after 15 min — skipping site creation")
        state_mark_error(state, key, "Backend 15-min timeout")
        return

    container = _get_backend_container(cfg.stack_name)
    _configure_bench_globals(container)
    sleep(2)

    site = cfg.site_name or cfg.domain
    if not _create_frappe_site(container, site, cfg.db_root_password, cfg.site_admin_password):
        state_mark_error(state, key, "Site creation failed or could not be verified")
        warn(f"Site '{site}' was NOT created successfully. Re-run the script to retry.")
        return

    state_mark_done(state, key)


def phase_create_frappe_sites(envs: List[EnvConfig], state: dict):
    header("Phase 10 — Frappe Site Creation")
    for cfg in envs:
        try:
            _setup_single_frappe_site(cfg, state)
        except Exception as e:
            fail(f"Site setup failed for '{cfg.stack_name}': {e}")
            state_mark_error(state, f"site_{cfg.stack_name}", str(e))
            if not confirm("Continue with remaining environments?", default=True):
                sys.exit(1)


# ── Deployment summary ─────────────────────────────────────────────────────────

def _print_deployment_summary(t_cfg: TraefikConfig, p_cfg: PortainerConfig,
                               ss_cfg: SharedServicesConfig, envs: List[EnvConfig]):
    print(f"\n{GREEN}{'═' * _W}{RESET}")
    print(f"{BOLD}{GREEN}  🎉  DEPLOYMENT COMPLETE{RESET}")
    print(f"{GREEN}{'═' * _W}{RESET}\n")

    print(f"  {BOLD}Access points{RESET}")
    print(f"    Traefik    →  https://{t_cfg.domain}")
    print(f"    {DIM}login: admin / <password set during setup>{RESET}")
    if p_cfg.enabled:
        print(f"    Portainer  →  https://{p_cfg.domain}")
        print(f"    {DIM}login: admin / <Portainer password>{RESET}")
    for env in envs:
        sn = env.site_name or env.domain
        print(f"    {env.stack_name:14s} →  https://{env.domain}  (site: {sn})")
        print(f"    {DIM}login: Administrator / <site admin password for '{env.stack_name}'>{RESET}")

    print(f"\n  {BOLD}Shared services{RESET}")
    if ss_cfg.mailpit_enabled:
        print(f"    Mailpit (shared) →  https://{ss_cfg.mailpit_domain}")
        print(f"    {DIM}All envs reach SMTP as  mailpit:1025  (overlay alias){RESET}")
    else:
        print(f"    Mailpit: disabled")

    backup_envs = [e for e in envs if e.has_backup]
    if backup_envs:
        print(f"\n  {BOLD}Backups (swarm-cronjob + backup-sites per stack){RESET}")
        print(f"    Scheduler: docker service logs shared-services_swarm-cronjob")
        for env in backup_envs:
            bdir = env.backup_dir.rstrip("/") + "/" + env.domain
            print(f"    {env.stack_name}: schedule={env.backup_schedule}"
                  f"  keep={env.backup_keep}  dir={bdir}")
        print(f"\n    {DIM}Manual backup: sudo /opt/frappe-deploy/backup.sh{RESET}")
        print(f"    {DIM}Restore:        sudo /opt/frappe-deploy/restore.sh{RESET}")

    print(f"\n  {BOLD}Notes{RESET}")
    print(f"    'migration' service runs once on deploy then exits — 0/1 is expected.")
    print(f"    Re-trigger: docker service scale <stack>_migration=1")
    print(f"\n  {BOLD}Useful commands{RESET}")
    print(f"    docker stack ls")
    print(f"    docker service ls")
    print(f"    docker service logs <stack>_backend -f")
    print(f"    sudo ./deploy-vps.py --add-env")
    print(f"    sudo ./deploy-vps.py --wipe-env")
    print(f"    sudo ./deploy-vps.py --status")
    print(f"\n{GREEN}{'═' * _W}{RESET}\n")


# ── Special flows ──────────────────────────────────────────────────────────────

def _show_status():
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


def _add_environment_flow(state: dict):
    """
    Add one or more new environments to an already-running deployment.
    Skips system setup and Traefik/Portainer — only writes new stack files,
    deploys new DB+app stacks, then redeploys shared-services.
    """
    header("Add Environment", "Extend an existing Frappe deployment with new environments")

    if not state.get("traefik") or not is_done(state, "traefik"):
        fail("No existing deployment found. Run without --add-env for a fresh setup.")
        sys.exit(1)

    existing_envs = _load_envs_from_state(state)
    info(f"Found {len(existing_envs)} existing environment(s):")
    for e in existing_envs:
        print(f"      {DIM}•{RESET}  {e.stack_name}  →  {e.domain}")
    print()

    new_envs, github_user, github_token = _collect_environments(existing_envs=existing_envs)

    step("Validating new environment configuration")
    if not _validate_env_uniqueness(new_envs, existing_envs=existing_envs):
        fail("Validation failed — correct the configuration and re-run with --add-env.")
        sys.exit(1)
    ok("All names and domains are unique")

    ss_raw = state.get("shared_services", {})
    ss_raw.setdefault("mailpit_enabled", False)
    ss_raw.setdefault("mailpit_domain",  "")
    existing_ss = SharedServicesConfig(**ss_raw)

    all_envs = existing_envs + new_envs
    t_cfg    = TraefikConfig(**state["traefik"])
    p_raw    = dict(state.get("portainer", {}))
    p_raw.setdefault("admin_password", "")
    p_raw.setdefault("enabled", False)
    p_raw.setdefault("domain",  "")
    p_cfg    = PortainerConfig(**p_raw)
    ss_cfg   = _collect_shared_services(all_envs, existing=existing_ss)

    print(f"\n  {BOLD}New environments to add:{RESET}")
    for e in new_envs:
        extras = [f"backup → {e.backup_dir}"] if e.has_backup else []
        print(f"    {e.stack_name:12s}  DB: {e.db_stack_name:22s}  {e.domain}"
              + (f"  [{', '.join(extras)}]" if extras else ""))
    print()

    if not confirm("Proceed?", default=True):
        print("  Aborted.")
        sys.exit(0)

    phase_generate_stack_files(t_cfg, p_cfg, ss_cfg, all_envs, new_envs=new_envs)
    _docker_login(github_user, github_token)

    header("Deploying New Environment Stacks")
    for cfg in new_envs:
        _deploy_single_environment(cfg, state)

    shared_yml = STACKS_DIR / "shared-services.yml"
    if shared_yml.exists():
        header("Redeploying Shared Services")
        step("Updating shared-services stack")
        info("Waiting 10s for new app networks to be ready…")
        sleep(10)
        _deploy_stack("shared-services", shared_yml, wait=10)
        _verify_backup_services(all_envs)
    else:
        info("shared-services not needed — skipping")

    state["environments"]    = [asdict(e) for e in all_envs]
    state["github_username"] = github_user
    state["shared_services"] = asdict(ss_cfg)
    state_save(state)

    phase_create_frappe_sites(new_envs, state)

    ok("Add-environment complete")
    _print_deployment_summary(t_cfg, p_cfg, ss_cfg, all_envs)


def _wipe_environment_flow(state: dict):
    """
    Remove ONE selected environment:
      1. Remove app stack and DB stack
      2. Optionally prune matching volumes
      3. Remove env from state and clean completed-steps keys
      4. Regenerate and redeploy shared-services (network list changed)
    """
    header("Wipe Environment", "Permanently remove one environment and its database")

    existing_envs = _load_envs_from_state(state)
    if not existing_envs:
        fail("No environments found in state. Nothing to wipe.")
        sys.exit(1)

    print(f"\n  {BOLD}Configured environments:{RESET}")
    for i, e in enumerate(existing_envs, 1):
        backup_note = " + backup" if e.has_backup else ""
        print(f"    {i}.  {e.stack_name:14s}  {e.domain}{backup_note}")
    print()

    while True:
        raw = input(f"  {BOLD}Enter environment number to wipe (or 'q' to abort): {RESET}").strip()
        if raw.lower() == "q":
            info("Aborted.")
            sys.exit(0)
        try:
            idx = int(raw) - 1
            if 0 <= idx < len(existing_envs):
                target = existing_envs[idx]
                break
            print(f"  {RED}Number out of range.{RESET}")
        except ValueError:
            print(f"  {RED}Enter a valid number.{RESET}")

    print(f"\n  {RED}{BOLD}⚠  DANGER  ⚠{RESET}")
    print(f"  {RED}This permanently destroys app stack, DB stack, and all data for:{RESET}")
    print(f"    {target.stack_name}  ({target.domain})")
    print()
    confirm_phrase = f"wipe {target.stack_name}"
    print(f"  Type exactly:  {BOLD}{confirm_phrase}{RESET}\n")
    if input("  Your confirmation: ").strip() != confirm_phrase:
        warn("Phrase did not match — wipe cancelled.")
        sys.exit(0)

    step(f"Removing app stack: {target.stack_name}")
    run(f"docker stack rm {target.stack_name}", check=False)
    ok(f"App stack '{target.stack_name}' removed")

    step(f"Removing DB stack: {target.db_stack_name}")
    run(f"docker stack rm {target.db_stack_name}", check=False)
    ok(f"DB stack '{target.db_stack_name}' removed")

    info("Waiting 20s for containers to fully stop…")
    sleep(20)

    if confirm(f"Also prune Docker volumes matching '{target.stack_name}-*'?", default=True):
        _, vol_out, _ = run(
            f"docker volume ls --format '{{{{.Name}}}}' | grep '^{target.stack_name}-'",
            check=False, silent=True,
        )
        vols = [v.strip() for v in vol_out.splitlines() if v.strip()]
        for v in vols:
            run(f"docker volume rm {v}", check=False)
            ok(f"Volume removed: {v}")
        if not vols:
            info("No matching volumes found.")

    for fname in (f"{target.stack_name}.yml", f"database-{target.stack_name}.yml"):
        p = STACKS_DIR / fname
        if p.exists():
            p.unlink()
            info(f"Removed stack file: {fname}")

    remaining_envs = [e for e in existing_envs if e.stack_name != target.stack_name]
    wipe_keys = {f"db_{target.stack_name}", f"app_{target.stack_name}",
                 f"site_{target.stack_name}"}
    state["completed"]    = [k for k in state["completed"] if k not in wipe_keys]
    state["environments"] = [asdict(e) for e in remaining_envs]
    state_save(state)
    ok(f"Environment '{target.stack_name}' removed from state")

    ss_raw = state.get("shared_services", {})
    ss_raw.setdefault("mailpit_enabled", False)
    ss_raw.setdefault("mailpit_domain",  "")
    ss_cfg = SharedServicesConfig(**ss_raw)

    if remaining_envs:
        step("Regenerating shared-services.yml (updated network list)")
        t_cfg = TraefikConfig(**state["traefik"])
        p_raw = dict(state.get("portainer", {}))
        p_raw.setdefault("admin_password", "")
        p_raw.setdefault("enabled", False)
        p_raw.setdefault("domain",  "")
        p_cfg = PortainerConfig(**p_raw)

        shared_content = _render_shared_services_stack(remaining_envs, ss_cfg)
        if shared_content:
            (STACKS_DIR / "shared-services.yml").write_text(shared_content)
            ok("shared-services.yml regenerated")
            sleep(10)
            _deploy_stack("shared-services", STACKS_DIR / "shared-services.yml", wait=10)
            ok("shared-services redeployed")
        else:
            stale = STACKS_DIR / "shared-services.yml"
            if stale.exists():
                stale.unlink()
            run("docker stack rm shared-services", check=False)
            info("shared-services removed (no remaining envs need it)")
    else:
        info("No environments remaining — skipping shared-services redeploy.")

    print(f"\n{GREEN}{'═' * _W}{RESET}")
    print(f"{BOLD}{GREEN}  ✓  Environment '{target.stack_name}' wiped{RESET}")
    print(f"{GREEN}{'═' * _W}{RESET}\n")
    if remaining_envs:
        print("  Remaining environments:")
        for e in remaining_envs:
            print(f"    {e.stack_name:14s}  →  https://{e.domain}")


# ── Main orchestrator ──────────────────────────────────────────────────────────

BANNER = f"""
{CYAN}╔{'═' * 62}╗
║{BOLD}   Frappe ERP — Complete Interactive VPS Setup              {RESET}{CYAN} ║
║   Packages → Docker → Swarm → Traefik → Stacks → Sites     ║
╚{'═' * 62}╝{RESET}
"""


def main():
    parser = argparse.ArgumentParser(description="Frappe ERP VPS setup")
    parser.add_argument("--reset",    action="store_true", help="Clear state and start over")
    parser.add_argument("--status",   action="store_true", help="Show deployment status")
    parser.add_argument("--add-env",  action="store_true",
                        help="Add environments to an existing deployment")
    parser.add_argument("--wipe-env", action="store_true",
                        help="Remove one selected environment")
    args = parser.parse_args()

    if args.status:
        _show_status()
        return

    _check_root()
    print(BANNER)

    BASE_DIR.mkdir(parents=True, exist_ok=True)
    LOGS_DIR.mkdir(parents=True, exist_ok=True)

    if args.reset and STATE_FILE.exists():
        STATE_FILE.unlink()
        ok("State cleared — starting fresh")

    state = state_load()

    if args.add_env:
        _add_environment_flow(state)
        return

    if args.wipe_env:
        _wipe_environment_flow(state)
        return

    _cleanup_existing_stacks(state)

    # ── Phase 1: System setup ────────────────────────────────────────────────
    phase_system_setup(state)

    # ── Phase 2: Gather configuration ────────────────────────────────────────
    t_cfg, p_cfg, ss_cfg, envs, github_user, github_token = phase_gather_configuration(state)

    # ── Phase 3: Validate ────────────────────────────────────────────────────
    phase_validate_configuration(envs)

    # ── Phase 4: Review and confirm ──────────────────────────────────────────
    phase_review_and_confirm(t_cfg, p_cfg, ss_cfg, envs)

    # ── Phase 5: Generate stack files ────────────────────────────────────────
    if not is_done(state, "files"):
        phase_generate_stack_files(t_cfg, p_cfg, ss_cfg, envs)
        state_mark_done(state, "files")
    else:
        info("Stack files already generated")

    # ── Phase 5b: Registry login ─────────────────────────────────────────────
    phase_registry_login(github_user, github_token, state)

    # ── Phase 6: Traefik ─────────────────────────────────────────────────────
    phase_deploy_traefik(t_cfg, state)

    # ── Phase 7: Portainer ───────────────────────────────────────────────────
    phase_deploy_portainer(p_cfg, state)

    # ── Phase 8: MariaDB + App stacks ────────────────────────────────────────
    phase_deploy_environments(envs, state)

    # ── Phase 9: Shared services ─────────────────────────────────────────────
    phase_deploy_shared_services(ss_cfg, envs, state)

    # ── Phase 10: Frappe site creation ───────────────────────────────────────
    phase_create_frappe_sites(envs, state)

    state_mark_done(state, "complete")
    _print_deployment_summary(t_cfg, p_cfg, ss_cfg, envs)


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n\n  {YELLOW}Interrupted.{RESET} Re-run to resume from where you left off.")
        sys.exit(0)
    except Exception as exc:
        fail(f"Fatal: {exc}")
        import traceback
        traceback.print_exc()
        sys.exit(1)