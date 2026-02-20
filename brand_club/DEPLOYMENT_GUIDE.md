# Brand Club Deployment Guide

Quick deployment guide for Brand Club on Ubuntu Server (VirtualBox).

---

## Your Stack

- **Frappe Framework:** version-15
- **Apps:**
  - Frappe Insights v3.2.31
  - Frappe Drive v0.3.0
  - Brand Club ERP (your custom app)

---

## Ubuntu Server Setup

### 1. Install Docker & Docker Compose

```bash
# Update system
sudo apt update && sudo apt upgrade -y

# Install prerequisites
sudo apt install -y apt-transport-https ca-certificates curl software-properties-common

# Add Docker GPG key
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /usr/share/keyrings/docker-archive-keyring.gpg

# Add Docker repository
echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/docker-archive-keyring.gpg] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

# Install Docker
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin

# Add your user to docker group (logout/login required after this)
sudo usermod -aG docker $USER

# Verify installation
docker --version
docker compose version
```

**Logout and login again** for group changes to take effect.

### 2. Initialize Docker Swarm

```bash
docker swarm init
```

**Note:** If you have multiple network interfaces, you may need to specify the advertise address:
```bash
docker swarm init --advertise-addr <your-server-ip>
```

Verify:
```bash
docker node ls
```

---

## Quick Deployment Steps

### Step 1: Clone Repository

```bash
cd ~
git clone https://github.com/brandclub/brand-club-erp.git
cd brand-club-erp/brand_club
```

### Step 2: Set Up Environment Variables

For testing, we'll deploy **development environment only**.

```bash
# Create config directory
mkdir -p config

# Create dev.env
cat > config/dev.env << 'EOF'
# Docker Registry (your existing GHCR image)
DOCKER_REGISTRY=ghcr.io
DOCKER_ORG=brandclub

# Domain (use your server IP for testing)
DEV_DOMAIN=dev.brandclub.local
MAILPIT_DOMAIN=mail.dev.brandclub.local

# Database Credentials
DB_ROOT_PASSWORD=dev_strong_password_123

# Frappe Admin Password
ADMIN_PASSWORD=admin123

# Performance
CLIENT_MAX_BODY_SIZE=100m

# Backup Directory (for production later)
BACKUP_DIR=/opt/brand-club/backups

# Let's Encrypt Email (for SSL, use later)
LETSENCRYPT_EMAIL=admin@yourdomain.com
EOF

# Secure the file
chmod 600 config/dev.env
```

**Edit the file** and update values:
```bash
nano config/dev.env
```

- Change `DOCKER_ORG` to your GitHub organization
- Update `DEV_DOMAIN` to your server's IP or hostname
- Set strong passwords for `DB_ROOT_PASSWORD` and `ADMIN_PASSWORD`

### Step 3: Create Networks

```bash
# Traefik network (for reverse proxy)
docker network create --driver=overlay --attachable traefik-public

# Shared services (for future use)
docker network create --driver=overlay --attachable shared-services
```

### Step 4: Deploy Traefik (Reverse Proxy)

```bash
# Load environment
set -a && source config/dev.env && set +a

# For local testing without SSL, deploy Traefik
docker stack deploy -c stacks/traefik.yml traefik
```

Wait 10-20 seconds, then verify:
```bash
docker stack ps traefik
docker service logs traefik_traefik --tail 50
```

### Step 5: Deploy Database Stack

**Critical:** Database must be deployed BEFORE application.

```bash
# Load environment
set -a && source config/dev.env && set +a

# Deploy database stack
docker stack deploy -c stacks/database-dev.yml brandclub-db-dev
```

Wait 30-60 seconds for databases to initialize:
```bash
# Monitor database startup
docker service logs brandclub-db-dev_mariadb --follow
```

Press `Ctrl+C` when you see "ready for connections".

Verify all services are running:
```bash
docker stack ps brandclub-db-dev
```

### Step 6: Deploy Application Stack

```bash
# Load environment
set -a && source config/dev.env && set +a

# Deploy application stack (uses your existing GHCR image)
docker stack deploy -c stacks/brandclub-dev.yml brandclub-dev
```

Monitor deployment:
```bash
# Watch all services
watch -n 2 'docker service ls'
```

Wait until all services show `1/1` replicas.

Check backend logs:
```bash
docker service logs brandclub-dev_backend --follow
```

### Step 7: Create Frappe Site

```bash
# Get backend container ID
CONTAINER=$(docker ps -q -f name=brandclub-dev_backend)

# Create new site
docker exec -it $CONTAINER bench new-site dev.brandclub.local \
  --admin-password 'admin123' \
  --db-root-password 'dev_strong_password_123'

# Install your apps
docker exec -it $CONTAINER bench --site dev.brandclub.local install-app insights
docker exec -it $CONTAINER bench --site dev.brandclub.local install-app drive
docker exec -it $CONTAINER bench --site dev.brandclub.local install-app brand_club

# Enable developer mode (for dev environment)
docker exec -it $CONTAINER bench --site dev.brandclub.local set-config developer_mode 1

# Clear cache
docker exec -it $CONTAINER bench --site dev.brandclub.local clear-cache
```

---

## Access Your Site

### Option 1: Using IP Address (Quick Test)

If you're using your server's IP address directly:

```bash
# Get your server IP
ip addr show
```

Add host entry on your **local machine** (not the server):

**On Linux/Mac:**
```bash
sudo nano /etc/hosts
```

**On Windows:**
```
C:\Windows\System32\drivers\etc\hosts
```

Add this line (replace with your server IP):
```
192.168.1.100   dev.brandclub.local
```

Then access in browser:
```
http://dev.brandclub.local
```

### Option 2: Using Traefik Dashboard

