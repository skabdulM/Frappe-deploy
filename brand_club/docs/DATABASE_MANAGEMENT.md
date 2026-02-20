# Database Management Guide

## Overview

The Brand Club deployment uses **separated database stacks** to ensure database stability and prevent unnecessary restarts during application updates.

## Architecture

### Why Separate Database Stacks?

**Problem**: When database services (MariaDB, Redis) are deployed within the same stack as application services, any update to the application stack causes the database containers to restart, leading to:
- Service downtime
- Lost connections
- Data consistency risks
- Deployment complications

**Solution**: Deploy databases in dedicated stacks that:
- Run independently from application code
- Only restart when database configuration changes
- Maintain persistent data through Docker volumes
- Provide stable network endpoints for applications

### Stack Structure

```
brandclub-db-dev       → MariaDB + Redis (dev)
brandclub-db-staging   → MariaDB + Redis (staging)  
brandclub-db-prod      → MariaDB + Redis (prod)

brandclub-dev          → App services (connects to db-dev)
brandclub-staging      → App services (connects to db-staging)
brandclub-prod         → App services (connects to db-prod)
```

## Database Stack Components

Each database stack (`database-{env}.yml`) contains:

### 1. MariaDB Service
- **Image**: `mariadb:10.6`
- **Purpose**: Primary data storage for Frappe
- **Configuration**:
  - Development: 512MB buffer pool
  - Staging: 768MB buffer pool + resource limits
  - Production: 1GB buffer pool + slow query logging
- **Persistence**: `brandclub-{env}-mariadb` volume
- **Networks**: 
  - `brandclub-{env}-mariadb` (overlay, application access)
  - `brandclub-{env}-network` (overlay, admin tools)

### 2. Redis Cache
- **Image**: `redis:6.2-alpine`
- **Purpose**: Application caching layer
- **Configuration**:
  - Development: 256MB max memory
  - Staging: 384MB max memory
  - Production: 512MB max memory
- **Eviction**: `allkeys-lru` (least recently used)
- **Persistence**: `brandclub-{env}-redis-cache` volume

### 3. Redis Queue
- **Image**: `redis:6.2-alpine`
- **Purpose**: Background job queue (RQ)
- **Configuration**:
  - Same memory limits as cache
  - AOF persistence enabled (appendfsync everysec)
- **Persistence**: `brandclub-{env}-redis-queue` volume

## Deployment Order

**Critical**: Database stacks must be deployed BEFORE application stacks.

### Correct Sequence

```bash
# 1. Deploy infrastructure
docker stack deploy -c stacks/traefik.yml traefik
docker stack deploy -c stacks/portainer.yml portainer

# 2. Deploy database stacks
docker stack deploy -c stacks/database-dev.yml brandclub-db-dev
docker stack deploy -c stacks/database-staging.yml brandclub-db-staging
docker stack deploy -c stacks/database-prod.yml brandclub-db-prod

# 3. Wait for databases to be ready (20-30 seconds)
sleep 30

# 4. Deploy application stacks
docker stack deploy -c stacks/brandclub-dev.yml brandclub-dev
docker stack deploy -c stacks/brandclub-staging.yml brandclub-staging
docker stack deploy -c stacks/brandclub-prod.yml brandclub-prod
```

### Using Setup Script

The `setup-brandclub.sh` script handles proper deployment order automatically:

```bash
cd brand_club/scripts
chmod +x setup-brandclub.sh
./setup-brandclub.sh
```

## Network Configuration

### External Networks

Application stacks reference database networks as **external**:

```yaml
networks:
  brandclub-dev-network:
    external: true  # Created by database stack
  brandclub-dev-mariadb:
    external: true  # Created by database stack
  traefik-public:
    external: true
```

This ensures:
- Application stacks can't create/destroy database networks
- Database services remain accessible during app updates
- Clean separation of concerns

### Network Names

| Environment | MariaDB Network | General Network |
|------------|----------------|----------------|
| Development | `brandclub-dev-mariadb` | `brandclub-dev-network` |
| Staging | `brandclub-staging-mariadb` | `brandclub-staging-network` |
| Production | `brandclub-prod-mariadb` | `brandclub-prod-network` |

## Environment Variables

### Database Connection

Application services connect using these environment variables:

```yaml
environment:
  DB_HOST: mariadb                    # Service name in database stack
  DB_PORT: "3306"
  REDIS_CACHE: redis-cache:6379       # Service name in database stack
  REDIS_QUEUE: redis-queue:6379       # Service name in database stack
```

