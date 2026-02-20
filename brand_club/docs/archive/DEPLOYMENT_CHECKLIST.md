# Brand Club - Deployment Checklist

Use this checklist to ensure a successful deployment of your Brand Club multi-environment setup.

---

## ☑️ Pre-Deployment Checklist

### Infrastructure Requirements

- [ ] **VPS/Server Ready**
  - [ ] Ubuntu 22.04 LTS or Debian 11+
  - [ ] Minimum 16GB RAM, 6 vCPUs, 200GB SSD (for all environments)
  - [ ] Root or sudo access
  - [ ] SSH access configured

- [ ] **Docker Installed**
  - [ ] Docker Engine 24.0+
  - [ ] Docker Compose 2.20+
  - [ ] Verify: `docker --version`

- [ ] **DNS Configured**
  - [ ] dev.brandclub.com → Server IP
  - [ ] mailpit.dev.brandclub.com → Server IP
  - [ ] staging.brandclub.com → Server IP
  - [ ] brandclub.com → Server IP
  - [ ] DNS propagated (test with `nslookup`)

- [ ] **Firewall Rules**
  - [ ] Port 80 (HTTP) open
  - [ ] Port 443 (HTTPS) open
  - [ ] Port 22 (SSH) secure
  - [ ] Optional: Port 9000 for Portainer

### GitHub Preparation

- [ ] **Repository Created**
  - [ ] Created GitHub repository: `YOUR_ORG/brand_club`
  - [ ] Repository initialized with README
  - [ ] Default branch is `main`

- [ ] **Branches Created**
  ```bash
  git checkout -b develop
  git push origin develop
  
  git checkout -b staging
  git push origin staging
  ```

- [ ] **Branch Protection Rules** (Optional but recommended)
  - [ ] `main` requires pull request reviews
  - [ ] `staging` requires pull request reviews
  - [ ] Status checks must pass

### Docker Registry

- [ ] **Registry Access**
  - [ ] Using GitHub Container Registry (GHCR) ✓ Recommended
  - [ ] OR Docker Hub account created
  - [ ] OR Private registry set up

- [ ] **GitHub Personal Access Token (PAT)**
  - [ ] Created with `write:packages` scope
  - [ ] Token securely saved

- [ ] **Login Test**
  ```bash
  echo $GITHUB_TOKEN | docker login ghcr.io -u YOUR_USERNAME --password-stdin
  ```

---

## ☑️ Deployment Steps

### Step 1: Clone & Customize

- [ ] **Clone repository**
  ```bash
  git clone https://github.com/YOUR_ORG/brand_club.git
  cd brand_club
  ```

- [ ] **Update apps configuration**
  - [ ] Edit `ci/apps-develop.json`
  - [ ] Edit `ci/apps-staging.json`
  - [ ] Edit `ci/apps-production.json`
  - [ ] Replace `YOUR_ORG` with actual organization name

- [ ] **Review Dockerfile**
  - [ ] Check Frappe version compatibility
  - [ ] Verify Python and Node versions

### Step 2: Run Setup Script

- [ ] **Make script executable**
  ```bash
  chmod +x scripts/setup-brandclub.sh
  ```

- [ ] **Run setup**
  ```bash
  ./scripts/setup-brandclub.sh
  ```

- [ ] **Provide configuration when prompted**
  - [ ] Docker registry URL
  - [ ] Docker organization/username
  - [ ] Domain names
  - [ ] Database passwords (SAVE THESE!)
  - [ ] Frappe admin password (SAVE THIS!)
  - [ ] Backup directory

- [ ] **Wait for setup to complete**

### Step 3: Verify Deployment

- [ ] **Check Docker Swarm**
  ```bash
  docker node ls
  docker swarm ca
  ```

- [ ] **Check networks created**
  ```bash
  docker network ls | grep -E "traefik-public|shared-services"
  ```

- [ ] **Check stacks deployed**
  ```bash
  docker stack ls
  # Should see: traefik, brandclub-dev, brandclub-staging, brandclub-prod
  ```

- [ ] **Check services running**
  ```bash
  docker stack ps brandclub-dev
  docker stack ps brandclub-staging
  docker stack ps brandclub-prod
  ```

- [ ] **Wait for services to be healthy** (2-3 minutes)
  ```bash
  watch -n 5 docker service ls
  ```

### Step 4: Create Frappe Sites

- [ ] **Development Site**
  ```bash
  CONTAINER=$(docker ps -q -f name=brandclub-dev_backend)
  docker exec -it $CONTAINER bench new-site dev.brandclub.com \
    --admin-password 'YOUR_ADMIN_PASSWORD' \
    --db-root-password 'YOUR_DB_PASSWORD'
  docker exec -it $CONTAINER bench --site dev.brandclub.com install-app brand_club
  ```

- [ ] **Staging Site**
  ```bash
  CONTAINER=$(docker ps -q -f name=brandclub-staging_backend)
  docker exec -it $CONTAINER bench new-site staging.brandclub.com \
    --admin-password 'YOUR_ADMIN_PASSWORD' \
    --db-root-password 'YOUR_DB_PASSWORD'
  docker exec -it $CONTAINER bench --site staging.brandclub.com install-app brand_club
  ```

