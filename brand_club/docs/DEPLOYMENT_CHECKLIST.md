# Deployment Checklist

A comprehensive pre-deployment and deployment checklist for Brand Club multi-environment setup.

---

## Pre-Deployment Checklist

### Infrastructure Preparation

- [ ] **VPS/Server provisioned** with minimum specs:
  - Development: 2 vCPU, 4GB RAM, 40GB SSD
  - Staging: 2 vCPU, 4GB RAM, 50GB SSD
  - Production: 4 vCPU, 8GB RAM, 100GB SSD
  - Combined: 6 vCPU, 16GB RAM, 200GB SSD

- [ ] **Operating System:**
  - Ubuntu 22.04 LTS or Debian 11+ installed
  - System updated: `sudo apt update && sudo apt upgrade -y`

- [ ] **Docker installed:**
  ```bash
  # Verify versions
  docker --version  # Should be 24.0+
  docker compose version  # Should be 2.20+
  ```

- [ ] **Docker Swarm initialized:**
  ```bash
  docker swarm init
  docker node ls  # Verify swarm is active
  ```

### DNS Configuration

- [ ] **Development domain:** `dev.brandclub.com` → VPS IP
- [ ] **Staging domain:** `staging.brandclub.com` → VPS IP
- [ ] **Production domain:** `brandclub.com` or `www.brandclub.com` → VPS IP
- [ ] **Mailpit domain (dev only):** `mail.dev.brandclub.com` → VPS IP
- [ ] **Traefik dashboard domain:** `traefik.yourdomain.com` → VPS IP
- [ ] **Portainer domain (optional):** `portainer.yourdomain.com` → VPS IP

**Verify DNS propagation:**
```bash
nslookup dev.brandclub.com
nslookup staging.brandclub.com
nslookup brandclub.com
```

### GitHub Configuration

- [ ] **Repository created:** `your-org/brand_club`

- [ ] **Branches created:**
  - `develop` (for development)
  - `staging` (for staging)
  - `main` (for production)

- [ ] **GitHub Secrets configured:**
  - `DOCKER_REGISTRY_TOKEN` (GitHub PAT with `write:packages` scope)
  - `PORTAINER_WEBHOOK_DEV` (from Portainer)
  - `PORTAINER_WEBHOOK_STAGING` (from Portainer)
  - `PORTAINER_WEBHOOK_PROD` (from Portainer)

### Docker Registry

- [ ] **GitHub Container Registry enabled:**
  - Organization settings → Packages → Enable improved container support

- [ ] **Test login from VPS:**
  ```bash
  echo $GITHUB_TOKEN | docker login ghcr.io -u YOUR_USERNAME --password-stdin
  ```

- [ ] **Verify image visibility:**
  - Set package to public or configure pull secrets

### SSL Certificate

- [ ] **Email for Let's Encrypt configured:**
  - Valid email address for certificate expiry notifications
  - Set in environment variable: `LETSENCRYPT_EMAIL=admin@yourdomain.com`

### Security Credentials

- [ ] **Generate strong passwords:**
  ```bash
  # Database root passwords
  openssl rand -base64 32  # Dev
  openssl rand -base64 32  # Staging
  openssl rand -base64 32  # Production
  
  # Frappe admin password
  openssl rand -base64 24
  
  # Traefik dashboard password
  htpasswd -nb admin $(openssl rand -base64 16)
  ```

- [ ] **Store credentials securely:**
  - Use password manager
  - Document in secure location
  - Never commit to Git

---

## Deployment Checklist

### Phase 1: Infrastructure Setup

- [ ] **1. Clone repository on VPS:**
  ```bash
  cd /home/abdul/Projects
  git clone https://github.com/your-org/brand_club.git
  cd brand_club
  ```

- [ ] **2. Create backup directory:**
  ```bash
  sudo mkdir -p /opt/brand-club/backups
  sudo chmod 755 /opt/brand-club/backups
  ```

- [ ] **3. Create Traefik network:**
  ```bash
  docker network create --driver=overlay --attachable traefik-public
  ```

