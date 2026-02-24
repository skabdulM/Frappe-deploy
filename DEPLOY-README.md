# 🚀 Frappe ERP Multi-Environment VPS Deployment

Complete automation for deploying Frappe ERP on Docker Swarm with dev, staging, and production environments.

## 📋 Quick Start

### 1. Verify Prerequisites

```bash
# Ensure Docker Swarm is initialized
docker info | grep Swarm

# If not initialized, run:
docker swarm init
```

### 2. Create Required Directory

```bash
mkdir -p /backups
sudo chmod 777 /backups
```

### 3. Verify Stack Files Exist

Stack files should be in `brand_club/stacks/`:
```bash
ls -la ./brand_club/stacks/
```

Should see:
- `traefik.yml`, `portainer.yml`, `ofelia.yml` (infrastructure)
- `database-{dev,staging,prod}.yml` (databases)
- `brandclub-{dev,staging,prod}.yml` (applications)

### 4. Run Deployment Script

```bash
python3 ./scripts/deploy-vps.py
```

The script will:
1. ✅ Check Docker and Swarm
2. 📋 Ask for configuration variables
3. 📦 Deploy infrastructure (Traefik → Portainer)
4. 🗄️ Deploy databases (MariaDB)
5. 🐳 Deploy applications (Frappe + Redis + Nginx)
6. ⏰ Deploy cron scheduler (Ofelia)
7. 🌍 Create Frappe sites
8. 📊 Display summary and next steps

**Total time:** ~15-20 minutes

### 5. Post-Deployment

After completing deployment:

1. **Add GHCR Credentials:**
   - Go to https://portainer.brandclub.site
   - Settings → Registries → Add GHCR registry
   - Use GitHub PAT with `read:packages` scope

2. **Test Access:**
   - Dev: https://erp-dev.brandclub.site
   - Staging: https://erp-staging.brandclub.site
   - Prod: https://erp.brandclub.site

3. **Check Status:**
   ```bash
   bash ./scripts/check-status.sh
   ```

## 📚 Documentation

### Main Guides
- 📖 [Deployment Guide](./scripts/DEPLOY-GUIDE.md) - Complete deployment documentation
- 🔧 [Backup & Restore Guide](./brand_club/BACKUP-RESTORE.md) - Backup strategy and commands
- 📝 [VPS Deployment Docs](./docs/vps-deployment.md) - Infrastructure overview

### Scripts
- 🚀 `scripts/deploy-vps.py` - Main deployment automation (senior DevOps level)
- 📊 `scripts/check-status.sh` - Quick health check of all services
- 💾 `brand_club/backup-prod.py` - Manual production backup
- 🔄 `brand_club/restore-backup.py` - Interactive backup restore

## 🏗️ Architecture

```
VPS (Docker Swarm)
├── Traefik (Reverse Proxy + SSL)
│   └── traefik network (public internet)
│
├── Portainer (Management UI)
│   └── portainer network
│
├── Ofelia (Cron Scheduler)
│   └── Watches swarm.cronjob labels
│
├── three environments (dev|staging|prod)
│   ├── Database Stack
│   │   ├── MariaDB 10.6 (isolated network)
│   │   └── Persistent volume
│   │
│   └── App Stack
│       ├── Backend (Gunicorn)
│       ├── Frontend (Nginx)
│       ├── WebSocket (Node.js)
│       ├── Queue Workers (bench worker)
│       ├── Scheduler (bench scheduler)
│       ├── Redis Cache & Queue
│       └── Backup Service (prod only, runs daily at 2 AM)
│
└── /backups (Host volume for backups)
```

## 🔐 Key Configurations

### Database Access
| Item | Value |
|------|-------|
| Host |`mariadb` (internal DNS) |
| Port | 3306 |
| User | `root` |
| Password | `$DB_ROOT_PASSWORD` (set during deployment) |

### Redis Access
| Item | Value |
|------|-------|
| Cache Host | `redis-cache:6379` |
| Queue Host | `redis-queue:6379` |
| Network | Internal to app stack |

### Important: Config Before Site Creation

The deployment script (and manual setup) must:
1. **First** set Frappe configuration:
   ```bash
   bench set-config -g db_host mariadb
   bench set-config -g redis_cache_host redis-cache:6379
   bench set-config -g redis_queue_host redis-queue:6379
   ```
2. **Then** create site:
   ```bash
   bench new-site erp.brandclub.site --db-host=mariadb --db-port=3306
   ```

If you set config after creating the site, it will fail with MariaDB host errors!

## 📊 Monitoring & Maintenance

### Health Check
```bash
bash ./scripts/check-status.sh
```

Shows:
- Docker Swarm status
- All stacks and services
- Container counts
- Disk usage
- Latest backups
- Useful commands

