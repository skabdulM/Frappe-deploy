# BRAND CLUB DEPLOYMENT - STEP BY STEP GUIDE

**Status:** Ready for deployment ✅  
**Date:** February 20, 2026  
**Environment:** Development (dev)

---

## PRE-DEPLOYMENT CHECKLIST

### ✅ Verify Setup
```bash
# Check Docker Swarm status
docker node ls

# List existing networks
docker network ls | grep -E "(traefik-public|shared-services)"

# Check project files exist
ls -la brand_club/{.env,config/dev.env}
ls -la brand_club/stacks/{traefik,database-dev,brandclub-dev}.yml
```

### ✅ Verify Environment Variables
```bash
# Check .env
cat brand_club/.env

# Check dev.env
cat brand_club/config/dev.env
```

---

## DEPLOYMENT STEPS

### **Step 1: Load Environment Variables**
```bash
cd /home/abdul/Projects/Frappe-deploy/brand_club
source .env

# Verify loaded
echo "Registry: $DOCKER_REGISTRY"
echo "Org: $DOCKER_ORG"
echo "Traefik Domain: $TRAEFIK_DOMAIN"
```

### **Step 2: Deploy Traefik (Reverse Proxy)**
```bash
docker stack deploy -c stacks/traefik.yml traefik
```

**Verify:**
```bash
docker stack services traefik
docker service logs traefik_traefik --tail 20
```

**Expected Output:**
```
2026-02-20T05:00:00Z INF Traefik version v3.6
2026-02-20T05:00:00Z INF Entrypoint "http" (0.0.0.0:80) with TLS
2026-02-20T05:00:00Z INF Traefik started successfully
```

**⏳ Wait:** 30 seconds for Traefik to initialize.

---

### **Step 3: Deploy Database Stack**
```bash
docker stack deploy \
    --env-file config/dev.env \
    -c stacks/database-dev.yml database-dev
```

**Verify:**
```bash
docker stack services database-dev
docker service logs database-dev_mariadb --tail 20
```

**Expected Output:**
```
2026-02-20T05:00:30Z [Note] [MY-011314] [Server] Plugin 'InnoDB' has
2026-02-20T05:00:30Z [Note] [MY-000000] [Server] Ready for connections
2026-02-20T05:00:30Z [Note] [MY-000000] [Server] Ready for connections (replication, ssl)
```

**⏳ Wait:** 15 seconds for MariaDB to fully initialize.

---

### **Step 4: Verify Database Connectivity**
```bash
# Get container ID
CONTAINER=$(docker ps -q -f "label=com.docker.swarm.service.name=database-dev_mariadb" | head -1)

# Test connection
docker exec $CONTAINER mysqladmin ping -h localhost -pmannan@123

# Expected: mysqld is alive
```

---

### **Step 5: Deploy Application Stack**
```bash
docker stack deploy \
    --env-file config/dev.env \
    -c stacks/brandclub-dev.yml brandclub-dev
```

**Verify:**
```bash
docker stack services brandclub-dev
```

**Expected Services:**
```
ID             NAME                      MODE        REPLICAS  IMAGE
...            brandclub-dev_backend        replicated  1/1       ghcr.io/brandclub/brand_club:develop
...            brandclub-dev_frontend       replicated  1/1       ghcr.io/brandclub/brand_club:develop
...            brandclub-dev_websocket      replicated  1/1       ghcr.io/brandclub/brand_club:develop
...            brandclub-dev_redis-cache    replicated  1/1       redis:6.2-alpine
...            brandclub-dev_redis-queue    replicated  1/1       redis:6.2-alpine
...            brandclub-dev_queue-default  replicated  1/1       ghcr.io/brandclub/brand_club:develop
...            brandclub-dev_queue-short    replicated  1/1       ghcr.io/brandclub/brand_club:develop
...            brandclub-dev_queue-long     replicated  1/1       ghcr.io/brandclub/brand_club:develop
...            brandclub-dev_scheduler      replicated  1/1       ghcr.io/brandclub/brand_club:develop
...            brandclub-dev_migration      replicated  0/1       ghcr.io/brandclub/brand_club:develop (one-time job)
...            brandclub-dev_mailpit        replicated  1/1       axllent/mailpit:latest
```

**⏳ Wait:** 30-45 seconds for all services to start.

---

### **Step 6: Monitor Service Health**