- [ ] **4. Create shared-services network:**
  ```bash
  docker network create --driver=overlay --attachable shared-services
  ```

- [ ] **5. Deploy Traefik:**
  ```bash
  LETSENCRYPT_EMAIL=admin@yourdomain.com \
  TRAEFIK_AUTH=$(htpasswd -nb admin your_password) \
  docker stack deploy -c stacks/traefik.yml traefik
  ```

  **Verify:**
  ```bash
  docker stack ps traefik
  curl -k https://traefik.yourdomain.com  # Should prompt for auth
  ```

- [ ] **6. Deploy Portainer (optional but recommended):**
  ```bash
  docker stack deploy -c stacks/portainer.yml portainer
  ```

  **Verify:**
  ```bash
  docker stack ps portainer
  # Access: https://portainer.yourdomain.com
  # Create admin user on first login
  ```

### Phase 2: Database Stack Deployment

**Critical:** Deploy database stacks BEFORE application stacks.

- [ ] **7. Create environment configuration files:**
  ```bash
  cd config
  cp dev.env.example dev.env
  cp staging.env.example staging.env
  cp prod.env.example prod.env
  ```

- [ ] **8. Edit environment files with your credentials:**
  ```bash
  # Edit each file
  nano dev.env
  nano staging.env
  nano prod.env
  ```

  **Required variables:**
  - `DOCKER_REGISTRY=ghcr.io`
  - `DOCKER_ORG=your-org`
  - `DEV_DOMAIN=dev.brandclub.com`
  - `STAGING_DOMAIN=staging.brandclub.com`
  - `PROD_DOMAIN=brandclub.com`
  - `DB_ROOT_PASSWORD=<strong-password>`
  - `CLIENT_MAX_BODY_SIZE=100m`

- [ ] **9. Deploy Development database stack:**
  ```bash
  cd /home/abdul/Projects/brand_club
  set -a && source config/dev.env && set +a
  docker stack deploy -c stacks/database-dev.yml brandclub-db-dev
  ```

  **Verify:**
  ```bash
  docker stack ps brandclub-db-dev
  docker service logs brandclub-db-dev_mariadb --tail 50
  docker service logs brandclub-db-dev_redis-cache --tail 20
  docker service logs brandclub-db-dev_redis-queue --tail 20
  ```

- [ ] **10. Deploy Staging database stack:**
  ```bash
  set -a && source config/staging.env && set +a
  docker stack deploy -c stacks/database-staging.yml brandclub-db-staging
  ```

  **Verify:**
  ```bash
  docker stack ps brandclub-db-staging
  docker service logs brandclub-db-staging_mariadb --tail 50
  ```

- [ ] **11. Deploy Production database stack:**
  ```bash
  set -a && source config/prod.env && set +a
  docker stack deploy -c stacks/database-prod.yml brandclub-db-prod
  ```

  **Verify:**
  ```bash
  docker stack ps brandclub-db-prod
  docker service logs brandclub-db-prod_mariadb --tail 50
  ```

- [ ] **12. Wait for databases to be healthy (30-60 seconds):**
  ```bash
  sleep 60
  docker stack ps brandclub-db-dev --no-trunc
  docker stack ps brandclub-db-staging --no-trunc
  docker stack ps brandclub-db-prod --no-trunc
  ```

- [ ] **13. Verify networks created by database stacks:**
  ```bash
  docker network ls | grep brandclub
  ```

  **Expected output:**
  - `brandclub-dev-network`
  - `brandclub-dev-mariadb`
  - `brandclub-staging-network`
  - `brandclub-staging-mariadb`
  - `brandclub-prod-network`
  - `brandclub-prod-mariadb`

### Phase 3: Application Image Building

- [ ] **14. Build initial images locally (one-time):**
  ```bash
  # Development image
  git checkout develop
  docker build -t ghcr.io/your-org/brand_club:develop -f Dockerfile .
  
  # Staging image
  git checkout staging
  docker build -t ghcr.io/your-org/brand_club:staging -f Dockerfile .
  
  # Production image
  git checkout main
  docker build -t ghcr.io/your-org/brand_club:main -f Dockerfile .
  ```

