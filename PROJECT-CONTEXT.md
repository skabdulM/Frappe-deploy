# Frappe ERP Multi-Environment Deployment - Project Context

**Last Updated:** February 27, 2026  
**Project:** Brand Club ERP Deployment on Docker Swarm  
**Environment:** VPS with Dev/Staging/Production isolation

---

## Table of Contents

1. [Project Overview](#project-overview)
2. [Architecture Evolution](#architecture-evolution)
3. [Problems Encountered & Solutions](#problems-encountered--solutions)
4. [Critical Decisions Made](#critical-decisions-made)
5. [Final Architecture](#final-architecture)
6. [Deployment Workflow](#deployment-workflow)
7. [Key Learnings](#key-learnings)
8. [Configuration Reference](#configuration-reference)

---

## Project Overview

### Objective
Deploy a Frappe v15 ERP system (Brand Club custom app) on a VPS using Docker Swarm with three isolated environments (dev/staging/production), automated backups, and proper SSL certificates.

### Initial Requirements
- ✅ Three separate environments: dev, staging, production
- ✅ Each environment with isolated databases and networks
- ✅ Traefik reverse proxy with Let's Encrypt SSL
- ✅ Portainer for UI management
- ✅ Automated daily backups for production
- ✅ GitHub Container Registry (GHCR) for private Docker images
- ✅ Deployment automation scripts
- ✅ Health monitoring and status checks

### Technology Stack
- **Container Orchestration:** Docker Swarm (single-node cluster)
- **Reverse Proxy:** Traefik v2 with Let's Encrypt
- **Database:** MariaDB 10.6 (separate instance per environment)
- **Cache/Queue:** Redis 6.2-alpine (cache + queue pairs per environment)
- **Application:** Frappe v15 + custom Brand Club app
- **Registry:** GitHub Container Registry (ghcr.io/brandclub/brand-club-erp)
- **Backup Scheduler:** Ofelia (mcuadros/ofelia:latest)
- **Management UI:** Portainer CE 2.27.1
- **Automation:** Python 3 + Bash scripts

---

## Architecture Evolution

### Phase 1: Initial Manual Deployment (Week 1)
**Approach:** Manual Portainer UI deployment for each stack  
**Problems:**
- Tedious manual configuration for 3 environments
- No state tracking - couldn't resume interrupted deployments
- Difficult to replicate setup on another machine
- GHCR registry credentials had to be added manually after deployment

### Phase 2: Basic Automation Script (Week 2)
**Approach:** Python script with hardcoded paths (`/home/abdul/Projects/Frappe-deploy`)  
**Problems:**
- Script only worked on development machine
- Couldn't run on VPS without path modifications
- No proper sequencing - MariaDB failures if database not ready
- Site creation failed due to wrong config order

### Phase 3: Flexible Deployment System (Week 3)
**Approach:** Auto-detecting base directory, proper sequencing, state management  
**Features Added:**
- ✅ Config class with `initialize()` method to auto-detect or prompt for base_dir
- ✅ StateManager for resumable deployments (`.deploy_state.json`)
- ✅ Proper sequencing: config → site creation → app installation
- ✅ Interactive GHCR credential gathering during setup
- ✅ Health checks with timeouts

### Phase 4: Backup Automation Journey (Week 4)
**Initial Attempts:**
1. **Swarm Service with `replicas: 0`** + manual cron labels → FAILED
   - Problem: `swarm.cronjob.*` labels not recognized by any scheduler
   
2. **Ofelia with `job-service-run`** (config.ini) → FAILED
   - Problem: Unauthorized error pulling GHCR private image
   - Error: `API error (500): error from registry: unauthorized`
   
3. **Ofelia with `job-exec`** targeting backend container → FAILED
   - Problem: Swarm container names include random task IDs (e.g., `brandclub-main_backend.1.abc123xyz`)
   - Ofelia couldn't reliably target the container
   
4. **Ofelia with Docker Labels + `job-run`** → ✅ SUCCESS
   - Solution: Keep backup service with `replicas: 0`, add proper Ofelia labels
   - Ofelia starts the stopped container on schedule
   - No image pulling needed (container already exists)

---

## Problems Encountered & Solutions

### 1. MariaDB "Access denied for user" Errors

#### Problem
```
pymysql.err.OperationalError: (1045, "Access denied for user 'db_name'@'%' (using password: YES)")
```

Frequent errors even after creating database and user. Affected site creation and bench operations.

#### Root Causes Identified
1. **Missing User:** Database exists but user was never created
2. **Wrong Host Wildcard:** User created with `'user'@'localhost'` instead of `'user'@'%'`
3. **Insufficient Privileges:** User exists but lacks GRANT OPTION or ALL PRIVILEGES
4. **Collation Mismatch:** Database created without `utf8mb4_unicode_ci` collation
5. **Password Mismatch:** `site_config.json` password doesn't match actual DB password

#### Solution Implemented
Created `scripts/fix-mariadb.py` that:
- Auto-detects Frappe sites from backend containers
- Reads `db_name` and `db_password` from each site's `site_config.json`
- Applies Frappe Docker official troubleshooting grants:
  ```sql
  CREATE DATABASE IF NOT EXISTS db_name CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
  CREATE USER IF NOT EXISTS 'db_name'@'%' IDENTIFIED BY 'password';
  UPDATE mysql.global_priv SET Host='%' WHERE User='db_name';
  UPDATE mysql.user SET Host='%' WHERE User='db_name';
  SET PASSWORD FOR 'db_name'@'%' = PASSWORD('password');
  GRANT ALL PRIVILEGES ON `db_name`.* TO 'db_name'@'%' WITH GRANT OPTION;
  FLUSH PRIVILEGES;
  ```

**Usage:**
```bash
python3 ./scripts/fix-mariadb.py
# Interactive menu to select sites and apply fixes
```

---

### 2. Site Creation "MariaDB host not found" Error

#### Problem
```
MariaDB host 'mariadb' not found during site creation
bench new-site erp.brandclub.site fails immediately
```

#### Root Cause
Wrong order of operations in deployment script:
```python
# WRONG ORDER (original)
create_site()  # Fails - no config exists yet
set_config()   # Too late

# CORRECT ORDER (fixed)
set_config()   # Set db_host, redis hosts FIRST
create_site()  # Now works - knows where MariaDB is
install_apps() # Final step
```

#### Solution
Modified `SiteManager.create_all_sites()` method to enforce proper sequencing:
1. Check if config exists, if not prompt to set it first
2. Set all required configs: `db_host`, `redis_cache`, `redis_queue`, `socketio_port`
3. Only then create site
4. Install apps as final step

**Code Location:** [scripts/deploy-vps.py](scripts/deploy-vps.py) lines 650-750

---

### 3. Hardcoded Base Directory Path

#### Problem
Deployment script had:
```python
BASE_DIR = Path("/home/abdul/Projects/Frappe-deploy")
```
This only worked on the development machine, failed on VPS or other systems.

#### Solution
Implemented auto-detection in `Config.initialize()`:
```python
@staticmethod
def initialize():
    # Try to detect from script location
    script_path = Path(__file__).resolve()
    base_dir = script_path.parent.parent  # Go up from scripts/ to root
    
    # Validate it looks like our project
    if (base_dir / "brand_club" / "stacks").exists():
        return Config(str(base_dir))
    
    # Fallback: prompt user
    print("Could not auto-detect base directory")
    base_dir = input("Enter full path to Frappe-deploy directory: ").strip()
    return Config(base_dir)
```

Now works on any machine without modification.

---

### 4. GHCR Registry Authentication

#### Problem
- Manual step: After deployment, admin had to add GHCR credentials via Portainer UI
- Easy to forget, caused pull failures
- No automation for this critical step

#### Solution
Added `EnvironmentSetup.gather_registry_credentials()` as Step 2.5 in deployment:
```python
def gather_registry_credentials(self):
    """Gather GHCR registry credentials for Portainer"""
    print("\n" + "="*60)
    print("Step 2.5: GitHub Container Registry Credentials")
    print("="*60)
    
    username = input("Enter GITHUB_USERNAME for GHCR: ").strip()
    token = getpass.getpass("Enter GITHUB_TOKEN (PAT): ").strip()
    
    self.state_manager.state['registry'] = {
        'username': username,
        'token': token,
        'url': 'ghcr.io'
    }
    self.state_manager.save()
```

Credentials captured upfront, displayed in final summary for manual Portainer entry.

---

### 5. Ofelia Cron Scheduler Configuration Problems

This was the most complex problem with multiple failed attempts.

#### Attempt 1: Swarm-native Cron Labels
**Setup:**
```yaml
backup:
  deploy:
    labels:
      - "swarm.cronjob.enable=true"
      - "swarm.cronjob.schedule=0 2 * * *"
```

**Error:**
```
Unable to start a empty scheduler.
(Service kept restarting)
```

**Root Cause:** No Docker Swarm native cron scheduler exists. These labels are not recognized by Docker or any built-in service.

---

#### Attempt 2: Ofelia with Config File + job-service-run
**Setup:**
```ini
[job-service-run "brandclub-prod-backup"]
schedule = 0 2 * * *
image = ghcr.io/brandclub/brand-club-erp:latest
network = brandclub-prod-network
command = /bin/bash -c '...'
```

**Error:**
```
ERROR [Job "brandclub-prod-backup"] Finished in "491ms", failed: true
error: error pulling image "ghcr.io/brandclub/brand-club-erp:latest": 
API error (500): error from registry: unauthorized
```

**Root Cause:** `job-service-run` creates a new Docker service which tries to pull the image. In Docker Swarm, registry authentication for services must be configured separately - Ofelia doesn't have access to GHCR credentials.

---

#### Attempt 3: Ofelia with job-exec targeting Backend Container
**Setup:**
```ini
[job-exec "brandclub-prod-backup"]
schedule = 0 2 * * *
container = brandclub-prod_backend.1
command = bench backup ...
```

**Error:**
```
ERROR [Job "brandclub-prod-backup"] Container not found
```

**Root Cause:** Docker Swarm container names include task IDs that change on restart:
- First deployment: `brandclub-main_backend.1.abc123xyz456`
- After restart: `brandclub-main_backend.1.def789uvw012`

The `.1.abc123xyz456` suffix is dynamic, making it impossible to reliably target in config.

---

#### Attempt 4: Ofelia Docker Labels + job-run (FINAL SOLUTION ✅)

**Understanding:** Ofelia supports TWO configuration modes:
1. **Config file mode:** `daemon --config=/etc/ofelia/config.ini`
2. **Docker labels mode:** `daemon --docker`

We switched to Docker labels mode with `job-run` type.

**Key Insight from Documentation:**
> `job-run` can be used in 2 situations:
> 1. To run a command inside of a new container, using a specific image
> 2. **To start a stopped container**, similar to `docker start`

**Setup:**
```yaml
# brandclub-prod.yml
backup:
  image: ghcr.io/brandclub/brand-club-erp:${TAG_NAME:-main}
  deploy:
    mode: replicated
    replicas: 0  # Stopped by default
    labels:
      ofelia.enabled: "true"
      ofelia.job-run.brandclub-backup.schedule: "0 2 * * *"
      ofelia.job-run.brandclub-backup.container: "brandclub-main_backup"
      ofelia.job-run.brandclub-backup.no-overlap: "true"
  volumes:
    - sites:/home/frappe/frappe-bench/sites
    - backups:/backups
  # ... full backup command in entrypoint
```

```yaml
# ofelia.yml
services:
  ofelia:
    image: mcuadros/ofelia:latest
    command: daemon --docker
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
```

**Why This Works:**
1. ✅ Backup service container exists but is stopped (`replicas: 0`)
2. ✅ Image already pulled during stack deployment (no auth needed at runtime)
3. ✅ All volumes and networks already mounted in container definition
4. ✅ Ofelia reads labels from Docker API, finds `ofelia.enabled: "true"`
5. ✅ At scheduled time, Ofelia executes `docker start brandclub-main_backup`
6. ✅ Container runs backup script, exits, stops again
7. ✅ Logs available via `docker service logs brandclub-main_backup`

**Verification:**
```bash
docker service logs ofelia_ofelia --tail 50
# Should show: "New job registered: brandclub-backup"

# Test manually:
docker service update --label-add \
  ofelia.job-run.brandclub-backup.schedule="@every 2m" \
  brandclub-main_backup
```

---

### 6. Documentation Bloat

#### Problem
After multiple iterations, the project had 6+ README files:
- DEPLOY-README.md
- QUICK-REFERENCE.md
- DEPLOYMENT-AUTOMATION.md
- SETUP-COMPLETE.md
- UPDATES-MADE.md
- scripts/DEPLOY-GUIDE.md
- Plus this PROJECT-CONTEXT.md

User feedback: **"i told you 2-3 is more than enough and those 2-3 should contain information accordingly"**

#### Solution
Consolidated to 3 essential documents:
1. **DEPLOY-README.md** (400 lines) - Quick start + architecture overview
2. **QUICK-REFERENCE.md** (350 lines) - Command reference card
3. **scripts/DEPLOY-GUIDE.md** (500 lines) - Detailed deployment guide

Deleted: DEPLOYMENT-AUTOMATION.md, SETUP-COMPLETE.md, UPDATES-MADE.md

**Lesson:** Keep documentation focused and actionable. Too many docs = nobody reads any.

---

### 7. Missing Ofelia Stack File

#### Problem
During final review, user asked: "where is Ofelia stack yml?"

Investigation revealed:
```bash
$ ls brand_club/stacks/
brandclub-dev.yml  brandclub-staging.yml  database-dev.yml  ...
portainer.yml  traefik.yml
# ofelia.yml was MISSING!
```

Yet deployment script referenced it in step 6, and docs mentioned it.

#### Solution
Created `brand_club/stacks/ofelia.yml` with proper configuration:
```yaml
version: '3.8'
services:
  ofelia:
    image: mcuadros/ofelia:latest
    command: daemon --docker
    user: "root"
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
      - ofelia-logs:/var/log/ofelia
    deploy:
      placement:
        constraints:
          - node.role == manager
      restart_policy:
        condition: on-failure
      ...
```

**Lesson:** Always verify file existence matches documentation references.

---

## Critical Decisions Made

### 1. Docker Swarm vs Docker Compose
**Decision:** Use Docker Swarm even for single-node deployment  
**Reasoning:**
- Easier scaling to multi-node cluster later
- Built-in service management (`docker service ls`, `docker stack deploy`)
- Better overlay networking for environment isolation
- Native secrets management
- Restart policies and health checks

**Trade-offs:**
- ❌ `depends_on` doesn't work across stacks (handled with wait scripts)
- ❌ Slightly more complex than Compose (but better for production)

---

### 2. Separate Database Stacks per Environment
**Decision:** Deploy MariaDB in separate stacks (database-dev, database-staging, database-main)  
**Reasoning:**
- Complete environment isolation at database level
- Independent scaling and resource allocation
- Easier to backup/restore individual environments
- Network isolation via separate overlay networks

**Alternative Rejected:** Single MariaDB instance with multiple databases  
**Why:** Security and resource contention issues

---

### 3. Ofelia vs System Cron vs Kubernetes CronJobs
**Decision:** Use Ofelia with Docker labels mode  
**Reasoning:**
- ✅ Docker-native, understands containers
- ✅ No need to install cron in containers
- ✅ Configuration via labels (infrastructure as code)
- ✅ Works in Docker Swarm (unlike docker-compose cron)
- ✅ Lightweight (Go binary)

**Alternatives Considered:**
- **System cron + `docker exec`:** Works but not portable, loses container restart benefits
- **Kubernetes CronJobs:** Overkill for single-node deployment, requires K8s migration
- **Frappe's built-in scheduler:** Can't schedule external operations like backups

---

### 4. State Management for Deployment Script
**Decision:** Implement `.deploy_state.json` tracking  
**Reasoning:**
- Deployments can be interrupted (network issues, server restarts)
- Need to resume from last successful step
- Prevents duplicate operations (e.g., creating same site twice)

**Implementation:**
```python
class StateManager:
    def mark_step_complete(self, step):
        self.state['completed_steps'].append(step)
        self.save()
    
    def is_step_complete(self, step):
        return step in self.state['completed_steps']
```

**Usage in VPSDeployer:**
```python
if not self.state_manager.is_step_complete('traefik_deployed'):
    self.deploy_traefik()
    self.state_manager.mark_step_complete('traefik_deployed')
else:
    print("✓ Traefik already deployed (skipping)")
```

---

### 5. Config Before Site Creation Enforcement
**Decision:** Refuse to create site without proper config set first  
**Reasoning:**
- Prevents cryptic "MariaDB host not found" errors
- Forces proper sequencing
- Better error messages upfront

**Code Pattern:**
```python
def create_all_sites(self):
    # Check config exists first
    result = self.shell.run(f"docker exec {backend} bench --site {site} get-config db_host")
    if result.returncode != 0:
        print("ERROR: Config not set. Run set_config first!")
        return False
```

---

## Final Architecture

### Stack Deployment Order
1. **traefik** - Reverse proxy with Let's Encrypt (shared across all envs)
2. **portainer** - Management UI (shared)
3. **database-{dev,staging,main}** - MariaDB instances (isolated per env)
4. **brandclub-{dev,staging,main}** - Application stacks (isolated per env)
5. **ofelia** - Cron scheduler (shared, watches all environments)

### Network Architecture
```
┌─────────────────────────────────────────────────────┐
│ traefik-public (overlay, external)                  │
│ - Accessible from host ports 80/443                 │
└─────────────────────────────────────────────────────┘
          │
          ├─► brandclub-dev-network (overlay, internal)
          │   └─► brandclub-dev-mariadb (overlay, external)
          │
          ├─► brandclub-staging-network (overlay, internal)
          │   └─► brandclub-staging-mariadb (overlay, external)
          │
          └─► brandclub-prod-network (overlay, internal)
              └─► brandclub-prod-mariadb (overlay, external)
```

### Service Breakdown per Environment

**Each environment (dev/staging/prod) has:**
- `backend` - Gunicorn serving Frappe
- `frontend` - Nginx reverse proxy
- `websocket` - Node.js for real-time features
- `queue-default`, `queue-short`, `queue-long` - Background workers
- `scheduler` - Frappe's task scheduler
- `redis-cache` - Session and page cache
- `redis-queue` - RQ job queue

**Only production has:**
- `backup` - Daily backup service (replicas: 0, started by Ofelia)

**Separate database stacks:**
- `mariadb` service in each database-{env} stack
- Isolated networks prevent cross-environment access

---

## Deployment Workflow

### Fresh Deployment
```bash
# 1. Clone repository
git clone <repo-url>
cd Frappe-deploy

# 2. Run deployment script
python3 ./scripts/deploy-vps.py

# Prompts will ask for:
# - Base directory (auto-detected or manual input)
# - 9 environment variables (domains, email, etc.)
# - GITHUB_USERNAME for GHCR
# - GITHUB_TOKEN for GHCR

# 3. Script handles:
# ✓ Preflight checks (Docker, Swarm init)
# ✓ Stack verification (all 10 yml files present)
# ✓ Traefik deployment
# ✓ Portainer deployment
# ✓ Database stacks deployment (waits for MariaDB ready)
# ✓ Application stacks deployment
# ✓ Ofelia deployment
# ✓ Frappe site creation
# ✓ App installation

# 4. Monitor deployment
bash ./scripts/check-status.sh

# 5. If errors occur, fix and resume
python3 ./scripts/deploy-vps.py
# State tracking resumes from last successful step
```

### Post-Deployment Manual Steps
1. **Add GHCR credentials to Portainer:**
   - Open Portainer UI: `https://portainer.brandclub.site`
   - Go to Registries → Add Registry
   - Select "Custom Registry"
   - Name: `ghcr`
   - Registry URL: `ghcr.io`
   - Username: `<from deployment output>`
   - Password: `<GITHUB_TOKEN from deployment>`

2. **Verify SSL certificates:**
   ```bash
   curl -I https://erp-dev.brandclub.site
   # Should show valid Let's Encrypt certificate
   ```

3. **Test backup manually (optional):**
   ```bash
   # Trigger backup immediately
   docker service scale brandclub-main_backup=1
   
   # Check logs
   docker service logs brandclub-main_backup -f
   
   # Stop after completion
   docker service scale brandclub-main_backup=0
   ```

---

## Key Learnings

### 1. Docker Swarm Service Names are Dynamic
Container names in Swarm include task IDs that change on restart:
- Service: `brandclub-main_backend`
- Container: `brandclub-main_backend.1.abc123xyz456` (dynamic suffix)

**Impact:** Can't use container names directly in configs. Use service labels instead.

---

### 2. Ofelia Has Two Distinct Modes
1. **Config file mode:** `daemon --config=/path/to/config.ini`
   - Good for static, well-defined jobs
   - Requires mounting config file
   - Harder to update (need to edit file and restart)

2. **Docker labels mode:** `daemon --docker`
   - Dynamic, reads from Docker API
   - Infrastructure as code (labels in stack files)
   - Can update by changing labels with `docker service update`

**Best Practice:** Use labels for Docker Swarm deployments.

---

### 3. Frappe Config Order is Critical
Frappe looks for config in this order:
1. `site_config.json` in site directory
2. `common_site_config.json` in sites directory
3. Environment variables

**Must set BEFORE site creation:**
- `db_host`
- `redis_cache`
- `redis_queue`
- `socketio_port`

**Can set AFTER:**
- `mail_server`
- `developer_mode`
- Custom app configs

---

### 4. MariaDB User Grants Need Explicit Host Wildcard
This doesn't work across Docker networks:
```sql
GRANT ALL PRIVILEGES ON db.* TO 'user'@'localhost';
```

Must use:
```sql
GRANT ALL PRIVILEGES ON db.* TO 'user'@'%' WITH GRANT OPTION;
```

The `%` wildcard allows connections from any host (including other containers in overlay networks).

---

### 5. State Files Enable Robust Automation
Without state tracking:
- ❌ Script runs all steps every time
- ❌ Duplicate site creation attempts fail
- ❌ Can't resume after interruption
- ❌ No visibility into what's been done

With `.deploy_state.json`:
- ✅ Skip completed steps automatically
- ✅ Resume from failure point
- ✅ Clear progress visibility
- ✅ Idempotent operations

---

### 6. Documentation Should Match Code Reality
Issues found during this project:
- ❌ Scripts referenced files that didn't exist (ofelia.yml)
- ❌ Too many README files with duplicate info
- ❌ Outdated examples (swarm.cronjob labels)

**Best Practice:**
- Keep 2-3 focused documents
- Verify all file paths mentioned actually exist
- Update docs when code changes
- Include troubleshooting based on real issues encountered

---

### 7. Private Registry Auth in Swarm is Complex
Docker Swarm services need registry credentials configured at:
1. **Swarm level:** `docker login` on all nodes
2. **Portainer level:** Registry configuration in UI
3. **Service level:** For image pulling during `docker service update`

**Ofelia's job-service-run** doesn't inherit these - it creates ephemeral services without auth context.

**Solution:** Use `job-run` with existing containers, or `job-exec` in running containers.

---

## Configuration Reference

### Environment Variables Required
```bash
# Traefik & SSL
LETSENCRYPT_EMAIL=admin@brandclub.com
TRAEFIK_DOMAIN=traefik.brandclub.site

# Development
DEV_DOMAIN=erp-dev.brandclub.site
MAILPIT_DEV_DOMAIN=mailpit-dev.brandclub.site

# Staging
STAGING_DOMAIN=erp-staging.brandclub.site
MAILPIT_STAGING_DOMAIN=mailpit-staging.brandclub.site

# Production
PROD_DOMAIN=erp.brandclub.site
MAILPIT_DOMAIN=mailpit.brandclub.site

# Portainer
PORTAINER_DOMAIN=portainer.brandclub.site

# Optional (has defaults)
CLIENT_MAX_BODY_SIZE=50m
TAG_NAME=main
BACKUP_DIR=/backups
```

### Stack Files Structure
```
brand_club/stacks/
├── traefik.yml              # Reverse proxy + SSL
├── portainer.yml            # Management UI
├── portainer-dind.yml       # Portainer agent (if needed)
├── ofelia.yml               # Cron scheduler
├── database-dev.yml         # Dev MariaDB
├── database-staging.yml     # Staging MariaDB
├── database-main.yml        # Prod MariaDB (named 'main' not 'prod')
├── brandclub-dev.yml        # Dev app stack
├── brandclub-staging.yml    # Staging app stack
└── brandclub-prod.yml       # Prod app stack
```

Note: Production stack is `brandclub-prod.yml` but deploys as `brandclub-main` stack.

### Volumes Created
```bash
# Per environment
brandclub-{env}-sites         # Frappe sites data
brandclub-{env}-logs          # Application logs
brandclub-{env}-redis-cache   # Redis cache persistence
brandclub-{env}-redis-queue   # Redis queue persistence
database-{env}-data           # MariaDB data

# Production only
brandclub-prod-backups        # Backup files (bind mount to /backups)

# Shared
traefik-certificates          # Let's Encrypt certs
portainer-data                # Portainer config
ofelia-logs                   # Ofelia execution logs
```

### Networks Created
```bash
# Shared (external)
traefik-public                # Reverse proxy network
shared-services               # Future shared services

# Per environment (external)
brandclub-{env}-mariadb       # Database isolation network

# Per environment (internal)
brandclub-{env}-network       # Application internal network
```

---

## Troubleshooting Quick Reference

### MariaDB Access Denied
```bash
python3 ./scripts/fix-mariadb.py
# Select site with issues
# Script applies proper grants automatically
```

### Site Creation Fails
```bash
# Check config is set FIRST
docker exec <backend_container> \
  bench --site erp.brandclub.site get-config db_host

# If returns error, set config:
docker exec <backend_container> \
  bench --site erp.brandclub.site set-config db_host mariadb
```

### Backup Not Running
```bash
# Check Ofelia found the job
docker service logs ofelia_ofelia | grep brandclub-backup

# Should see: "New job registered: brandclub-backup"

# Test manually
docker service scale brandclub-main_backup=1
docker service logs brandclub-main_backup -f
docker service scale brandclub-main_backup=0
```

### SSL Certificate Issues
```bash
# Check Traefik logs
docker service logs traefik_traefik

# Verify DNS points to server
dig erp.brandclub.site

# Force certificate regeneration
docker service update --force traefik_traefik
```

---

## Files to Review

### Core Deployment
- [scripts/deploy-vps.py](scripts/deploy-vps.py) - Main deployment automation
- [scripts/check-status.sh](scripts/check-status.sh) - Health monitoring
- [scripts/fix-mariadb.py](scripts/fix-mariadb.py) - Database permission fixer

### Stack Definitions
- [brand_club/stacks/](brand_club/stacks/) - All 10 stack files
- [brand_club/ofelia/config.ini](brand_club/ofelia/config.ini) - Ofelia config (not used in final setup)

### Documentation
- [DEPLOY-README.md](DEPLOY-README.md) - Quick start guide
- [QUICK-REFERENCE.md](QUICK-REFERENCE.md) - Command reference
- [scripts/DEPLOY-GUIDE.md](scripts/DEPLOY-GUIDE.md) - Detailed deployment guide
- [PROJECT-CONTEXT.md](PROJECT-CONTEXT.md) - This file

---

## Future Improvements

### Potential Enhancements
1. **GitHub Actions CI/CD**
   - Auto-build Docker images on git push
   - Auto-deploy to staging on merge to develop
   - Manual approval for prod deployment

2. **Monitoring Stack**
   - Prometheus for metrics
   - Grafana for dashboards
   - AlertManager for notifications

3. **High Availability**
   - Multi-node Swarm cluster
   - Database replication
   - Redis sentinel for failover

4. **Security Hardening**
   - Docker secrets for sensitive data
   - Network policies
   - Regular security scans

### Known Limitations
1. **Single-node deployment** - Not HA, single point of failure
2. **Manual Portainer registry setup** - Could be automated with API calls
3. **No automated rollback** - Manual intervention needed if deployment fails
4. **Logs not centralized** - Each service logs separately

---

## Contact & Support

For questions about this setup:
1. Review this document first
2. Check [DEPLOY-README.md](DEPLOY-README.md) for quick answers
3. Search logs: `docker service logs <service_name>`
4. Check state file: `cat .deploy_state.json`

**Common Log Locations:**
```bash
# Service logs
docker service logs <stack>_<service>

# Container logs (if service not running)
docker ps -a
docker logs <container_id>

# Ofelia execution logs
docker exec <ofelia_container> ls -lh /var/log/ofelia/
```

---

**Document Version:** 1.0  
**Last Updated:** February 27, 2026  
**Authors:** Deployment automation team  
**Status:** Production-ready
