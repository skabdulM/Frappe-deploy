#!/usr/bin/env sh
set -eu

prompt() {
  label="$1"
  default="$2"
  printf "%s" "$label"
  if [ -n "$default" ]; then
    printf " [%s]" "$default"
  fi
  printf ": "
  read -r value
  if [ -z "$value" ]; then
    value="$default"
  fi
  printf "%s" "$value"
}

prompt_secret() {
  label="$1"
  printf "%s: " "$label"
  stty -echo
  read -r value
  stty echo
  printf "\n"
  printf "%s" "$value"
}

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required command: $1" >&2
    exit 1
  fi
}

require_cmd docker

repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
compose_dir="$repo_root/compose"
env_dir="$compose_dir/env"

use_defaults=$(prompt "Use default env names (dev/staging/prod)" "yes")
if [ "$use_defaults" = "yes" ]; then
  envs="dev staging prod"
else
  envs=$(prompt "Enter env names (space-separated)" "dev staging prod")
fi

traefik_domain=$(prompt "Traefik dashboard domain" "traefik.example.com")
portainer_domain=$(prompt "Portainer domain" "portainer.example.com")
admin_email=$(prompt "LetsEncrypt email" "admin@example.com")

stack_prefix=$(prompt "Stack prefix" "nms-erp")

for env in $envs; do
  echo "\nConfiguring $env"
  env_file="$env_dir/$env.env"

  if [ -f "$env_file" ]; then
    overwrite=$(prompt "Env file $env_file exists. Overwrite" "no")
    if [ "$overwrite" != "yes" ]; then
      continue
    fi
  fi

  version=$(prompt "Image tag for $env" "$env")
  bench_name=$(prompt "Bench name" "$env-nms-erp")
  sites=$(prompt "Site host(s) (comma-separated)" "$env.example.com")
  client_max_body_size=$(prompt "Client max body size" "50m")
  mariadb_network=$(prompt "MariaDB network name" "$env-mariadb-network")
  db_data_volume=$(prompt "MariaDB volume name" "$env-mariadb-data")
  sites_volume=$(prompt "Sites volume name" "$env-nms-erp_sites")
  backup_dir=""
  mailpit_host=""

  if [ "$env" = "prod" ]; then
    backup_dir=$(prompt "Backup directory (host path)" "/backups")
  fi

  if [ "$env" = "dev" ]; then
    mailpit_host=$(prompt "Mailpit host" "mailpit.dev.example.com")
  fi

  cat > "$env_file" <<EOF
VERSION=$version
BENCH_NAME=$bench_name
SITES=$sites
CLIENT_MAX_BODY_SIZE=$client_max_body_size
MARIADB_NETWORK=$mariadb_network
DB_DATA_VOLUME=$db_data_volume
SITES_VOLUME_NAME=$sites_volume
EOF

  if [ -n "$backup_dir" ]; then
    echo "BACKUP_DIR=$backup_dir" >> "$env_file"
  fi

  if [ -n "$mailpit_host" ]; then
    echo "MAILPIT_HOST=$mailpit_host" >> "$env_file"
  fi

db_password=$(prompt_secret "MariaDB root password for $env")

  stack_name="$stack_prefix-$env"
  set -a
  . "$env_file"
  set +a
  echo "Deploying MariaDB stack: ${stack_name}-db"
  DB_PASSWORD="$db_password" docker stack deploy -c "$compose_dir/mariadb.yml" --with-registry-auth "${stack_name}-db"

  echo "Deploying app stack: $stack_name"
  DB_PASSWORD="$db_password" docker stack deploy -c "$compose_dir/nmserp.yml" --with-registry-auth "$stack_name"

  if [ "$env" = "dev" ] && [ -n "${MAILPIT_HOST:-}" ]; then
    echo "Deploying Mailpit stack: ${stack_name}-mailpit"
    docker stack deploy -c "$compose_dir/mailpit.yml" --with-registry-auth "${stack_name}-mailpit"
  fi

  if [ "$env" = "prod" ]; then
    if [ -n "${BACKUP_DIR:-}" ] && [ ! -d "$BACKUP_DIR" ]; then
      mkdir -p "$BACKUP_DIR" 2>/dev/null || true
    fi
    echo "Deploying backup stack: ${stack_name}-backup"
    docker stack deploy -c "$compose_dir/backup-scheduler.yml" --with-registry-auth "${stack_name}-backup"
  fi

  db_password=""

done

traefik_stack=$(prompt "Deploy Traefik stack now" "yes")
if [ "$traefik_stack" = "yes" ]; then
  HASHED_PASSWORD=$(prompt "Traefik dashboard hashed password (htpasswd)" "")
  if [ -z "$HASHED_PASSWORD" ]; then
    echo "Missing HASHED_PASSWORD, skipping Traefik deploy." >&2
  else
    TRAEFIK_DOMAIN="$traefik_domain" EMAIL="$admin_email" HASHED_PASSWORD="$HASHED_PASSWORD" \
      docker stack deploy -c "$compose_dir/traefik.yml" --with-registry-auth traefik
  fi
fi

portainer_stack=$(prompt "Deploy Portainer stack now" "yes")
if [ "$portainer_stack" = "yes" ]; then
  PORTAINER_DOMAIN="$portainer_domain" \
    docker stack deploy -c "$compose_dir/portainer.yml" --with-registry-auth portainer
fi

echo "\nDone. Verify stacks with: docker stack ls"