- [ ] **15. Push images to registry:**
  ```bash
  docker push ghcr.io/your-org/brand_club:develop
  docker push ghcr.io/your-org/brand_club:staging
  docker push ghcr.io/your-org/brand_club:main
  ```

### Phase 4: Application Stack Deployment

- [ ] **16. Deploy Development application stack:**
  ```bash
  set -a && source config/dev.env && set +a
  docker stack deploy -c stacks/brandclub-dev.yml brandclub-dev
  ```

  **Verify:**
  ```bash
  docker stack ps brandclub-dev
  docker service ls | grep brandclub-dev
  ```

- [ ] **17. Deploy Staging application stack:**
  ```bash
  set -a && source config/staging.env && set +a
  docker stack deploy -c stacks/brandclub-staging.yml brandclub-staging
  ```

  **Verify:**
  ```bash
  docker stack ps brandclub-staging
  docker service ls | grep brandclub-staging
  ```

- [ ] **18. Deploy Production application stack:**
  ```bash
  set -a && source config/prod.env && set +a
  docker stack deploy -c stacks/brandclub-prod.yml brandclub-prod
  ```

  **Verify:**
  ```bash
  docker stack ps brandclub-prod
  docker service ls | grep brandclub-prod
  ```

- [ ] **19. Wait for all services to be healthy (2-3 minutes):**
  ```bash
  watch -n 5 'docker service ls'
  ```

  Wait until all replicas show `X/X` in `REPLICAS` column.

### Phase 5: Frappe Site Creation

- [ ] **20. Create Development site:**
  ```bash
  CONTAINER=$(docker ps -q -f name=brandclub-dev_backend)
  docker exec -it $CONTAINER bench new-site dev.brandclub.com \
    --admin-password 'your_admin_password' \
    --db-root-password 'your_dev_db_password'
  
  docker exec -it $CONTAINER bench --site dev.brandclub.com install-app brand_club
  docker exec -it $CONTAINER bench --site dev.brandclub.com set-config developer_mode 1
  docker exec -it $CONTAINER bench --site dev.brandclub.com clear-cache
  ```

  **Verify:**
  ```bash
  docker exec -it $CONTAINER bench --site dev.brandclub.com list-apps
  ```

- [ ] **21. Create Staging site:**
  ```bash
  CONTAINER=$(docker ps -q -f name=brandclub-staging_backend)
  docker exec -it $CONTAINER bench new-site staging.brandclub.com \
    --admin-password 'your_admin_password' \
    --db-root-password 'your_staging_db_password'
  
  docker exec -it $CONTAINER bench --site staging.brandclub.com install-app brand_club
  docker exec -it $CONTAINER bench --site staging.brandclub.com clear-cache
  ```

- [ ] **22. Create Production site:**
  ```bash
  CONTAINER=$(docker ps -q -f name=brandclub-prod_backend)
  docker exec -it $CONTAINER bench new-site brandclub.com \
    --admin-password 'your_strong_admin_password' \
    --db-root-password 'your_prod_db_password'
  
  docker exec -it $CONTAINER bench --site brandclub.com install-app brand_club
  docker exec -it $CONTAINER bench --site brandclub.com clear-cache
  docker exec -it $CONTAINER bench --site brandclub.com migrate
  ```

### Phase 6: Portainer Webhook Configuration

- [ ] **23. Create webhooks in Portainer:**
  - Login to Portainer: https://portainer.yourdomain.com
  - Go to Stacks
  - For each stack (`brandclub-dev`, `brandclub-staging`, `brandclub-prod`):
    - Click on stack name
    - Click "Webhooks" tab
    - Create webhook
    - Copy webhook URL