- [ ] **Production Site**
  ```bash
  CONTAINER=$(docker ps -q -f name=brandclub-prod_backend)
  docker exec -it $CONTAINER bench new-site brandclub.com \
    --admin-password 'YOUR_ADMIN_PASSWORD' \
    --db-root-password 'YOUR_DB_PASSWORD'
  docker exec -it $CONTAINER bench --site brandclub.com install-app brand_club
  ```

### Step 5: Verify Site Access

- [ ] **Access Development**
  - [ ] Open https://dev.brandclub.com
  - [ ] Login with admin credentials
  - [ ] Verify site loads correctly

- [ ] **Access Mailpit (Development)**
  - [ ] Open https://mailpit.dev.brandclub.com
  - [ ] Verify Mailpit UI loads

- [ ] **Access Staging**
  - [ ] Open https://staging.brandclub.com
  - [ ] Login with admin credentials
  - [ ] Verify site loads correctly

- [ ] **Access Production**
  - [ ] Open https://brandclub.com
  - [ ] Login with admin credentials
  - [ ] Verify site loads correctly

- [ ] **Check SSL Certificates**
  - [ ] All sites have valid Let's Encrypt certificates
  - [ ] No browser warnings

---

## ☑️ CI/CD Configuration

### Step 1: Configure GitHub Secrets

Go to **Settings → Secrets and variables → Actions → New repository secret**

- [ ] **Docker Registry Secrets**
  - [ ] `DOCKER_REGISTRY_URL` = `ghcr.io`
  - [ ] `DOCKER_REGISTRY_USERNAME` = Your GitHub username
  - [ ] `DOCKER_REGISTRY_TOKEN` = Your GitHub PAT

- [ ] **Docker Organization**
  - [ ] `DOCKER_ORG` = Your organization name

- [ ] **Build Configuration**
  - [ ] `FRAPPE_VERSION` = `version-15`
  - [ ] `PYTHON_VERSION` = `3.11.6`
  - [ ] `NODE_VERSION` = `18.18.2`

### Step 2: Deploy Portainer (Optional but Recommended)

- [ ] **Deploy Portainer stack**
  ```bash
  # Portainer will be at https://portainer.brandclub.com
  ```

- [ ] **Access Portainer**
  - [ ] Create admin account
  - [ ] Connect to Docker Swarm environment

### Step 3: Create Portainer Webhooks

For each stack in Portainer:

- [ ] **Development Webhook**
  - [ ] Navigate to `brandclub-dev` stack
  - [ ] Create webhook
  - [ ] Copy URL
  - [ ] Add to GitHub secrets as `PORTAINER_WEBHOOK_DEV`

- [ ] **Staging Webhook**
  - [ ] Navigate to `brandclub-staging` stack
  - [ ] Create webhook
  - [ ] Copy URL
  - [ ] Add to GitHub secrets as `PORTAINER_WEBHOOK_STAGING`

- [ ] **Production Webhook**
  - [ ] Navigate to `brandclub-prod` stack
  - [ ] Create webhook
  - [ ] Copy URL
  - [ ] Add to GitHub secrets as `PORTAINER_WEBHOOK_PROD`

### Step 4: Test CI/CD Pipeline

- [ ] **Test Development Pipeline**
  ```bash
  git checkout develop
  echo "# Test" >> README.md
  git add .
  git commit -m "Test dev deployment"
  git push origin develop
  ```
  - [ ] Check GitHub Actions tab
  - [ ] Verify build succeeds
  - [ ] Verify webhook triggers
  - [ ] Verify dev site updates

- [ ] **Test Staging Pipeline**
  ```bash
  git checkout staging
  git merge develop
  git push origin staging
  ```
  - [ ] Verify staging deployment

- [ ] **Test Production Pipeline**
  ```bash
  git checkout main
  git merge staging
  git push origin main
  ```
  - [ ] Verify production deployment

---

## ☑️ Post-Deployment Configuration

### Frappe Configuration

- [ ] **System Settings**
  - [ ] Set system timezone
  - [ ] Configure date and number formats
  - [ ] Set system language

- [ ] **Email Settings** (Each environment)
  - [ ] DEV: Configure to use Mailpit (smtp: mailpit, port: 1025)
  - [ ] STAGING: Configure SMTP relay or testing service
  - [ ] PROD: Configure production SMTP (SendGrid, AWS SES, etc.)

- [ ] **Email Account Creation**
  ```frappe
  Email Domain: brandclub.com
  SMTP Server: mailpit (dev) or smtp.sendgrid.net (prod)
  Use TLS: Yes (prod only)
  Port: 1025 (dev) or 587 (prod)
  ```

- [ ] **Customize Website**
  - [ ] Upload logo
  - [ ] Set website title
  - [ ] Configure homepage

### Security Hardening

- [ ] **Change Default Passwords**
  - [ ] Frappe admin password (if using default)
  - [ ] Database passwords (already done in setup)

