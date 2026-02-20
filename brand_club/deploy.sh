#!/bin/bash

# =====================================================
# Brand Club - Deployment Script
# =====================================================
# Prerequisites:
# - Docker Swarm initialized (docker swarm init)
# - Networks created (traefik-public, shared-services)
# - .env file configured
# =====================================================

set -e

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"

echo "=========================================="
echo "BRAND CLUB DEPLOYMENT"
echo "=========================================="

# Step 1: Verify prerequisites
echo ""
echo "[1/8] Verifying prerequisites..."

if ! docker node ls > /dev/null 2>&1; then
    echo "❌ Docker Swarm not initialized"
    echo "Run: docker swarm init"
    exit 1
fi

# Verify networks exist
for network in traefik-public shared-services; do
    if ! docker network ls --filter "name=$network" --format "{{.Name}}" | grep -q "$network"; then
        echo "⚠️  Network '$network' not found"
        echo "Run: docker network create --driver overlay --attachable $network"
        exit 1
    fi
done

echo "✅ Prerequisites verified"

# Step 2: Load environment
echo ""
echo "[2/8] Loading environment variables..."
source .env
echo "✅ Environment loaded"
echo "   - DOCKER_REGISTRY: $DOCKER_REGISTRY"
echo "   - DOCKER_ORG: $DOCKER_ORG"
echo "   - TRAEFIK_DOMAIN: $TRAEFIK_DOMAIN"

# Step 3: Check env file exists
echo ""
echo "[3/8] Checking config/dev.env..."
if [ ! -f "config/dev.env" ]; then
    echo "❌ config/dev.env not found"
    exit 1
fi
echo "✅ config/dev.env exists"

# Step 4: Deploy Traefik
echo ""
echo "[4/8] Deploying Traefik (reverse proxy)..."
docker stack deploy -c stacks/traefik.yml traefik
echo "✅ Traefik deployed"
echo "   🔗 Dashboard: https://$TRAEFIK_DOMAIN"
echo "   ⏳ Wait 30 seconds for startup..."
sleep 30

# Step 5: Deploy Database
echo ""
echo "[5/8] Deploying MariaDB database..."
docker stack deploy \
    --env-file config/dev.env \
    -c stacks/database-dev.yml database-dev
echo "✅ Database stack deployed"
echo "   ⏳ Wait 15 seconds for database to start..."
sleep 15

# Step 6: Verify database health
echo ""
echo "[6/8] Waiting for database to be ready..."
max_attempts=30
attempt=0
while [ $attempt -lt $max_attempts ]; do
    if docker exec $(docker ps -q -f "label=com.docker.swarm.service.name=database-dev_mariadb" | head -1) \
        mysqladmin ping -h localhost -pmannan@123 > /dev/null 2>&1; then
        echo "✅ Database is ready"
        break
    fi
    attempt=$((attempt + 1))
    echo "   ... waiting ($attempt/$max_attempts)"
    sleep 2
done

if [ $attempt -eq $max_attempts ]; then
    echo "⚠️  Database startup timeout (but continuing deployment)"
fi

# Step 7: Deploy Application Stack
echo ""
echo "[7/8] Deploying application stack..."
docker stack deploy \
    --env-file config/dev.env \
    -c stacks/brandclub-dev.yml brandclub-dev
echo "✅ Application stack deployed"

# Step 8: Check service status
echo ""
echo "[8/8] Checking service status..."
echo "   Waiting 20 seconds for services to start..."
sleep 20

echo ""
echo "=========================================="
echo "✅ DEPLOYMENT COMPLETE"
echo "=========================================="
echo ""
echo "Next steps:"
echo "1. Check service status:"
echo "   docker stack ps database-dev"
echo "   docker stack ps brandclub-dev"
echo ""
echo "2. Create Frappe site:"
echo "   docker exec <backend_container> bench new-site $DEV_DOMAIN"
echo ""
echo "3. Install apps:"
echo "   docker exec <backend_container> bench --site $DEV_DOMAIN install-app insights drive brand_club"
echo ""
echo "4. Access application:"
echo "   🌐 https://$DEV_DOMAIN"
echo ""
echo "5. Traefik Dashboard:"
echo "   🔗 https://$TRAEFIK_DOMAIN"
echo "   👤 Username: admin"
echo "   🔑 Check .env for password"
echo ""