- [ ] **24. Add webhooks to GitHub Secrets:**
  - Go to: `https://github.com/your-org/brand_club/settings/secrets/actions`
  - Add:
    - `PORTAINER_WEBHOOK_DEV` = webhook URL for brandclub-dev
    - `PORTAINER_WEBHOOK_STAGING` = webhook URL for brandclub-staging
    - `PORTAINER_WEBHOOK_PROD` = webhook URL for brandclub-prod

### Phase 7: CI/CD Testing

- [ ] **25. Test Development CI/CD:**
  ```bash
  git checkout develop
  echo "# Test change" >> README.md
  git add .
  git commit -m "Test dev deployment"
  git push origin develop
  ```

  **Monitor:**
  - GitHub Actions: Check workflow run
  - Portainer: Watch stack update
  - Logs: `docker service logs brandclub-dev_backend --follow`

- [ ] **26. Test Staging CI/CD:**
  ```bash
  git checkout staging
  git merge develop
  git push origin staging
  ```

  **Monitor workflow and deployment**

- [ ] **27. Test Production CI/CD:**
  ```bash
  git checkout main
  git merge staging
  git push origin main
  ```

  **Note:** Production workflow requires manual approval in GitHub Actions

---

## Post-Deployment Verification

### Accessibility Checks

- [ ] **Development site accessible:**
  ```bash
  curl -I https://dev.brandclub.com
  # Expected: HTTP 200 OK
  ```

- [ ] **Staging site accessible:**
  ```bash
  curl -I https://staging.brandclub.com
  # Expected: HTTP 200 OK
  ```

- [ ] **Production site accessible:**
  ```bash
  curl -I https://brandclub.com
  # Expected: HTTP 200 OK
  ```

- [ ] **SSL certificates valid:**
  - Visit each domain in browser
  - Check for valid HTTPS (green padlock)
  - Certificate should be from Let's Encrypt

### Health Checks

- [ ] **Check all services are running:**
  ```bash
  docker service ls
  ```

  Verify all services show `X/X` replicas (not `0/X` or stuck)

- [ ] **Check database connections:**
  ```bash
  # Development
  CONTAINER=$(docker ps -q -f name=brandclub-dev_backend)
  docker exec -it $CONTAINER bench --site dev.brandclub.com mariadb
  # Type: SHOW DATABASES; (verify site DB exists)
  # Type: exit
  
  # Production
  CONTAINER=$(docker ps -q -f name=brandclub-prod_backend)
  docker exec -it $CONTAINER bench --site brandclub.com mariadb
  # Type: SHOW DATABASES; (verify site DB exists)
  # Type: exit
  ```

- [ ] **Check Redis connectivity:**
  ```bash
  CONTAINER=$(docker ps -q -f name=brandclub-prod_backend)
  docker exec -it $CONTAINER bench --site brandclub.com execute frappe.utils.redis_wrapper.ping
  # Expected: True
  ```

- [ ] **Check queue workers:**
  ```bash
  docker service logs brandclub-prod_queue-default --tail 50
  docker service logs brandclub-prod_queue-short --tail 50
  docker service logs brandclub-prod_queue-long --tail 50
  ```

  Look for: "Listening for jobs on queue..."

- [ ] **Check scheduler:**
  ```bash
  docker service logs brandclub-prod_scheduler --tail 100
  ```

  Look for: Scheduler tasks running

### Backup Verification

- [ ] **Verify backup service (production only):**
  ```bash
  docker service logs brandclub-prod_backup --tail 50
  ```

- [ ] **Manually trigger test backup:**
  ```bash
  CONTAINER=$(docker ps -q -f name=brandclub-prod_backup)
  docker exec -it $CONTAINER bench --site brandclub.com backup --with-files
  ```

- [ ] **Check backup files created:**
  ```bash
  sudo ls -lh /opt/brand-club/backups/brandclub.com/
  ```

  Should see dated directories with:
  - `*.sql.gz` (database backup)
  - `*-files.tar` (public files)
  - `*-private-files.tar` (private files)

### Monitoring Setup

