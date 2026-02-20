# VPS deployment guide

This repo is a builder and deployment helper for your VPS. CI/CD belongs in your Frappe app repo.

## Prerequisites

- A VPS with Docker installed
- A public IP and DNS control for your domains
- Open ports: 80 and 443 to the Traefik node
- A Docker registry containing your built app images

## 1) Initialize Docker Swarm

Run on the VPS:

  docker swarm init

If you will use worker nodes, join them with the join token.

## 2) Label the manager node

Traefik and Portainer stacks require node labels for placement.

  docker node update --label-add traefik-public.traefik-public-certificates=true <manager-node>
  docker node update --label-add portainer.portainer-data=true <manager-node>

## 3) Prepare host directories

Backups are stored on the VPS at /backups.

  mkdir -p /backups

## 4) Deploy infrastructure stacks

Use the setup script or deploy manually:

- compose/traefik.yml
- compose/portainer.yml
- compose/swarm-cron.yml (optional)

## 5) Configure env files

Set values per environment:

- compose/env/dev.env
- compose/env/staging.env
- compose/env/prod.env

Important values:

- SITES for each environment
- MARIADB_NETWORK, DB_DATA_VOLUME, SITES_VOLUME_NAME
- MAILPIT_HOST for dev
- BACKUP_DIR for prod

## 6) Deploy app stacks

Option A: run the script

  chmod +x scripts/setup-multi-env.sh
  ./scripts/setup-multi-env.sh

Option B: deploy manually per environment

  set -a
  . compose/env/prod.env
  set +a
  docker stack deploy -c compose/mariadb.yml --with-registry-auth nms-erp-prod-db
  docker stack deploy -c compose/nmserp.yml --with-registry-auth nms-erp-prod
  docker stack deploy -c compose/backup-scheduler.yml --with-registry-auth nms-erp-prod-backup

## 7) GitHub configuration (app repo)

Your Frappe app repo should:

- Build images on push to develop, staging, main
- Tag images with the branch name
- Push to your registry
- Trigger Portainer webhooks per environment

Typical secrets needed in the app repo:

- REGISTRY
- REGISTRY_USERNAME
- REGISTRY_PASSWORD
- IMAGE_NAME
- PORTAINER_WEBHOOK_DEV
- PORTAINER_WEBHOOK_STAGING
- PORTAINER_WEBHOOK_PROD

## 8) Post-deploy checks

- docker stack ls
- docker service ls
- Verify Traefik dashboard and app URLs
- Verify backups in /backups
