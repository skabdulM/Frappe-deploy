#!/usr/bin/env python3
"""
MariaDB Frappe User Fixer

Fixes MariaDB user issues described in Frappe Docker troubleshooting docs.
It reads each site's site_config.json to get db_name/db_password and applies
the required grants and user fixes.
"""

import json
import shlex
import subprocess
import sys
from typing import Dict, List, Tuple


def run_cmd(cmd: List[str], check: bool = True) -> Tuple[int, str, str]:
    result = subprocess.run(cmd, capture_output=True, text=True)
    if check and result.returncode != 0:
        raise RuntimeError(result.stderr.strip())
    return result.returncode, result.stdout, result.stderr


def find_backend_containers() -> List[Dict[str, str]]:
    cmd = [
        "docker",
        "ps",
        "--format",
        "{{.ID}} {{.Names}} {{.Label \"com.docker.swarm.service.name\"}}",
    ]
    _, stdout, _ = run_cmd(cmd, check=False)
    containers = []
    for line in stdout.splitlines():
        parts = line.strip().split(" ", 2)
        if len(parts) != 3:
            continue
        container_id, name, service = parts
        if service.endswith("_backend") or "backend" in name:
            containers.append({"id": container_id, "name": name, "service": service})
    return containers


def get_sites_for_container(container_id: str) -> List[str]:
    cmd = [
        "docker",
        "exec",
        container_id,
        "bash",
        "-c",
        "find /home/frappe/frappe-bench/sites -maxdepth 2 -name site_config.json -print 2>/dev/null",
    ]
    _, stdout, _ = run_cmd(cmd, check=False)
    sites = []
    for line in stdout.splitlines():
        parts = line.strip().split("/")
        if len(parts) >= 6:
            site_name = parts[-2]
            if site_name and site_name not in ["assets", "logs"]:
                sites.append(site_name)
    return sorted(list(set(sites)))


def read_site_config(container_id: str, site: str) -> Dict:
    cmd = [
        "docker",
        "exec",
        container_id,
        "bash",
        "-c",
        f"cat /home/frappe/frappe-bench/sites/{site}/site_config.json 2>/dev/null",
    ]
    _, stdout, _ = run_cmd(cmd, check=False)
    if not stdout.strip():
        return {}
    try:
        return json.loads(stdout)
    except json.JSONDecodeError:
        return {}


def run_mysql(container_id: str, db_host: str, root_user: str, root_password: str, sql: str, check: bool = True) -> None:
    mysql_cmd = f"mysql -u{root_user} -p{root_password} -h{db_host} -e {shlex.quote(sql)}"
    cmd = ["docker", "exec", "-i", container_id, "bash", "-c", mysql_cmd]
    run_cmd(cmd, check=check)


def fix_site(container_id: str, site: str, db_host: str, root_user: str, root_password: str) -> bool:
    config = read_site_config(container_id, site)
    db_name = config.get("db_name")
    db_password = config.get("db_password")

    if not db_name or not db_password:
        print(f"❌ Missing db_name/db_password in site_config.json for {site}")
        return False

    print(f"\n🔧 Fixing MariaDB user for site: {site}")
    print(f"   DB User: {db_name}")

    try:
        run_mysql(
            container_id,
            db_host,
            root_user,
            root_password,
            f"CREATE DATABASE IF NOT EXISTS `{db_name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;",
            check=False,
        )

        run_mysql(
            container_id,
            db_host,
            root_user,
            root_password,
            f"CREATE USER IF NOT EXISTS '{db_name}'@'%' IDENTIFIED BY '{db_password}';",
            check=False,
        )

        run_mysql(
            container_id,
            db_host,
            root_user,
            root_password,
            f"UPDATE mysql.global_priv SET Host = '%' WHERE User = '{db_name}';",
            check=False,
        )

        run_mysql(
            container_id,
            db_host,
            root_user,
            root_password,
            f"UPDATE mysql.user SET Host = '%' WHERE User = '{db_name}';",
            check=False,
        )

        run_mysql(
            container_id,
            db_host,
            root_user,
            root_password,
            f"SET PASSWORD FOR '{db_name}'@'%' = PASSWORD('{db_password}');",
            check=False,
        )

        run_mysql(
            container_id,
            db_host,
            root_user,
            root_password,
            f"GRANT ALL PRIVILEGES ON `{db_name}`.* TO '{db_name}'@'%' IDENTIFIED BY '{db_password}' WITH GRANT OPTION;",
            check=False,
        )

        run_mysql(container_id, db_host, root_user, root_password, "FLUSH PRIVILEGES;", check=False)

        print("   ✓ Permissions fixed")
        return True
    except RuntimeError as exc:
        print(f"   ❌ Failed: {exc}")
        return False


def pick_sites(site_index: List[Dict[str, str]]) -> List[Dict[str, str]]:
    if not site_index:
        return []

    print("\n📍 Sites detected:")
    for idx, entry in enumerate(site_index, start=1):
        print(f"  {idx}. {entry['site']}  [{entry['service']}]")

    raw = input("\nSelect sites (comma-separated or 'all'): ").strip().lower()
    if raw == "all":
        return site_index

    selections = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        if not part.isdigit():
            continue
        idx = int(part)
        if 1 <= idx <= len(site_index):
            selections.append(site_index[idx - 1])
    return selections


def interactive() -> int:
    print("\n" + "=" * 70)
    print("🔧 MariaDB Frappe User Fixer")
    print("=" * 70)

    db_host = input("DB Host [mariadb]: ").strip() or "mariadb"
    root_user = input("DB Root User [root]: ").strip() or "root"
    root_password = input("DB Root Password [mannan@123]: ").strip() or "mannan@123"

    containers = find_backend_containers()
    site_index = []

    for container in containers:
        sites = get_sites_for_container(container["id"])
        for site in sites:
            site_index.append(
                {
                    "site": site,
                    "container_id": container["id"],
                    "service": container["service"],
                }
            )

    if not site_index:
        print("\n⚠️  No sites detected. Enter site name and backend container ID.")
        site = input("Site name: ").strip()
        container_id = input("Backend container ID: ").strip()
        if not site or not container_id:
            print("❌ Missing site or container ID")
            return 1
        site_index = [{"site": site, "container_id": container_id, "service": "manual"}]

    selected = pick_sites(site_index)
    if not selected:
        print("❌ No sites selected")
        return 1

    print("\n✅ Will fix:")
    for entry in selected:
        print(f"  - {entry['site']} ({entry['service']})")

    confirm = input("Proceed? (y/n): ").strip().lower()
    if confirm != "y":
        print("Cancelled")
        return 1

    fixed = 0
    for entry in selected:
        ok = fix_site(entry["container_id"], entry["site"], db_host, root_user, root_password)
        fixed += 1 if ok else 0

    print("\n" + "=" * 70)
    print(f"✅ Fixed {fixed}/{len(selected)} sites")
    print("=" * 70)
    return 0 if fixed == len(selected) else 1


def main() -> int:
    return interactive()


if __name__ == "__main__":
    sys.exit(main())