### View Logs
```bash
# Service logs
docker service logs <stack>_<service> -f

# Deployment logs
tail -f ./logs/deploy-*.log

# Container shell
docker exec -it <container-id> bash
```

### Backups
```bash
# Manual backup (production)
docker exec -it <backend-container> python3 backup-prod.py --site erp.brandclub.site --backup-dir /backups

# Restore from backup
docker exec -it <backend-container> python3 restore-backup.py --backup-dir /backups

# Check backup files
ls -lah /backups/erp.brandclub.site/
```

Automated backups run daily at **2 AM** via Ofelia cron scheduler.

## 🆘 Troubleshooting

### Services Keep Restarting
```bash
docker service logs <stack>_<service> -f
# Check for database, Redis, or configuration errors
```

### Site Creation Failed: "MariaDB host error"
**Cause:** Config not set before site creation

**Solution:**
```bash
docker exec -it <backend-container> bash
cd /home/frappe/frappe-bench

# Set config FIRST
bench set-config -g db_host mariadb

# Then create site
bench new-site erp.brandclub.site --db-host=mariadb --db-port=3306
```

### Domain Not Resolving
```bash
# Check DNS
nslookup erp.brandclub.site

# If not resolving, update DNS at your domain provider
# and wait for propagation (5-30 minutes)
```

### Permission Denied on /backups
```bash
sudo chmod 777 /backups
```

### Resume Interrupted Deployment
```bash
python3 ./scripts/deploy-vps.py
# Script loads state from .deploy_state.json and resumes from where it left off
```

## 🎯 What Gets Deployed

### Infrastructure ✅
- ✓ Traefik v2 (reverse proxy + Let's Encrypt SSL)
- ✓ Portainer CE 2.27.1 (Docker management UI)
- ✓ Ofelia (Docker cron scheduler)

### Per Environment (×3: dev, staging, prod)
- ✓ MariaDB 10.6 (database)
- ✓ Frappe v15 backend (Gunicorn)
- ✓ Nginx frontend
- ✓ Node.js WebSocket (socketio)
- ✓ Redis Cache
- ✓ Redis Queue
- ✓ Queue Workers (default, short, long)
- ✓ Scheduler
- ✓ Backup Service (prod only)

### Applications/Apps
- ✓ insights
- ✓ drive
- ✓ brand_club

### Features
- ✓ SSL/TLS with Let's Encrypt
- ✓ Automatic DNS-based routing
- ✓ Database isolation per environment
- ✓ Daily automated backups
- ✓ Interactive restore capability
- ✓ Email testing with Mailpit
- ✓ Full Docker Swarm native

## 🔧 Configuration Files

### Environment Variables
Set during deployment, stored in `.deploy_state.json`:
```
DB_ROOT_PASSWORD
DEV_DOMAIN
STAGING_DOMAIN 
PROD_DOMAIN
MAILPIT_DOMAIN
PORTAINER_DOMAIN
GITHUB_TOKEN
TAG_NAME
LETS_ENCRYPT_EMAIL
```

### Stack Files
Located in `brand_club/stacks/`:
- All stack files use environment variables via shell substitution
- Can be re-deployed without modifying files
- Each environment is completely isolated

## 📈 Scaling

### Scale Services Up
```bash
# Add more replicas
docker service scale brandclub-prod_backend=3 brandclub-prod_queue-long=2
```

### Adjust Resources
Edit stack files to modify CPU/memory limits:
```yaml
deploy:
  resources:
    limits:
      cpus: '2'
      memory: 2G
```

Then redeploy:
```bash
docker stack deploy -c brand_club/stacks/brandclub-prod.yml brandclub-prod
```

## 🚨 Important Notes

1. **Swarm Mode Only:** This setup requires Docker Swarm (all services use `deploy:`)
2. **Single Node OK:** Works fine with single manager node
3. **State Tracking:** `.deploy_state.json` allows resumable deployments
4. **Config Before Site:** Always set Frappe config before creating sites
5. **Backup Retention:** Keeps last 7 backups automatically
6. **SSL Auto-Renew:** Let's Encrypt certificates auto-renew via Traefik

## 📞 Support

For issues:
1. Check logs: `docker service logs <service> -f`
2. Run status check: `bash scripts/check-status.sh`
3. Review deployment guide: `scripts/DEPLOY-GUIDE.md`
4. Check Frappe logs: `docker exec -it <backend> tail -f logs/frappe.*`

## 📄 License & Credits

Created for Brand Club ERP deployment on Docker Swarm.

Utilizes:
- Frappe Framework v15
- Docker Swarm
- Traefik v2
- Ofelia
- MariaDB
- Nginx
- Node.js
- Redis