**Important**: Use service names (`mariadb`, `redis-cache`, `redis-queue`), not container names or IPs.

### Database Credentials

Set in environment files (`config/{env}.env`):

```bash
# Development
DB_ROOT_PASSWORD=dev_secure_password_123

# Staging
DB_ROOT_PASSWORD=staging_secure_password_456

# Production
DB_ROOT_PASSWORD=prod_secure_password_789
```

## Common Operations

### View Database Stack Status

```bash
# List all stacks
docker stack ls

# View database stack services
docker stack ps brandclub-db-prod

# View service logs
docker service logs brandclub-db-prod_mariadb
docker service logs brandclub-db-prod_redis-cache
docker service logs brandclub-db-prod_redis-queue
```

### Update Database Configuration

```bash
# 1. Edit database stack file
nano stacks/database-prod.yml

# 2. Redeploy database stack
docker stack deploy -c stacks/database-prod.yml brandclub-db-prod

# 3. Application stack automatically reconnects
# (No need to redeploy application stack)
```

### Update Application Without Database Restart

```bash
# Deploy application stack only
docker stack deploy -c stacks/brandclub-prod.yml brandclub-prod

# Database services remain running ✓
# No connection interruption ✓
# Zero database downtime ✓
```

### Scale Database Services

**MariaDB**: Single instance only (not horizontally scalable)

```yaml
# In database-prod.yml
mariadb:
  deploy:
    replicas: 1  # Do not change
```

**Redis**: Can scale, but typically single instance sufficient

```bash
# If needed (rare)
docker service scale brandclub-db-prod_redis-cache=2
```

### Database Backups

Production database stack uses the backup service in the **application stack** to back up data from the database stack:

```yaml
# In brandclub-prod.yml
backup:
  image: ghcr.io/${DOCKER_ORG}/brand_club:main
  networks:
    - brandclub-prod-mariadb  # Accesses database stack network
  environment:
    DB_HOST: mariadb           # Connects to database stack service
```

This design allows:
- Backup service to update without database restart
- Database stack to remain focused on data services
- Backup schedules to be managed independently

## Troubleshooting

### Database Connection Issues

**Symptom**: Application can't connect to database

```bash
# 1. Check database stack is running
docker stack ps brandclub-db-prod

# 2. Check networks exist
docker network ls | grep brandclub-prod

# 3. Verify database service health
docker service logs brandclub-db-prod_mariadb --tail 100

# 4. Test connection from application container
CONTAINER=$(docker ps -q -f name=brandclub-prod_backend)
docker exec -it $CONTAINER ping mariadb
docker exec -it $CONTAINER nc -zv mariadb 3306
```

**Fix**: Ensure database stack was deployed first and networks are external in app stack.

### Database Stack Won't Deploy

**Symptom**: Network creation fails

```bash
Error: network brandclub-prod-network is ambiguous
```

**Fix**: Remove orphaned networks

```bash
docker network ls | grep brandclub-prod
docker network rm <network-id>
# Then redeploy database stack
```

### Application Stack Can't Find Networks

**Symptom**: Network not found error

```bash
Error: network brandclub-prod-mariadb not found
```

**Fix**: Deploy database stack first

```bash
docker stack deploy -c stacks/database-prod.yml brandclub-db-prod
sleep 10
docker stack deploy -c stacks/brandclub-prod.yml brandclub-prod
```

### Redis Memory Issues

**Symptom**: Redis evicting keys too frequently

```bash
# Check Redis memory stats
CONTAINER=$(docker ps -q -f name=brandclub-prod_redis-cache)
docker exec -it $CONTAINER redis-cli INFO memory
```

**Fix**: Increase maxmemory in database stack

```yaml
# In database-prod.yml
redis-cache:
  command: >
    redis-server
    --maxmemory 1024mb        # Increase from 512mb
    --maxmemory-policy allkeys-lru
```

Redeploy database stack to apply changes.

## Version Management

### Current Versions

- **MariaDB**: 10.6 (matches existing nmserp.yml deployment)
- **Redis**: 6.2-alpine (matches existing nmserp.yml deployment)

### Upgrade Process

**MariaDB Upgrade**:

