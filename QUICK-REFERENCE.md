# 🚀 Quick Reference Card - Deployment Automation

## Files Created

### 📂 Core Deployment Scripts (in `/scripts/`)

| File | Type | Size | Purpose |
|------|------|------|---------|
| `deploy-vps.py` | Python 3 | 900+ lines | **MAIN** - Complete automated deployment |
| `check-status.sh` | Bash | 250+ lines | Real-time health monitoring |
| `DEPLOY-GUIDE.md` | Markdown | 500+ lines | Comprehensive deployment guide |

### 📂 Documentation (in root directory)

| File | Size | Purpose |
|------|------|---------|
| `DEPLOY-README.md` | 400+ lines | Quick start guide for new users |
| `DEPLOYMENT-AUTOMATION.md` | 500+ lines | Technical implementation details |
| `CREATED-FILES.md` | 300+ lines | This file! Complete file inventory |

---

## 🎯 One-Command Deployment

```bash
cd /home/abdul/Projects/Frappe-deploy
python3 ./scripts/deploy-vps.py
```

**That's it!** Script handles everything.

---

## ⏱️ Timeline

| Phase | Time | What Happens |
|-------|------|--------------|
| Preflight | 1-2 min | Docker, Swarm, directories verified |
| Configuration | 2-3 min | You answer 9 prompts for env variables |
| Verification | 1 min | Stack files checked |
| Infrastructure | 30 sec | Traefik + Portainer deployed |
| Databases | 30 sec | MariaDB for dev/staging/prod |
| Applications | 30 sec | Frappe stacks deployed |
| Cron Scheduler | 10 sec | Ofelia deployed for backups |
| Frappe Sites | 3-5 min | Sites created + apps installed |
| Summary | instant | Access points displayed |
| **TOTAL** | **15-20 min** | **Full production setup!** |

---

## 🎛️ What Gets Configured