```bash
# Watch all services
watch -n 2 'docker stack services brandclub-dev && echo "---" && docker stack services database-dev'

# Check backend service logs
docker service logs brandclub-dev_backend --tail 20

# Check frontend service logs
docker service logs brandclub-dev_frontend --tail 20

# Check migration service status
docker service logs brandclub-dev_migration --tail 50
```

**Expected Backend Output:**
```
Listening on 0.0.0.0:8000
App initialized successfully
```

**Expected Frontend Output:**
```
Starting Nginx
Upstream configuration updated
```

---

### **Step 7: Access Services**

Once all services are running (REPLICAS = 1/1):

```bash
# Traefik Dashboard
# URL: https://traefik.brandclub.site
# Username: admin
# Password: (from TRAEFIK_AUTH in .env)

# Mailpit (Email Testing)
# URL: https://mailpit.develop-erp.brandclub.site

# Application (after site creation)
# URL: https://develop-erp.brandclub.site
```

---

## TROUBLESHOOTING

### ❌ Services not starting

```bash
# Check service logs
docker service logs <service_name> --tail 50

# Check task status
docker stack ps brandclub-dev

# Restart a service
docker service update --force <service_name>
```

### ❌ Database connection error

```bash
# Check database is running
docker service ls -f "name=mariadb"

# Test connection manually
docker exec $(docker ps -q -f "label=com.docker.swarm.service.name=database-dev_mariadb") \
    mysql -h localhost -uroot -pmannan@123 -e "SHOW DATABASES;"
```

### ❌ Traefik certificates not generating

```bash
# Check Traefik logs
docker service logs traefik_traefik --tail 50 | grep -i cert

# Check acme.json exists
docker volume ls | grep traefik-certificates
```

---

## MANUAL COMMANDS (If Script Fails)

### Remove all stacks and restart
```bash
# Stop all stacks
docker stack rm traefik
docker stack rm database-dev
docker stack rm brandclub-dev

# Wait for cleanup
sleep 10

# Verify networks still exist
docker network ls | grep -E "(traefik-public|brandclub-dev)"

# Redeploy from scratch
cd brand_club
source .env
docker stack deploy -c stacks/traefik.yml traefik
sleep 30
docker stack deploy --env-file config/dev.env -c stacks/database-dev.yml database-dev
sleep 15
docker stack deploy --env-file config/dev.env -c stacks/brandclub-dev.yml brandclub-dev
```

---

## NEXT STEPS (After Deployment)

### 1. Create Frappe Site
```bash
# Get backend container ID
BACKEND=$(docker ps -q -f "label=com.docker.swarm.service.name=brandclub-dev_backend" | head -1)

# Create new site
docker exec $BACKEND bench new-site develop-erp.brandclub.site

# Verify site created
docker exec $BACKEND bench list-apps --site develop-erp.brandclub.site
```

### 2. Install Applications
```bash
docker exec $BACKEND bench --site develop-erp.brandclub.site install-app insights drive brand_club

# Verify installation
docker exec $BACKEND bench list-apps --site develop-erp.brandclub.site
```

### 3. Create Admin User
```bash
docker exec $BACKEND bench --site develop-erp.brandclub.site set-admin-password admin

# Or set the password at site creation
docker exec $BACKEND bench new-site develop-erp.brandclub.site --admin-password admin@123
```

### 4. Access Application
```
🌐 https://develop-erp.brandclub.site
Username: Administrator
Password: (set in step 3)
```

---

## MONITORING

### Check Service Status
```bash
# All services running?
docker stack ps brandclub-dev -f "desired-state=running"

# Failed services?
docker stack ps brandclub-dev -f "desired-state!=running"
```

### View Logs
```bash
# Real-time logs
docker service logs brandclub-dev_backend -f

# Historical logs
docker service logs brandclub-dev_backend --tail 100
```

### Performance
```bash
# Container resource usage
docker stats

# Disk usage
docker system df

# Network usage
docker stats --no-stream
```

---

## ROLLBACK

If deployment fails:

```bash
# Remove all stacks
docker stack rm traefik database-dev brandclub-dev

# Wait for cleanup
sleep 10

# Remove volumes (caution - deletes data)
# docker volume rm traefik-certificates
# docker volume rm brandclub-dev-mariadb
# docker volume rm brandclub-dev-sites
# docker volume rm brandclub-dev-logs
# docker volume rm brandclub-dev-redis-cache
# docker volume rm brandclub-dev-redis-queue

# Start fresh
source .env
docker stack deploy -c stacks/traefik.yml traefik
# ... repeat deployment
```

---

**Questions?** Check logs with `docker service logs <service_name>`