```bash
# 1. Backup all data
./backup-database.sh

# 2. Update version in database stack
# database-prod.yml: image: mariadb:10.7

# 3. Test in development first
docker stack deploy -c stacks/database-dev.yml brandclub-db-dev

# 4. Verify compatibility
# Test all application features

# 5. Deploy to staging, then production
docker stack deploy -c stacks/database-staging.yml brandclub-db-staging
docker stack deploy -c stacks/database-prod.yml brandclub-db-prod
```

**Redis Upgrade**:

```bash
# 1. Update version in database stack
# database-prod.yml: image: redis:6.3-alpine

# 2. Deploy (Redis handles minor version upgrades)
docker stack deploy -c stacks/database-prod.yml brandclub-db-prod
```

## Best Practices

### Do ✅

- Deploy database stacks before application stacks
- Use service names for database connections (`mariadb`, not IPs)
- Test database configuration changes in dev/staging first
- Monitor database metrics (memory, connections, slow queries)
- Keep database versions aligned across environments
- Use external networks in application stacks
- Backup before any database stack changes

### Don't ❌

- Don't include database services in application stacks
- Don't redeploy database stacks unless necessary
- Don't use container names or IPs for connections
- Don't scale MariaDB beyond 1 replica
- Don't change database versions in production without testing
- Don't remove database volumes (data loss!)
- Don't deploy application stack before database stack

## Security Considerations

### Network Isolation

- Database networks are overlay type (encrypted by default)
- Only application services in same environment can access databases
- MariaDB not exposed to traefik-public network
- Redis not exposed to traefik-public network

### Credential Management

```bash
# Never commit real passwords
# Use strong passwords in production

# Development
DB_ROOT_PASSWORD=dev_strong_password_change_me

# Production  
DB_ROOT_PASSWORD=$(openssl rand -base64 32)
```

### Volume Permissions

```bash
# Database volumes run as mysql/redis users
# Host backup directory needs proper permissions
sudo mkdir -p /opt/brand-club/backups
sudo chmod 755 /opt/brand-club/backups
```

## Monitoring

### Database Health Checks

All services include health checks:

```yaml
mariadb:
  healthcheck:
    test: ["CMD", "healthcheck.sh", "--connect", "--innodb_initialized"]
    interval: 10s
    timeout: 5s
    retries: 3

redis-cache:
  healthcheck:
    test: ["CMD", "redis-cli", "ping"]
    interval: 5s
    timeout: 3s
    retries: 3
```

### Check Service Health

```bash
# View health status
docker service ps brandclub-db-prod_mariadb
docker service ps brandclub-db-prod_redis-cache

# Check logs for health check failures
docker service logs brandclub-db-prod_mariadb | grep health
```

## Reference

### Complete Stack List

| Stack Name | Purpose | Dependencies |
|-----------|---------|--------------|
| `traefik` | Reverse proxy | None |
| `portainer` | Management UI | traefik |
| `brandclub-db-dev` | Dev databases | traefik |
| `brandclub-db-staging` | Staging databases | traefik |
| `brandclub-db-prod` | Prod databases | traefik |
| `brandclub-dev` | Dev app | brandclub-db-dev, traefik |
| `brandclub-staging` | Staging app | brandclub-db-staging, traefik |
| `brandclub-prod` | Prod app | brandclub-db-prod, traefik |

### Network Topology

```
traefik-public (overlay)
    ↓
    ├─ Traefik
    ├─ Portainer
    ├─ App Frontend (dev/staging/prod)
    └─ App Backend (dev/staging/prod)

brandclub-{env}-network (overlay)
    ↓  
    ├─ MariaDB
    ├─ Redis Cache
    ├─ Redis Queue
    ├─ Backend
    ├─ Frontend
    ├─ WebSocket
    ├─ Queue Workers
    └─ Scheduler

brandclub-{env}-mariadb (overlay)
    ↓
    ├─ MariaDB (only)
    └─ App services needing DB access
```

### Volume List

| Volume | Purpose | Backup Priority |
|--------|---------|----------------|
| `brandclub-{env}-mariadb` | Database files | **Critical** |
| `brandclub-{env}-redis-cache` | Cache data | Low |
| `brandclub-{env}-redis-queue` | Queue jobs | High |
| `brandclub-{env}-sites` | Frappe sites | **Critical** |
| `brandclub-{env}-logs` | Application logs | Medium |

---

**Last Updated**: 2024
**Maintainer**: DevOps Team
**Related Docs**: [ARCHITECTURE.md](ARCHITECTURE.md), [QUICKSTART.md](QUICKSTART.md)
