# Getting Started - Ubuntu Server Setup

Follow these steps to deploy Brand Club on your VirtualBox Ubuntu server.

---

## ✅ Pre-Deployment Checklist

### On Your Ubuntu Server (VirtualBox)

**1. Install Docker & Docker Compose**

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

# Add your user to docker group
sudo usermod -aG docker $USER

# IMPORTANT: Logout and login again for group changes to take effect
```

After logout/login:
```bash
# Verify installation
docker --version  # Should show 24.0+
docker compose version  # Should show 2.20+
```

**2. Initialize Docker Swarm**

```bash
docker swarm init
```

If you see an error about multiple IP addresses, use:
```bash
docker swarm init --advertise-addr <your-server-ip>
```

Verify:
```bash
docker node ls
# Should show 1 node as Leader
```

---

## 📦 Deploy Your Stack

### Step 1: Get Your Code

Since you're testing and already have a GHCR image:

```bash
cd ~
# If you haven't cloned your repo yet:
git clone https://github.com/brandclub/brand-club-erp.git
cd brand-club-erp/brand_club
```

### Step 2: Create Environment Configuration

```bash
# Create config directory
mkdir -p config

# Create dev.env file
cat > config/dev.env << 'EOF'
# Docker Registry (your existing GHCR image)
DOCKER_REGISTRY=ghcr.io
DOCKER_ORG=brandclub

# Domain (use localhost for testing)
DEV_DOMAIN=localhost
MAILPIT_DOMAIN=mail.localhost

# Database Credentials (CHANGE THESE!)
DB_ROOT_PASSWORD=your_secure_password_here

# Frappe Admin Password (CHANGE THIS!)
ADMIN_PASSWORD=admin123

# Performance
CLIENT_MAX_BODY_SIZE=100m

# Backup Directory
BACKUP_DIR=/opt/brand-club/backups

# Let's Encrypt (not needed for localhost testing)
LETSENCRYPT_EMAIL=admin@yourdomain.com
EOF

# Secure the file
chmod 600 config/dev.env

# Edit the file to set your passwords
nano config/dev.env
```

**What to change:**
- `DOCKER_ORG`: Your GitHub organization (probably already correct as "brandclub")
- `DB_ROOT_PASSWORD`: Set a strong password
- `ADMIN_PASSWORD`: Set your Frappe admin password
- `DEV_DOMAIN`: Keep as "localhost" for local testing

### Step 3: Create Docker Networks

```bash
# Traefik network (for routing)
docker network create --driver=overlay --attachable traefik-public

# Shared services network
docker network create --driver=overlay --attachable shared-services
```

Verify:
```bash
docker network ls | grep -E "traefik|shared"
```

### Step 4: Deploy Traefik (Reverse Proxy)

```bash
# Load environment variables
set -a && source config/dev.env && set +a

# Deploy Traefik
docker stack deploy -c stacks/traefik.yml traefik
```

Wait 10-20 seconds, then check:
```bash
docker stack ps traefik
docker service logs traefik_traefik --tail 50
```

### Step 5: Deploy Database Stack

**CRITICAL: Database MUST be deployed BEFORE application!**

```bash
# Load environment (if not already loaded)
set -a && source config/dev.env && set +a

# Deploy database stack
docker stack deploy -c stacks/database-dev.yml brandclub-db-dev
```

**Monitor database startup:**
```bash
docker service logs brandclub-db-dev_mariadb --follow
```

**Wait until you see:** "ready for connections" (press Ctrl+C to exit)

Verify all database services are running:
```bash
docker stack ps brandclub-db-dev
```

You should see:
- `brandclub-db-dev_mariadb`
- `brandclub-db-dev_redis-cache`
- `brandclub-db-dev_redis-queue`

All should show "Running" state.

### Step 6: Deploy Application Stack

```bash
# Load environment
set -a && source config/dev.env && set +a

# Deploy application (will pull your GHCR image)
docker stack deploy -c stacks/brandclub-dev.yml brandclub-dev
```

**Monitor deployment:**
```bash
watch -n 2 'docker service ls'
```

Wait until all services show **1/1** in the REPLICAS column (2-3 minutes).

Press Ctrl+C to exit watch.

**Check backend logs:**
```bash
docker service logs brandclub-dev_backend --tail 100 --follow
```

Look for: "Booting worker with pid" or similar successful startup messages.

---

## 🌐 Create Your Frappe Site

### Step 7: Initialize Site and Install Apps

```bash
# Get backend container ID
CONTAINER=$(docker ps -q -f name=brandclub-dev_backend)

# Verify container exists
docker ps -f name=brandclub-dev_backend

# Create new site
docker exec -it $CONTAINER bench new-site localhost \
  --admin-password 'admin123' \
  --db-root-password 'your_secure_password_here'
```

**Replace** `your_secure_password_here` with the password you set in config/dev.env!

**Now install your apps:**

```bash
# Install Frappe Insights
docker exec -it $CONTAINER bench --site localhost install-app insights

