# VPS Deployment Guide

Complete automated deployment script for Frappe ERP multi-environment setup on Docker Swarm.

## Overview

This deployment script automates the entire VPS setup in the following sequence:

```
1. Preflight Checks (Docker, Swarm, Directories)
   ↓
2. Environment Variables Configuration
   ↓
3. Stack Files Verification
   ↓
4. Traefik Reverse Proxy (with Let's Encrypt SSL)
   ↓
5. Portainer Management UI
   ↓
6. Database Stacks (dev, staging, prod)
   ↓
7. Application Stacks (dev, staging, prod)
   ↓
8. Ofelia Cron Scheduler
   ↓
9. Frappe Site Creation (with proper config before site creation)
   ↓
10. Deployment Summary
```

## Prerequisites

### System Requirements

- **OS:** Linux VPS (Ubuntu 20.04+)
- **Docker:** v24+
- **Docker Swarm:** Initialized (single or multi-node)
- **Disk Space:** 50GB+ (for databases, backups, logs)
- **Memory:** 8GB+ recommended

### Pre-Deployment Setup

1. **Initialize Docker Swarm** (if not already done):
   ```bash
   docker swarm init
   ```

2. **Create required directories** with proper permissions:
   ```bash
   mkdir -p /backups
   sudo chmod 777 /backups
   ```

3. **Verify all stack files exist** in `brand_club/stacks/`:
   - `traefik.yml`
   - `portainer.yml`
   - `database-{dev,staging,prod}.yml`
   - `brandclub-{dev,staging,prod}.yml`
   - `ofelia.yml` (optional, script creates as service if missing)

## Environment Variables

The script will prompt you for these variables during setup:

| Variable | Default | Required | Notes |
|----------|---------|----------|-------|
| DB_ROOT_PASSWORD | mannan@123 | ✓ | MariaDB root password |
| DEV_DOMAIN | erp-dev.brandclub.site | ✓ | Dev environment domain |
| STAGING_DOMAIN | erp-staging.brandclub.site | ✓ | Staging environment domain |
| PROD_DOMAIN | erp.brandclub.site | ✓ | Production environment domain |
| MAILPIT_DOMAIN | mailpit.brandclub.site | ✓ | Email testing service |
| PORTAINER_DOMAIN | portainer.brandclub.site | ✓ | Management UI domain |
| GITHUB_TOKEN | - | ✓ | GitHub PAT for GHCR access (read:packages) |
| TAG_NAME | main | ✓ | Docker image tag to deploy |
| LETS_ENCRYPT_EMAIL | admin@brandclub.site | ✓ | For SSL certificate generation |

## Usage

### Basic Deployment

```bash
# Run the deployment script
python3 /home/abdul/Projects/Frappe-deploy/scripts/deploy-vps.py
```

### What Happens

1. **Preflight Checks (1-2 min)**
   - Verifies Docker installation
   - Checks Docker Swarm status
   - Creates required directories

2. **Configuration Input (2-3 min)**
   - You'll be prompted for environment variables
   - Defaults are provided (press Enter to use them)
   - GitHub token is required

3. **Stack Verification (1 min)**
   - Script checks all required stack files exist
   - If any are missing, it will tell you and exit

4. **Traefik Deployment (5-10 sec)**
   - Deploys reverse proxy with Let's Encrypt
   - Auto-configures SSL for all domains

5. **Portainer Deployment (10-15 sec)**
   - Launches management UI
   - Accessible immediately at specified domain

6. **Database Stacks Deployment (15-20 sec)**
   - Deploys MariaDB 10.6 for dev, staging, prod
   - Separate networks for isolation
   - Waits 30s for full initialization

7. **Application Stacks Deployment (20-30 sec)**
   - Deploys Frappe, Redis, Nginx for each environment
   - Services reach "running" state
   - Waits 20s for stabilization

8. **Ofelia Deployment (5-10 sec)**
   - Deploys cron scheduler service
   - Enables swarm.cronjob labels for automated tasks

9. **Site Creation (3-5 min per site)**
   - Waits for backend containers to be ready
   - **Sets Frappe config BEFORE site creation** (important!)
   - Creates sites: erp-{dev|staging|prod}.brandclub.site
   - Installs apps: insights, drive, brand_club
   - Validates MariaDB connectivity

