# Brand Club - Quick Start Guide

## Prerequisites

- Ubuntu 22.04 LTS or Debian 11+
- Docker 24.0+ installed
- DNS configured pointing to your server
- Domain names ready

## Installation (5 minutes)

### 1. Clone Repository

```bash
git clone https://github.com/YOUR_ORG/brand_club.git
cd brand_club
```

### 2. Run Setup Script

```bash
chmod +x scripts/setup-brandclub.sh
./scripts/setup-brandclub.sh
```

The script will ask for:
- Docker registry details
- Domain names (dev, staging, prod)
- Database passwords
- Admin password
- Backup directory

### 3. Wait for Services

```bash
# Check stack status
docker stack ls

# Check service health
docker stack ps brandclub-dev
docker stack ps brandclub-staging
docker stack ps brandclub-prod

# View logs
docker service logs -f brandclub-dev_backend
```

### 4. Create Frappe Sites

After services are healthy (2-3 minutes):

```bash
# Development
CONTAINER=$(docker ps -q -f name=brandclub-dev_backend)
docker exec -it $CONTAINER bench new-site dev.brandclub.com \
  --admin-password 'YOUR_PASSWORD' \
  --db-root-password 'YOUR_DB_PASSWORD'

docker exec -it $CONTAINER bench --site dev.brandclub.com install-app brand_club
```

### 5. Access Your Sites

- **Development**: https://dev.brandclub.com
- **Mailpit**: https://mailpit.dev.brandclub.com
- **Staging**: https://staging.brandclub.com
- **Production**: https://brandclub.com

## GitHub CI/CD Setup

### 1. Add Secrets to GitHub

Go to **Settings → Secrets → Actions**:

```
DOCKER_REGISTRY_URL=ghcr.io
DOCKER_REGISTRY_USERNAME=your-username
DOCKER_REGISTRY_TOKEN=your-github-token

FRAPPE_VERSION=version-15
PYTHON_VERSION=3.11.6
NODE_VERSION=18.18.2

PORTAINER_WEBHOOK_DEV=https://portainer.../api/webhooks/xxx
PORTAINER_WEBHOOK_STAGING=https://portainer.../api/webhooks/yyy
PORTAINER_WEBHOOK_PROD=https://portainer.../api/webhooks/zzz
```

### 2. Create Branches

```bash
git checkout -b develop
git push origin develop

git checkout -b staging
git push origin staging
```

### 3. Test CI/CD

```bash
# Make a change
echo "# Test" >> README.md
git add .
git commit -m "Test CI/CD"
git push origin develop
```

Check **Actions** tab in GitHub to see deployment progress.

## Common Commands

```bash
# View stacks
docker stack ls

# View services in a stack
docker stack ps brandclub-dev

# View logs
docker service logs -f brandclub-dev_backend

# Scale workers
docker service scale brandclub-prod_queue-default=3

# Update stack
docker stack deploy -c stacks/brandclub-dev.yml brandclub-dev

# Remove stack
docker stack rm brandclub-dev
```

## Troubleshooting

### Services not starting?

```bash
docker service ps brandclub-dev_backend --no-trunc
docker service logs brandclub-dev_backend
```

### Can't access site?

- Check DNS configuration
- Verify Traefik is running: `docker service ps traefik_traefik`
- Check service labels: `docker service inspect brandclub-dev_frontend | grep traefik`

### Database connection failed?

```bash
# Test database connectivity
CONTAINER=$(docker ps -q -f name=brandclub-dev_backend)
docker exec -it $CONTAINER ping db
docker exec -it $CONTAINER nc -zv db 3306
```

## Next Steps

1. Configure email settings in Frappe
2. Set up regular backups (production has automated daily backups)
3. Configure monitoring
4. Set up off-site backup sync
5. Review security settings

## Support

- [Full Documentation](README.md)
- [Frappe Forum](https://discuss.frappe.io/)
- [Docker Swarm Docs](https://docs.docker.com/engine/swarm/)