- [ ] **Set up log monitoring:**
  ```bash
  # Watch production logs
  docker service logs -f brandclub-prod_backend
  ```

- [ ] **Set up disk space monitoring:**
  ```bash
  df -h
  # Verify sufficient space on /opt/brand-club/backups
  ```

- [ ] **Set up uptime monitoring (optional):**
  - UptimeRobot, Pingdom, or similar
  - Monitor: https://brandclub.com
  - Alert email configured

### Security Hardening

- [ ] **Firewall configured:**
  ```bash
  sudo ufw status
  # Should allow: 22 (SSH), 80 (HTTP), 443 (HTTPS)
  # Should deny: 3306 (MariaDB), 6379 (Redis), 8080 (Traefik), 9000 (Portainer)
  ```

- [ ] **Disable password authentication (if using SSH keys):**
  ```bash
  sudo nano /etc/ssh/sshd_config
  # Set: PasswordAuthentication no
  sudo systemctl restart sshd
  ```

- [ ] **Set up automatic security updates:**
  ```bash
  sudo apt install unattended-upgrades
  sudo dpkg-reconfigure -plow unattended-upgrades
  ```

---

## Ongoing Maintenance Checklist

### Daily

- [ ] Check service health: `docker service ls`
- [ ] Monitor disk space: `df -h`
- [ ] Review error logs: `docker service logs <service> --tail 100 | grep -i error`

### Weekly

- [ ] Verify backups are running (production)
- [ ] Check backup file sizes: `du -sh /opt/brand-club/backups/brandclub.com/*`
- [ ] Test restore on development environment
- [ ] Review Traefik access logs
- [ ] Check SSL certificate expiry (should auto-renew)

### Monthly

- [ ] Review and update packages:
  ```bash
  sudo apt update && sudo apt upgrade -y
  ```
- [ ] Check Docker image updates
- [ ] Review resource usage (CPU, RAM, Disk)
- [ ] Audit user accounts and permissions
- [ ] Test disaster recovery procedure

---

## Rollback Procedure

**If deployment fails:**

1. **Identify failing service:**
   ```bash
   docker service ls
   docker service ps <service-name> --no-trunc
   ```

2. **Check service logs:**
   ```bash
   docker service logs <service-name> --tail 200
   ```

3. **Rollback single service:**
   ```bash
   docker service rollback <service-name>
   ```

4. **Rollback entire stack (if needed):**
   ```bash
   # Deploy previous version
   docker stack deploy -c stacks/brandclub-prod.yml brandclub-prod
   # Or update image to previous tag
   docker service update --image ghcr.io/your-org/brand_club:previous-tag brandclub-prod_backend
   ```

5. **Database rollback (rarely needed):**
   ```bash
   # Restore from backup
   CONTAINER=$(docker ps -q -f name=brandclub-prod_backend)
   docker exec -it $CONTAINER bench --site brandclub.com restore /backups/brandclub.com/2024-01-20/*.sql.gz
   ```

---

## Emergency Contacts

**Document your emergency contacts:**

- **Primary Admin:** [Name, Email, Phone]
- **VPS Provider Support:** [Support URL, Account ID]
- **DNS Provider Support:** [Support URL, Account ID]
- **GitHub Support:** https://support.github.com
- **Docker Support:** https://www.docker.com/support/

---

## Useful Commands Reference

```bash
# List all stacks
docker stack ls

# List services in a stack
docker stack ps brandclub-prod

# View service logs
docker service logs brandclub-prod_backend --tail 100 --follow

# Scale a service
docker service scale brandclub-prod_backend=3

# Update service image
docker service update --image ghcr.io/your-org/brand_club:main brandclub-prod_backend

# Execute command in service container
CONTAINER=$(docker ps -q -f name=brandclub-prod_backend)
docker exec -it $CONTAINER bash

# Remove a stack (CAUTION!)
docker stack rm brandclub-prod

# Clean up unused resources
docker system prune -a --volumes
```

---

**Last Updated:** 2024
**Version:** 1.0
**Maintained by:** DevOps Team