10. **Summary Display**
    - Shows all access points
    - Provides next steps
    - Lists important credentials

**Total Time:** 15-20 minutes for complete setup

## Monitoring Deployment

### View Logs

All deployment logs are saved to:
```bash
ls -lah /home/abdul/Projects/Frappe-deploy/logs/
```

View real-time logs:
```bash
docker service logs <service-name> -f
```

### Check Stack Status

```bash
# List all stacks
docker stack ls

# Check specific stack
docker stack ps brandclub-prod

# View service logs
docker service logs brandclub-prod_backend -f
```

### Interactive Debugging

If something fails mid-deployment, you can:

1. **Check container logs:**
   ```bash
   docker service logs <stack>_<service> -f
   ```

2. **Access container bash:**
   ```bash
   CONTAINER_ID=$(docker ps --filter "label=com.docker.swarm.service.name=brandclub-prod_backend" --format "{{.ID}}")
   docker exec -it $CONTAINER_ID bash
   ```

3. **Manual site creation (if automated step fails):**
   ```bash
   docker exec -it <backend-container> bash
   cd /home/frappe/frappe-bench
   
   # Set config first (CRITICAL!)
   bench set-config -g db_host mariadb
   bench set-config -g redis_cache_host redis-cache:6379
   bench set-config -g redis_queue_host redis-queue:6379
   
   # Then create site
   bench new-site erp.brandclub.site --db-host=mariadb --db-port=3306
   
   # Install apps
   bench install-app insights drive brand_club --site erp.brandclub.site
   ```

## Post-Deployment Steps

### 1. GHCR Authentication (Required for image pulls)

Go to Portainer UI at `https://portainer.brandclub.site`:

1. Navigate to **Settings → Registries**
2. Click **+ Add Registry**
3. Configure:
   - **Name:** ghcr
   - **Registry URL:** ghcr.io
   - **Username:** Your GitHub username
   - **Password:** Your GitHub PAT (read:packages scope)

### 2. Verify Services

Check all services are running:
```bash
bash scripts/check-status.sh
```

Or manually in Portainer:
- Services tab should show all services as "Running"
- No service should be restarting

### 3. Test Site Access

Visit your domains in browser:
- Dev: https://erp-dev.brandclub.site
- Staging: https://erp-staging.brandclub.site  
- Production: https://erp.brandclub.site

Wait 1-2 minutes for services to be fully ready before accessing.

### 4. GitHub Actions CI/CD Setup

Add these secrets to your GitHub repository:

```
DOCKER_REGISTRY_URL=ghcr.io
DOCKER_REGISTRY_USERNAME=<your-github-username>
DOCKER_REGISTRY_TOKEN=<your-github-pat>
DOCKER_ORG=brandclub
FRAPPE_VERSION=version-15
PYTHON_VERSION=3.11.6
NODE_VERSION=18.18.2
PORTAINER_WEBHOOK_DEV=<webhook-url>
PORTAINER_WEBHOOK_STAGING=<webhook-url>
PORTAINER_WEBHOOK_PROD=<webhook-url>
```

Create webhooks in Portainer for auto-deployment when images are pushed.

### 5. Test Backup Service

Production stack includes automated daily backups at 2 AM. Test manually:

```bash
# Force backup to run now
docker service update --force brandclub-prod_backup

# View backup logs
docker service logs brandclub-prod_backup -f

# Check backup files
ls -lah /backups/erp.brandclub.site/
```

Backups are stored in: `/backups/erp.brandclub.site/`

## Resuming Interrupted Deployment

If deployment is interrupted, you can resume by running the script again:

```bash
python3 /home/abdul/Projects/Frappe-deploy/scripts/deploy-vps.py
```

The script will:
1. Load previous state from `.deploy_state.json`
2. Ask if you want to use previously configured variables (or reconfigure)
3. Skip completed steps
4. Continue from where it left off

## Troubleshooting

### Services Keep Restarting

Check logs for the specific service:
```bash
docker service logs <stack>_<service> -f
```