# Install Frappe Drive
docker exec -it $CONTAINER bench --site localhost install-app drive

# Install Brand Club ERP
docker exec -it $CONTAINER bench --site localhost install-app brand_club

# Enable developer mode (for testing)
docker exec -it $CONTAINER bench --site localhost set-config developer_mode 1

# Clear cache
docker exec -it $CONTAINER bench --site localhost clear-cache
```

**Verify apps are installed:**
```bash
docker exec -it $CONTAINER bench --site localhost list-apps
```

You should see:
- frappe
- insights
- drive
- brand_club

---

## 🎉 Access Your Site

### Option 1: Access via Localhost (Simplest)

Open your browser and go to:
```
http://localhost
```

You should see the Frappe login page!

**Login credentials:**
- Username: `Administrator`
- Password: `admin123` (or whatever you set in ADMIN_PASSWORD)

### Option 2: Access from Host Machine (if using VirtualBox)

If your Ubuntu server is running in VirtualBox:

1. **Configure Port Forwarding in VirtualBox:**
   - VirtualBox → Settings → Network → Advanced → Port Forwarding
   - Add rule: Host Port 80 → Guest Port 80
   - Add rule: Host Port 443 → Guest Port 443

2. **Access from host:**
   ```
   http://localhost
   ```

---

## 🔍 Troubleshooting

### Check If Everything Is Running

```bash
# List all services
docker service ls

# Should show:
# - traefik_traefik (1/1)
# - brandclub-db-dev_mariadb (1/1)
# - brandclub-db-dev_redis-cache (1/1)
# - brandclub-db-dev_redis-queue (1/1)
# - brandclub-dev_backend (1/1)
# - brandclub-dev_frontend (1/1)
# - brandclub-dev_websocket (1/1)
# - brandclub-dev_queue-default (1/1)
# - brandclub-dev_queue-short (1/1)
# - brandclub-dev_queue-long (1/1)
# - brandclub-dev_scheduler (1/1)
# - brandclub-dev_mailpit (1/1)
```

### If Backend Won't Start

```bash
# Check backend logs
docker service logs brandclub-dev_backend --tail 200

# Common issues:
# - "Can't connect to MariaDB" → Database not ready yet, wait 60 seconds
# - "Permission denied" → Check volume permissions
# - "Image not found" → Check DOCKER_ORG in config/dev.env
```

### If Site Creation Fails

```bash
# Test database connection
CONTAINER=$(docker ps -q -f name=brandclub-dev_backend)
docker exec -it $CONTAINER ping mariadb
docker exec -it $CONTAINER nc -zv mariadb 3306

# If connection fails, check database logs:
docker service logs brandclub-db-dev_mariadb --tail 100
```

### If Site Doesn't Load in Browser

1. **Check if backend is responding:**
   ```bash
   curl http://localhost
   ```

2. **Check Traefik routing:**
   ```bash
   docker service logs traefik_traefik --tail 100
   ```

3. **Check frontend logs:**
   ```bash
   docker service logs brandclub-dev_frontend --tail 100
   ```

---

## 🚀 Next Steps

### After Testing Works

1. **Test your custom app features**
2. **Test Insights and Drive apps**
3. **Verify database persistence** (restart stacks, data should remain)

### Later: Set Up CI/CD

Once you confirm manual deployment works:

1. Set up GitHub Actions secrets
2. Test automated deployment via CI
3. Deploy staging and production environments

---

## 📝 Quick Commands Reference

### View Logs
```bash
# Backend
docker service logs brandclub-dev_backend --tail 100 --follow

# Database
docker service logs brandclub-db-dev_mariadb --tail 100

# All services
docker service ls
```

### Enter Container
```bash
CONTAINER=$(docker ps -q -f name=brandclub-dev_backend)
docker exec -it $CONTAINER bash

# Inside container, run bench commands:
bench --site localhost migrate
bench --site localhost clear-cache
bench --site localhost list-apps
```

### Restart Services
```bash
# Restart specific service
docker service update --force brandclub-dev_backend

# Redeploy entire stack
docker stack deploy -c stacks/brandclub-dev.yml brandclub-dev
```

### Clean Up (Start Fresh)
```bash
# Remove stacks
docker stack rm brandclub-dev
docker stack rm brandclub-db-dev
docker stack rm traefik

# Wait for cleanup
sleep 30

# Remove volumes (THIS DELETES ALL DATA!)
docker volume rm brandclub-dev-sites brandclub-dev-logs
docker volume rm brandclub-dev-mariadb brandclub-dev-redis-cache brandclub-dev-redis-queue
```

---

## 🆘 Need Help?

**Tell me:**
1. Which step you're on
2. What command you ran
3. What error message you see
4. Output of `docker service ls`

**I'll help you troubleshoot!** 🚀

---

**Start with Step 1 above and let me know when you're ready or if you get stuck!**