### Infrastructure
✅ Traefik reverse proxy (with Let's Encrypt SSL)  
✅ Portainer management UI  
✅ Ofelia cron scheduler  

### Per Environment (×3: dev/staging/prod)
✅ MariaDB 10.6 database  
✅ Frappe v15 backend  
✅ Nginx frontend  
✅ Node.js websocket  
✅ Redis cache + queue  
✅ Queue workers + scheduler  
✅ Backup service (prod only)  

### Apps Installed
✅ insights  
✅ drive  
✅ brand_club  

---

## 📊 Status Check

After deployment, always verify:

```bash
bash ./scripts/check-status.sh
```

Shows:
- All stacks running
- Service replicas healthy
- Backup directory created
- Access point links

---

## 🔐 Environment Variables

Script will prompt you for these. **Have them ready:**

```
1. DB Root Password           (default: mannan@123)
2. Dev Domain                 (default: erp-dev.brandclub.site)
3. Staging Domain             (default: erp-staging.brandclub.site)
4. Prod Domain                (default: erp.brandclub.site)
5. Mailpit Domain             (default: mailpit.brandclub.site)
6. Portainer Domain           (default: portainer.brandclub.site)
7. GitHub PAT Token           (REQUIRED - no default)
8. Docker Image Tag           (default: main)
9. Let's Encrypt Email        (default: admin@brandclub.site)
```

**Defaults work fine** - just press Enter unless you need custom values.

---

## ✨ Key Features

### Smart Automation
- ✅ Enforces config BEFORE site creation (prevents errors!)
- ✅ Health checks between steps
- ✅ Proper sequencing (dependencies first)
- ✅ Interactive configuration (not file editing)

### Reliability
- ✅ State tracking - **resumable if interrupted**
- ✅ Complete logging to file
- ✅ Error tracking and reporting
- ✅ Container readiness verification

### Monitoring
- ✅ Status check script included
- ✅ Service health verification
- ✅ Resource usage display
- ✅ Backup verification

---

## 🔍 Monitoring After Deployment

### Check Everything is Running
```bash
bash ./scripts/check-status.sh
```

### Watch Specific Service
```bash
docker service logs brandclub-prod_backend -f
```

### Access Your Sites
```
Dev:      https://erp-dev.brandclub.site
Staging:  https://erp-staging.brandclub.site
Prod:     https://erp.brandclub.site
Portainer: https://portainer.brandclub.site
Mailpit:   https://mailpit.brandclub.site
```

### Check Backups
```bash
ls -lah /backups/erp.brandclub.site/
```

Automated backups run **daily at 2 AM** via Ofelia.

---

## 🆘 If Something Goes Wrong

### Option 1: Resume Deployment
```bash
python3 ./scripts/deploy-vps.py
# Script loads state and continues from where it left off
```

### Option 2: Check Logs
```bash
tail -f ./logs/deploy-*.log
docker service logs <service> -f
```

### Option 3: Manual Fixes
For site creation issues, see `scripts/DEPLOY-GUIDE.md` section "Troubleshooting"

---

## 📚 Smart Tips

### Pre-Deployment
✓ Read `DEPLOY-README.md` (5 min)  
✓ Ensure Docker Swarm initialized  
✓ Have all 9 env variables ready  
✓ Verify stack files exist  

### During Deployment
✓ Don't interrupt unless absolutely necessary  
✓ Monitor logs if you want: `tail -f logs/deploy-*.log`  
✓ Answer prompts with Your configuration  

### Post-Deployment
✓ Add GHCR credentials in Portainer UI  
✓ Run status check: `bash scripts/check-status.sh`  
✓ Visit your domains (wait 1-2 min first)  
✓ Set up GitHub Actions if using CI/CD  

---

## 🎓 Script Architecture

**Main Classes:**
- `Config` - Paths and constants
- `StateManager` - Tracks deployment progress
- `Shell` - Executes commands safely
- `PreflightChecks` - System validation
- `EnvironmentSetup` - Interactive prompts
- `StackDeployer` - Deploys Docker stacks
- `SiteManager` - Creates Frappe sites
- `VPSDeployer` - Main orchestrator

**Entry Point:** `python3 scripts/deploy-vps.py`

---

## 📋 Deployment Phases

```
1️⃣  Preflight Checks
    └─ Docker, Swarm, directories

2️⃣  Environment Setup
    └─ Interactive configuration prompts

3️⃣  Stack Verification
    └─ Check all required files exist

4️⃣  Infrastructure
    ├─ Traefik (SSL reverse proxy)
    └─ Portainer (management UI)

5️⃣  Databases
    ├─ MariaDB-dev
    ├─ MariaDB-staging
    └─ MariaDB-prod

6️⃣  Applications
    ├─ Frappe-dev
    ├─ Frappe-staging
    └─ Frappe-prod

7️⃣  Cron Scheduler
    └─ Ofelia (for backup scheduling)

8️⃣  Frappe Sites
    ├─ Set config (critical!)
    ├─ Create site
    └─ Install apps

9️⃣  Summary
    └─ Show access points & next steps
```

---

## 🚀 Getting Started (5 Steps)

### Step 1: Verify (2 min)
```bash
docker info | grep Swarm  # Should say "active"
ls brand_club/stacks/     # Should show *.yml files
```

### Step 2: Read (5 min)
```bash
cat DEPLOY-README.md
```

### Step 3: Prepare (2 min)
- Have GitHub PAT token
- Prepare domain names
- Note DB password

### Step 4: Deploy (15-20 min)
```bash
python3 scripts/deploy-vps.py
```

### Step 5: Verify (1 min)
```bash
bash scripts/check-status.sh
```

---

## 💡 Pro Tips

### Save Configuration
Configuration is automatically saved to `.deploy_state.json` - can resume anytime.

### Resume Deployment
If interrupted: just run the script again!

### Custom Domains
If your domains are different, just enter them when prompted.

### Multiple Deployments
Each environment (dev/staging/prod) is completely isolated.

### Backing Up
Automated daily at 2 AM. Manual backups via `docker service update --force brandclub-prod_backup`

---

## 📞 Where to Find Help

| Question | Answer |
|----------|--------|
| "How do I start?" | Read `DEPLOY-README.md` |
| "What does the script do?" | See `DEPLOYMENT-AUTOMATION.md` |
| "How do I deploy?" | Run `python3 scripts/deploy-vps.py` |
| "How do I check status?" | Run `bash scripts/check-status.sh` |
| "Deployment failed, what now?" | See `scripts/DEPLOY-GUIDE.md` troubleshooting |
| "How do I backup/restore?" | See `brand_club/BACKUP-RESTORE.md` |

---

## ✅ Success Checklist

After running the script, you should have:

- [ ] Traefik running (reverse proxy with SSL)
- [ ] Portainer accessible
- [ ] 3 MariaDB instances (dev/staging/prod)
- [ ] 3 Frappe stacks running
- [ ] 3 Frappe sites created
- [ ] Ofelia cron scheduler running
- [ ] Backup directory ready
- [ ] All services healthy
- [ ] Deployment logs saved
- [ ] Access points accessible in browser

---

## 🎯 Post-Deployment (Important!)

After initial deployment:

1. **GHCR Credentials** (Required for pulls)
   ```
   Portainer → Settings → Registries → Add
   URL: ghcr.io
   Username: <github-username>
   Password: <github-pat>
   ```

2. **Test Sites**
   ```
   Visit: https://erp-dev.brandclub.site
   (Wait 1-2 min for first access)
   ```

3. **GitHub Actions** (If using CI/CD)
   ```
   Add repo secrets with image registry details
   Create Portainer webhooks for auto-deploy
   ```

4. **Backup Testing** (Recommended)
   ```bash
   docker service update --force brandclub-prod_backup
   docker service logs brandclub-prod_backup -f
   ```

---

## 🔄 Update/Redeploy

To change Docker image version:

```bash
# Change tag in environment
TAG_NAME=v1.0.0

# Redeploy stack
docker stack deploy -c brand_club/stacks/brandclub-prod.yml brandclub-prod

# Monitor
docker stack ps brandclub-prod
```

---

**Version:** 1.0 (February 2026)  
**Status:** ✅ Production Ready  
**Maintainer:** Senior DevOps Team  

🎉 **You're ready to deploy!** 🎉