Common issues:
- **Database connectivity:** Verify DB_HOST is set to `mariadb`
- **Application crashed:** Check Redis and MariaDB are running
- **Image pull failed:** Verify GHCR credentials in Portainer

### Site Creation Failed: MariaDB Host Error

**Most common cause:** Not setting config BEFORE creating site.

The script does this automatically:
```bash
bench set-config -g db_host mariadb
bench set-config -g redis_cache_host redis-cache:6379
bench set-config -g redis_queue_host redis-queue:6379
# THEN create site
bench new-site erp.brandclub.site --db-host=mariadb --db-port=3306
```

### Port Conflicts

If ports 80, 443, 8080 are in use:

1. Check what's using them:
   ```bash
   sudo lsof -i :80
   sudo lsof -i :443
   sudo lsof -i :8080
   ```

2. Stop conflicting services or change stack configurations

### Domain Not Resolving

Ensure your DNS records point to your VPS IP:

```bash
nslookup erp.brandclub.site
# Should return your VPS IP
```

If not resolving:
- Update DNS records at your domain provider
- Wait for DNS propagation (5-30 minutes)
- Clear your local DNS cache

### Backup Permission Denied

```bash
sudo chmod 777 /backups
```

## Monitoring & Maintenance

### Regular Checks

```bash
# Check stack status
docker stack ps brandclub-prod

# View resource usage
docker stats

# Check disk space
df -h

# Check backup rotation
ls -lah /backups/erp.brandclub.site/
```

### Logs Rotation

Logs are automatically saved to:
```
/home/abdul/Projects/Frappe-deploy/logs/
```

No manual rotation needed (script creates timestamped logs).

### Database Maintenance

For MariaDB optimization:
```bash
# Access MySQL CLI
docker exec -it <mariadb-container> mysql -u root -p

# Check databases
SHOW DATABASES;
USE frappe;
SHOW TABLES;
```

## Undeploying / Cleanup

To remove all services and stacks:

```bash
# Remove in reverse order
docker stack rm brandclub-prod brandclub-staging brandclub-dev
docker stack rm brandclub-db-prod brandclub-db-staging brandclub-db-dev
docker stack rm portainer
docker stack rm traefik

# Clean up volumes (CAUTION: this deletes data!)
# docker volume prune

# Keep backups (not in volumes)
ls -lah /backups/
```

## Performance Tuning

### For High Traffic

1. **Scale services:**
   ```bash
   docker service scale brandclub-prod_backend=3
   docker service scale brandclub-prod_queue-long=2
   ```

2. **Increase resource limits** in stack YAML:
   ```yaml
   deploy:
     resources:
       limits:
         cpus: '4'
         memory: 4G
   ```

3. **Enable Redis persistence:**
   Already configured in the stacks

### Backup Retention

The backup script keeps last 7 backups. Modify in stack file if needed:
```bash
# Change this line in backup command:
ls -t *-database* | tail -n +8 | while read old_db; do
  # 8 means keep last 7 (tail -n +8 skips first 7)
```

## Support & Documentation

- **Traefik Docs:** https://doc.traefik.io
- **Frappe Docs:** https://frappeframework.com/docs
- **Docker Docs:** https://docs.docker.com
- **Portainer Docs:** https://docs.portainer.io

## Script Architecture

### Class Structure

- **Config:** Configuration paths and defaults
- **StateManager:** Tracks deployment progress for resumability
- **Shell:** Safe command execution with error handling
- **PreflightChecks:** System prerequisites verification
- **EnvironmentSetup:** Interactive variable prompt
- **StackDeployer:** Docker stack deployment logic
- **SiteManager:** Frappe site creation with proper sequencing
- **VPSDeployer:** Main orchestrator

### State File

Deployment state is saved to:
```
/home/abdul/Projects/Frappe-deploy/.deploy_state.json
```

This allows resuming if deployment is interrupted.

## Credits

Created for Brand Club ERP deployment on Docker Swarm with:
- Modern Python 3 with proper typed hints
- Comprehensive logging with file and console output
- Resumable deployment with state tracking
- Interactive prompts for configuration
- Proper error handling and retries
- Production-ready sequencing
