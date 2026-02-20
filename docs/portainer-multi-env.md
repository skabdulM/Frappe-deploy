# Portainer multi-environment setup (dev, staging, prod)

This repo already supports multi-environment stacks via environment files. The recommended approach in Portainer is one Swarm environment with multiple stacks (dev/staging/prod). If you must have separate Portainer environments, use separate Swarm clusters or separate Portainer instances.

## 1) One-time infrastructure stacks

Deploy these once per Swarm:

- Traefik: compose/traefik.yml
- Portainer: compose/portainer.yml
- Swarm cron (optional): compose/swarm-cron.yml

## 2) Per-environment stacks

Each environment uses the same compose files with a different env file:

- MariaDB: compose/mariadb.yml
- ERP stack: compose/nmserp.yml
- Backup scheduler (prod only): compose/backup-scheduler.yml
- Mailpit (dev only): compose/mailpit.yml

Example stack names:

- nms-erp-dev
- nms-erp-staging
- nms-erp-prod

Use these env files as starting points:

- compose/env/dev.env
- compose/env/staging.env
- compose/env/prod.env

Key variables:

- VERSION: image tag (matches branch names develop, staging, main)
- BENCH_NAME: used for the bench network name
- SITES: hostnames used by Traefik (comma-separated for multiple domains)
- MARIADB_NETWORK: shared network name between db and app
- DB_DATA_VOLUME: MariaDB data volume name
- SITES_VOLUME_NAME: sites volume name used by backups
- BACKUP_DIR: host path where daily backups are stored (prod only)
- MAILPIT_HOST: hostname for Mailpit UI (dev only)

## 3) Mailservice (postfix_relay) later

Create a separate stack named postfix_relay when ready. If your app needs to reach it by service name, connect both stacks to a shared external network (for example, traefik-public or a dedicated smtp-public network).

## 3.1) Mailpit for dev

Deploy compose/mailpit.yml in the dev stack. It exposes the Mailpit web UI via Traefik and SMTP at mailpit:1025 within the dev bench network.

## 4) Traefik host mapping, SSL, and TLS

1) DNS

- Create A/AAAA records for each environment host pointing to the public IP of your Traefik node.
- Example: dev.example.com, staging.example.com, erp.example.com

2) Traefik dashboard and Portainer domains

- Set TRAEFIK_DOMAIN and PORTAINER_DOMAIN in the Traefik/Portainer stack environment.
- The dashboard/Portainer routers already use Host(`${TRAEFIK_DOMAIN}`) and Host(`${PORTAINER_DOMAIN}`).

3) App host mapping per environment

- Set SITES in each env file to the hostname that should route to that stack.
- For a single host: SITES=dev.example.com
- For multiple hosts: SITES=dev.example.com`,`dev2.example.com

4) TLS/SSL

- Traefik uses the Let's Encrypt resolver named le and TLS-ALPN challenge.
- Ensure ports 80 and 443 are open to the Traefik node and DNS is public.
- Certificates are stored in the traefik-public-certificates volume.
- If you use private/internal domains, switch to DNS challenge or mount your own certs and update compose/traefik.yml.

HTTP requests are redirected to HTTPS by the https-redirect middleware already defined in the Traefik stack.

## 4.1) Daily backups on the VPS (prod only)

The backup stack runs daily at 00:00 and copies backups into /backups/YYYY-MM-DD on the VPS, then deletes folders older than 7 days. Ensure /backups exists on the node that runs the backup service.

## 5) Automated deployments (app repo)

Keep CI/CD in your Frappe app repository. Build the image there, tag by branch (develop, staging, main), push to your registry, and trigger Portainer webhooks per environment.

If you prefer Frappe Docker conventions, align your build args and runtime envs with their official docs while keeping the same Portainer stack pattern.

## 6) One-shot setup script

Use scripts/setup-multi-env.sh to generate env files and deploy stacks. The script:

- Prompts for per-environment values (domains, networks, volumes)
- Prompts for MariaDB root password per environment
- Deploys MariaDB and app stacks for each environment
- Optionally deploys Traefik and Portainer

Run:

	chmod +x scripts/setup-multi-env.sh
	./scripts/setup-multi-env.sh

Note: You must provide a Traefik dashboard htpasswd hash when prompted.

## 7) Portainer UI stack template checklist

Use this to create stacks in Portainer by pointing at this repo (or your fork).

1) Create or verify the Swarm environment

- Environments -> Add environment -> Docker Swarm -> Name it (for example, vps-swarm)
- Connect to the agent endpoint and validate status is healthy

2) Add the Git repository

- Stacks -> Add stack -> Git repository
- Repository URL: your nms-builder repo
- Repository reference: main (or the branch you want)
- Compose path: compose/traefik.yml

3) Deploy Traefik stack

- Stack name: traefik
- Environment variables:
	- TRAEFIK_DOMAIN
	- EMAIL
	- HASHED_PASSWORD (htpasswd format)
- Deploy the stack

4) Deploy Portainer stack

- Add stack -> Git repository
- Compose path: compose/portainer.yml
- Stack name: portainer
- Environment variables:
	- PORTAINER_DOMAIN
- Deploy the stack

5) Create an environment-specific stack (repeat for dev/staging/prod)

- Add stack -> Git repository
- Compose path: compose/mariadb.yml
- Stack name: nms-erp-<env>-db
- Environment variables:
	- DB_PASSWORD
	- MARIADB_NETWORK (for example, dev-mariadb-network)
	- DB_DATA_VOLUME (for example, dev-mariadb-data)
- Deploy the stack

- Add stack -> Git repository
- Compose path: compose/nmserp.yml
- Stack name: nms-erp-<env>
- Environment variables:
	- VERSION
	- BENCH_NAME
	- SITES
	- CLIENT_MAX_BODY_SIZE
	- MARIADB_NETWORK
- Deploy the stack

6) Dev-only: Mailpit

- Add stack -> Git repository
- Compose path: compose/mailpit.yml
- Stack name: nms-erp-dev-mailpit
- Environment variables:
	- BENCH_NAME
	- MAILPIT_HOST
- Deploy the stack

7) Prod-only: Backup scheduler

- Add stack -> Git repository
- Compose path: compose/backup-scheduler.yml
- Stack name: nms-erp-prod-backup
- Environment variables:
	- VERSION
	- BENCH_NAME
	- MARIADB_NETWORK
	- SITES_VOLUME_NAME
	- BACKUP_DIR
- Deploy the stack
