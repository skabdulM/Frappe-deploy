# BRAND CLUB DEPLOYMENT - CONFIGURATION REVIEW
**Date:** February 20, 2026  
**Status:** ⚠️ ONE CRITICAL ISSUE FOUND

---

## ✅ WHAT'S CORRECT

### 1. **Database Stack Architecture** (database-dev.yml, staging, prod)
- ✅ **ONLY MariaDB** - No Redis (correctly separated)
- ✅ MariaDB 10.6 with proper configuration (utf8mb4, buffer pool, max connections)
- ✅ Health check with mysqladmin ping
- ✅ Deployment constraints for manager node
- ✅ Volume naming: `brandclub-{env}-mariadb`
- ✅ Network naming: `brandclub-{env}-mariadb`

### 2. **Application Stack Architecture** (brandclub-dev.yml, staging, prod)
- ✅ **Backend** service with proper Gunicorn configuration
- ✅ **Frontend** service with Nginx and Traefik routing
- ✅ **WebSocket** service (Node.js socketio)
- ✅ **Queue Workers** (default, short, long) with correct configurations
- ✅ **Scheduler** service
- ✅ **Migration service** with `condition: none` (one-time runner)
- ✅ **Redis Cache** service (256MB dev, 384MB staging, 512MB prod)
- ✅ **Redis Queue** service with appendonly persistence
- ✅ **Mailpit** service for email testing
- ✅ All services have DB_HOST: mariadb (not "db")
- ✅ All services reference redis-cache:6379 and redis-queue:6379
- ✅ Volume definitions for sites, logs, redis-cache-data, redis-queue-data
- ✅ Service restarts with exponential backoff (queue, scheduler)
- ✅ Migration service can reach database and Redis

### 3. **Traefik Configuration** (stacks/traefik.yml)
- ✅ **Version:** v3.6 (latest stable, compatible with Docker API)
- ✅ **TLS Challenge:** Using certresolver with TLS challenge (stable)
- ✅ **HTTP->HTTPS redirect:** Proper middleware configuration
- ✅ **Basic Auth:** For dashboard protection via TRAEFIK_AUTH
- ✅ **Domain:** traefik.brandclub.site (shared service)
- ✅ **Constraint Label:** traefik-public for proper routing
- ✅ **Swarm Provider:** Properly configured for Docker Swarm
- ✅ **Certificate Storage:** /certificates/acme.json (persistent volume)

### 4. **CI/CD Apps Configuration** (ci/apps-develop.json)
- ✅ **Insights:** v3.2.31 (correct version)
- ✅ **Drive:** v0.3.0 (correct version)
- ✅ **Brand Club ERP:** develop branch (brandclub/brand-club-erp)

### 5. **Environment Files**
- ✅ **brand_club/.env** - Global/shared variables (Traefik, Docker registry)
- ✅ **brand_club/config/dev.env.example** - App stack variables (DEV_DOMAIN, DB passwords)
- ✅ **brand_club/config/staging.env.example** - Staging-specific variables
- ✅ **brand_club/config/prod.env.example** - Production-specific variables

---

## ⚠️ **CRITICAL ISSUE FOUND**

### **Network Configuration Mismatch**

**Current Problem:**
In `brandclub-dev.yml`, the application stack declares ALL networks as `external: true`:

```yaml
networks:
  brandclub-dev-network:
    external: true          # ❌ WRONG
    name: brandclub-dev-network

  brandclub-dev-mariadb:
    external: true          # ✅ CORRECT
    name: brandclub-dev-mariadb

  traefik-public:
    external: true          # ✅ CORRECT
    name: traefik-public
```

**What Should Happen:**
Following the nmserp.yml pattern:
- `brandclub-dev-mariadb`: Created by database-dev stack (external to app stack)
- `brandclub-dev-network`: Created by application stack itself (NOT external)
- `traefik-public`: Created manually (external to app stack)

**The Fix Required:**
Change `brandclub-{dev|staging|prod}-network` from `external: true` to `external: false`

---

## 📋 DEPLOYMENT STACK SUMMARY

| Component | Status | Details |
|-----------|--------|---------|
| Docker Swarm Init | ✅ Complete | Single-node cluster |
| Networks (traefik-public) | ✅ Created | Manual creation |
| Networks (shared-services) | ✅ Created | For future expansion |
| Database Stack Arch | ✅ Correct | MariaDB only + Redis removed |
| App Stack Arch | ⚠️ Network Issue | Has extra network dependency |
| Traefik Config | ✅ Correct | v3.6, TLS challenge, proper routing |
| Apps Config | ✅ Correct | Insights, Drive, Brand Club ERP |
| Environment Files | ✅ Ready | Needs TRAEFIK_AUTH password hash |

---

## 🚀 NEXT STEPS (After Fix)

1. **Fix network configuration** in all 3 app stacks
2. **Generate Traefik password** and update brand_club/.env:
   ```bash
   docker run --rm httpd:2.4-alpine htpasswd -nB admin admin@123
   # Copy output to TRAEFIK_AUTH in brand_club/.env
   ```
3. **Create dev.env** from dev.env.example with actual values
4. **Deploy in order:**
   ```bash
   # Source global env
   source brand_club/.env
   
   # Step 6: Deploy Traefik (shared service)
   docker stack deploy -c brand_club/stacks/traefik.yml traefik
   
   # Step 7: Deploy Database
   docker stack deploy \
     --env-file brand_club/config/dev.env \
     -c brand_club/stacks/database-dev.yml database-dev
   
   # Step 8: Deploy Application
   docker stack deploy \
     --env-file brand_club/config/dev.env \
     -c brand_club/stacks/brandclub-dev.yml brandclub-dev
   
   # Step 9: Run migration
   docker service update --force brandclub-dev_migration
   
   # Step 10: Create Frappe site and install apps
   ```

---

## 📝 FILES MODIFIED

- ✅ `brand_club/stacks/database-dev.yml` - MariaDB only
- ✅ `brand_club/stacks/database-staging.yml` - MariaDB only
- ✅ `brand_club/stacks/database-prod.yml` - MariaDB only
- ✅ `brand_club/stacks/brandclub-dev.yml` - Added migration + Redis services
- ✅ `brand_club/stacks/brandclub-staging.yml` - Added migration + Redis services
- ✅ `brand_club/stacks/brandclub-prod.yml` - Added migration + Redis services
- ✅ `brand_club/stacks/traefik.yml` - v3.6 compatible + TLS challenge
- ✅ `brand_club/.env` - Created with shared variables
- ✅ `brand_club/config/dev.env.example` - Cleaned (no Traefik vars)
- ✅ `brand_club/config/staging.env.example` - Cleaned
- ✅ `brand_club/config/prod.env.example` - Cleaned