- [ ] **Enable Two-Factor Authentication**
  - [ ] For admin users
  - [ ] For all users (recommended)

- [ ] **Review User Permissions**
  - [ ] Create role-based access
  - [ ] Limit admin access

- [ ] **Configure Session Security**
  - [ ] Set session timeout
  - [ ] Enable secure cookies

### Backup Verification

- [ ] **Check Backup Service Running**
  ```bash
  docker service ps brandclub-prod_backup
  docker service logs brandclub-prod_backup
  ```

- [ ] **Verify Backup Directory**
  ```bash
  ls -lh /backups/brandclub.com/
  ```

- [ ] **Test Manual Backup**
  ```bash
  CONTAINER=$(docker ps -q -f name=brandclub-prod_backend)
  docker exec -it $CONTAINER bench --site brandclub.com backup --with-files
  ```

- [ ] **Test Restore Procedure** (on staging)
  - [ ] Create backup
  - [ ] Create new site
  - [ ] Restore backup
  - [ ] Verify data integrity

- [ ] **Configure Off-site Backup** (Recommended)
  - [ ] Set up rsync to remote server
  - [ ] OR configure S3/object storage sync
  - [ ] Test off-site backup
  - [ ] Document restore procedure

### Monitoring Setup

- [ ] **Basic Monitoring**
  ```bash
  # Set up cronjob to monitor disk space
  # Set up alerts for service failures
  ```

- [ ] **Application Monitoring**
  - [ ] Configure Frappe error logs
  - [ ] Set up log rotation
  - [ ] Monitor slow queries

- [ ] **Optional: Advanced Monitoring**
  - [ ] Deploy Prometheus + Grafana
  - [ ] Configure alerting (email/Slack)
  - [ ] Set up uptime monitoring (UptimeRobot, Pingdom)

---

## ☑️ Operations & Maintenance

### Daily Checks

- [ ] **Monitor Service Health**
  ```bash
  docker service ls
  docker stack ps brandclub-prod --no-trunc
  ```

- [ ] **Check Disk Space**
  ```bash
  df -h
  du -sh /backups/
  ```

- [ ] **Review Logs**
  ```bash
  docker service logs --since 24h brandclub-prod_backend
  ```

### Weekly Checks

- [ ] **Review Backup Status**
  - [ ] Verify backups are running
  - [ ] Check backup sizes
  - [ ] Spot-check backup integrity

- [ ] **Security Updates**
  ```bash
  sudo apt update
  sudo apt upgrade
  ```

- [ ] **Review Access Logs**
  - [ ] Check for suspicious activity
  - [ ] Review failed login attempts

### Monthly Checks

- [ ] **Test Disaster Recovery**
  - [ ] Simulate site failure
  - [ ] Practice restore procedure
  - [ ] Document time to recover

- [ ] **Performance Review**
  - [ ] Database query performance
  - [ ] Response times
  - [ ] Resource utilization

- [ ] **Capacity Planning**
  - [ ] Database size growth
  - [ ] Storage requirements
  - [ ] Scaling needs

---

## ☑️ Documentation

- [ ] **Create Operations Runbook**
  - [ ] Common troubleshooting steps
  - [ ] Emergency contacts
  - [ ] Escalation procedures

- [ ] **Document Custom Configurations**
  - [ ] Brand Club specific settings
  - [ ] Custom scripts
  - [ ] Integration details

- [ ] **Maintain Change Log**
  - [ ] Record all deployments
  - [ ] Document configuration changes
  - [ ] Track issues and resolutions

---

## ☑️ Team Onboarding

- [ ] **Developer Access**
  - [ ] GitHub repository access
  - [ ] Development environment access
  - [ ] Documentation shared

- [ ] **DevOps Access**
  - [ ] SSH access to servers
  - [ ] Portainer access
  - [ ] Docker registry access

- [ ] **Training Completed**
  - [ ] How to deploy changes
  - [ ] How to check logs
  - [ ] How to scale services
  - [ ] Emergency procedures

---

## 🎉 Deployment Complete!

Your Brand Club multi-environment deployment is now live and operational.

### Next Steps

1. **Monitor** the first few days closely
2. **Test** thoroughly in development before promoting to production
3. **Document** any issues or learnings
4. **Optimize** based on real-world usage patterns

### Quick Reference Commands

```bash
# Check everything
docker stack ls && docker service ls

# View logs
docker service logs -f brandclub-prod_backend

# Scale workers
docker service scale brandclub-prod_queue-default=3

# Manual deployment
docker stack deploy -c stacks/brandclub-prod.yml brandclub-prod

# Backup now
CONTAINER=$(docker ps -q -f name=brandclub-prod_backend)
docker exec -it $CONTAINER bench --site brandclub.com backup --with-files
```

### Support Resources

- **Documentation**: [README.md](README.md)
- **Architecture**: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- **Quick Start**: [docs/QUICKSTART.md](docs/QUICKSTART.md)
- **Frappe Forum**: https://discuss.frappe.io/
- **Docker Docs**: https://docs.docker.com/engine/swarm/

---

**Congratulations! 🚀**

Your production-grade multi-environment deployment is complete and ready for use.