Access Traefik dashboard to see routing:
```
http://your-server-ip:8080
```

**Note:** For production, you'll use proper domain names and SSL certificates.

---

## Troubleshooting

### Check Service Status

```bash
# List all services
docker service ls

# Check specific stack
docker stack ps brandclub-dev
docker stack ps brandclub-db-dev

# View logs
docker service logs brandclub-dev_backend --tail 100
docker service logs brandclub-db-dev_mariadb --tail 50
```

### Database Connection Issues

```bash
# Test MariaDB connection
CONTAINER=$(docker ps -q -f name=brandclub-dev_backend)
docker exec -it $CONTAINER ping mariadb
docker exec -it $CONTAINER nc -zv mariadb 3306

# Test Redis connection
docker exec -it $CONTAINER nc -zv redis-cache 6379
```

### Site Not Loading

1. **Check if backend is running:**
   ```bash
   docker service ps brandclub-dev_backend
   ```

2. **Check Gunicorn logs:**
   ```bash
   docker service logs brandclub-dev_backend --tail 200
   ```

3. **Check if site exists:**
   ```bash
   CONTAINER=$(docker ps -q -f name=brandclub-dev_backend)
   docker exec -it $CONTAINER bench --site dev.brandclub.local list-apps
   ```

### Container Keeps Restarting

```bash
# Check full logs
docker service ps brandclub-dev_backend --no-trunc

# Check last 500 lines
docker service logs brandclub-dev_backend --tail 500
```

Common issues:
- Database not ready (wait 60 seconds after deploying database stack)
- Wrong DB_ROOT_PASSWORD in environment file
- Image not pulled correctly (check DOCKER_ORG in dev.env)

---

## Useful Commands

### View All Stacks
```bash
docker stack ls
```

### View Services in Stack
```bash
docker stack services brandclub-dev
```

### Scale a Service
```bash
docker service scale brandclub-dev_backend=2
```

### Update Service (Pull New Image)
```bash
docker service update --image ghcr.io/brandclub/brand_club:develop brandclub-dev_backend --force
```

### Enter Backend Container
```bash
CONTAINER=$(docker ps -q -f name=brandclub-dev_backend)
docker exec -it $CONTAINER bash
```

### Run Bench Commands
```bash
CONTAINER=$(docker ps -q -f name=brandclub-dev_backend)

# List sites
docker exec -it $CONTAINER bench --site dev.brandclub.local list-apps

# Run migrate
docker exec -it $CONTAINER bench --site dev.brandclub.local migrate

# Clear cache
docker exec -it $CONTAINER bench --site dev.brandclub.local clear-cache

# Console
docker exec -it $CONTAINER bench --site dev.brandclub.local console
```

### Remove Everything (Clean Slate)

**⚠️ WARNING: This deletes all data!**

```bash
# Remove stacks
docker stack rm brandclub-dev
docker stack rm brandclub-db-dev
docker stack rm traefik

# Wait for cleanup
sleep 30

# Remove volumes (THIS DELETES DATA!)
docker volume rm brandclub-dev-sites
docker volume rm brandclub-dev-logs
docker volume rm brandclub-dev-mariadb
docker volume rm brandclub-dev-redis-cache
docker volume rm brandclub-dev-redis-queue

# Remove networks
docker network rm traefik-public shared-services
```

---

## Next Steps After Testing

### 1. Build Custom Docker Image (Later)

Once you confirm everything works with your existing GHCR image:

```bash
# Build from your Dockerfile
docker build -t ghcr.io/brandclub/brand_club:develop .

# Push to registry
echo $GITHUB_TOKEN | docker login ghcr.io -u your-username --password-stdin
docker push ghcr.io/brandclub/brand_club:develop
```

### 2. Set Up CI/CD

- Configure GitHub Actions (workflows already exist in `.github/workflows/`)
- Add GitHub Secrets:
  - `DOCKER_REGISTRY_TOKEN`
  - `PORTAINER_WEBHOOK_DEV` (if using Portainer)

### 3. Deploy Staging & Production

Follow similar steps but use:
- `stacks/database-staging.yml` and `stacks/brandclub-staging.yml`
- `stacks/database-prod.yml` and `stacks/brandclub-prod.yml`
- Proper domain names with SSL certificates

---

## File Locations

- **Stack Files:** `stacks/`
  - `traefik.yml` - Reverse proxy
  - `database-dev.yml` - MariaDB + Redis
  - `brandclub-dev.yml` - Application services
  
- **Config:** `config/dev.env` - Environment variables

- **Apps Config:** `ci/apps-develop.json` - Apps to install (Insights, Drive, Brand Club)

- **Dockerfile:** Root of repo - For building custom image later

---

## Getting Help

If you get stuck:

1. **Check service logs:**
   ```bash
   docker service logs <service-name> --tail 200
   ```

2. **Verify all services running:**
   ```bash
   docker service ls
   ```

3. **Check database networks created:**
   ```bash
   docker network ls | grep brandclub
   ```

4. **Test database connectivity:**
   ```bash
   CONTAINER=$(docker ps -q -f name=brandclub-dev_backend)
   docker exec -it $CONTAINER ping mariadb
   ```

**Ask me when you get stuck at any step!** I'll help you troubleshoot.

---

## Quick Reference: Deployment Order

```
1. Install Docker & Initialize Swarm
2. Create Networks (traefik-public, shared-services)
3. Deploy Traefik
4. Deploy Database Stack (brandclub-db-dev)
   ↓ Wait 30-60 seconds
5. Deploy Application Stack (brandclub-dev)
   ↓ Wait 2-3 minutes
6. Create Frappe Site & Install Apps
7. Access Site via Browser
```

---

**Ready to start?** Follow the steps above and let me know when you complete each section or if you encounter any issues!
