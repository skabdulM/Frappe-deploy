# Brand Club - Architecture Documentation

## Overview

This document explains the architectural decisions, network topology, and service composition for the Brand Club multi-environment deployment.

---

## Architecture Principles

### 1. Environment Isolation

**Decision**: Each environment (dev, staging, prod) runs as an independent Docker stack with isolated resources.

**Rationale**:
- Prevents resource contention between environments
- Enables independent scaling per environment
- Reduces blast radius of failures
- Allows environment-specific configurations

**Implementation**:
- Separate application stacks: `brandclub-dev`, `brandclub-staging`, `brandclub-prod`
- Separate database stacks: `brandclub-db-dev`, `brandclub-db-staging`, `brandclub-db-prod`
- Environment-specific volumes
- Isolated overlay networks per environment
- Independent database instances

### 1.1. Database Stack Separation

**Critical Decision**: Database services (MariaDB, Redis) are deployed in dedicated stacks, separate from application stacks.

**Rationale**:
- **Zero Database Downtime**: Application stack updates don't restart databases
- **Service Stability**: Database services remain running during app deployments
- **Clear Separation**: Data layer independent from application layer
- **Operational Safety**: Reduces risk of accidental database restarts

**Implementation**:
- Database stacks create and own networks
- Application stacks reference networks as `external: true`
- Database services: `mariadb`, `redis-cache`, `redis-queue`
- Application services connect via service names (`DB_HOST: mariadb`)

### 2. Image Tagging Strategy

**Decision**: Tag images with branch name (`develop`, `staging`, `main`)

**Rationale**:
- Simple and predictable
- Easy to understand which code is deployed where
- Aligns with GitOps workflow
- Enables easy rollback

**Alternative Considered**:
- Semantic versioning (v1.2.3)
- Git commit SHA
- Date-based tags

**Why Branch Tags Won**:
- Simplicity for developers
- Clear environment-to-branch mapping
- No manual version bumping required
- CI/CD integration is straightforward

### 3. Network Topology

```
┌─────────────────────────────────────────────────────────────┐
│                      Internet (Port 80/443)                 │
└─────────────────┬───────────────────────────────────────────┘
                  │
        ┌─────────▼──────────┐
        │  Traefik (Proxy)   │ ◄── traefik-public network
        │  - SSL Termination │
        │  - Load Balancing  │
        └─────────┬──────────┘
                  │
        ┌─────────┴──────────────────────────────────┐
        │                                             │
┌───────▼────────┐  ┌────────────────┐  ┌───────────▼──────┐
│   DEV Stack    │  │ Staging Stack  │  │   PROD Stack     │
│  (Application) │  │  (Application) │  │  (Application)   │
│ ┌────────────┐ │  │ ┌────────────┐ │  │ ┌──────────────┐ │
│ │  Frontend  │ │  │ │  Frontend  │ │  │ │  Frontend x2 │ │
│ └──────┬─────┘ │  │ └──────┬─────┘ │  │ └──────┬───────┘ │
│        │       │  │        │       │  │        │         │
│ ┌──────▼─────┐ │  │ ┌──────▼─────┐ │  │ ┌──────▼───────┐ │
│ │  Backend   │ │  │ │  Backend   │ │  │ │  Backend x2  │ │
│ └──────┬─────┘ │  │ └──────┬─────┘ │  │ └──────┬───────┘ │
│        │       │  │        │       │  │        │         │
│ ┌──────▼─────┐ │  │ ┌──────▼─────┐ │  │ ┌──────▼───────┐ │
│ │  Workers   │ │  │ │  Workers   │ │  │ │  Workers x2  │ │
│ └──────┬─────┘ │  │ └──────┬─────┘ │  │ └──────┬───────┘ │
│        │       │  │        │       │  │        │         │
│ ┌──────▼─────┐ │  │ ┌──────▼─────┐ │  │ ┌──────▼───────┐ │
│ │ WebSocket  │ │  │ │ WebSocket  │ │  │ │ WebSocket x2 │ │
│ └────────────┘ │  │ └────────────┘ │  │ └──────────────┘ │
│ ┌────────────┐ │  │ ┌────────────┐ │  │ ┌──────────────┐ │
│ │ Scheduler  │ │  │ │ Scheduler  │ │  │ │  Scheduler   │ │
│ └────────────┘ │  │ └────────────┘ │  │ └──────────────┘ │
│ ┌────────────┐ │  │                │  │ ┌──────────────┐ │
│ │  Mailpit   │ │  │                │  │ │  Backup Svc  │ │
│ └────────────┘ │  │                │  │ └──────────────┘ │
└───────┬────────┘  └────────┬───────┘  └────────┬─────────┘
        │                    │                    │
        │ Connects to        │ Connects to        │ Connects to
        │ DB Stack           │ DB Stack           │ DB Stack
        ▼                    ▼                    ▼
┌────────────────┐  ┌────────────────┐  ┌────────────────┐
│ DEV DB Stack   │  │ Staging DB Stk │  │ PROD DB Stack  │
│ (Databases)    │  │ (Databases)    │  │ (Databases)    │
│ ┌────────────┐ │  │ ┌────────────┐ │  │ ┌────────────┐ │
│ │  MariaDB   │ │  │ │  MariaDB   │ │  │ │  MariaDB   │ │
│ └────────────┘ │  │ └────────────┘ │  │ └────────────┘ │
│ ┌────────────┐ │  │ ┌────────────┐ │  │ ┌────────────┐ │
│ │Redis Cache │ │  │ │Redis Cache │ │  │ │Redis Cache │ │
│ └────────────┘ │  │ └────────────┘ │  │ └────────────┘ │
│ ┌────────────┐ │  │ ┌────────────┐ │  │ ┌────────────┐ │
│ │Redis Queue │ │  │ │Redis Queue │ │  │ │Redis Queue │ │
│ └────────────┘ │  │ └────────────┘ │  │ └────────────┘ │
└────────────────┘  └────────────────┘  └────────────────┘
        │                                         │
┌───────▼─────────────────────────────────────────▼──────────┐
│              shared-services network                       │
│              (for future mail relay, monitoring)           │
└────────────────────────────────────────────────────────────┘
```

### 4. Network Design

**Networks Created**:

1. **`traefik-public`** (overlay, attachable)
   - Purpose: Ingress routing
   - Attached to: All frontend services, Traefik
   - Rationale: Centralized entry point for all HTTP/HTTPS traffic
   - Created by: Traefik stack

2. **`brandclub-{env}-network`** (overlay, attachable)
   - Purpose: Internal service communication
   - Attached to: Backend, Frontend, Workers, WebSocket, Scheduler, MariaDB, Redis
   - Rationale: Isolates each environment's internal traffic
   - Created by: Database stack (owned by data layer)

3. **`brandclub-{env}-mariadb`** (overlay)
   - Purpose: Database isolation layer
   - Attached to: Backend, Workers, Scheduler, MariaDB
   - Rationale: Adds security layer - only data services can access DB
   - Created by: Database stack (owned by data layer)

4. **`shared-services`** (overlay, attachable, external)
   - Purpose: Common services across environments
   - Future use: SMTP relay, monitoring agents
   - Rationale: Share infrastructure services without code duplication
   - Created by: External setup (manual or infrastructure stack)

**Network Ownership**:
- **Database stacks** create and own environment networks
- **Application stacks** reference networks as `external: true`
- This prevents application updates from affecting network lifecycle
- Ensures database services maintain stable network endpoints

### 5. Service Composition

#### Development Environment

**Application Stack (`brandclub-dev`)**:
- `backend` (Gunicorn) - 1 replica
- `frontend` (Nginx) - 1 replica
- `websocket` (Node.js) - 1 replica
- `queue-default` - 1 replica
- `queue-short` - 1 replica
- `queue-long` - 1 replica
- `scheduler` - 1 replica
- `mailpit` - 1 replica (dev only, email testing)

**Database Stack (`brandclub-db-dev`)**:
- `mariadb` (MariaDB 10.6) - 1 replica, 512MB buffer pool
- `redis-cache` (Redis 6.2-alpine) - 1 replica, 256MB max memory
- `redis-queue` (Redis 6.2-alpine) - 1 replica, 256MB max memory

**Characteristics**:
- Single replica services (cost optimization)
- Debug logging enabled
- Lower resource limits
- Mailpit for local email testing

#### Staging Environment

**Application Stack (`brandclub-staging`)**:
- `backend` - 1 replica
- `frontend` - 1 replica
- `websocket` - 1 replica
- `queue-default` - 1 replica
- `queue-short` - 1 replica
- `queue-long` - 1 replica
- `scheduler` - 1 replica

**Database Stack (`brandclub-db-staging`)**:
- `mariadb` - 1 replica, 768MB buffer pool, 1.5GB memory limit
- `redis-cache` - 1 replica, 384MB max memory
- `redis-queue` - 1 replica, 384MB max memory

**Characteristics**:
- Production-like configs
- Moderate resource limits
- Security headers enabled
- Stricter health checks
- Rollback on failure

#### Production Environment

**Application Stack (`brandclub-prod`)**:
- `backend` - 2 replicas (high availability)
- `frontend` - 2 replicas (high availability)
- `websocket` - 2 replicas (high availability)
- `queue-default` - 2 replicas
- `queue-short` - 2 replicas
- `queue-long` - 2 replicas
- `scheduler` - 1 replica (singleton by design)
- `backup` - 1 replica (daily backups at 2AM UTC)

**Database Stack (`brandclub-db-prod`)**:
- `mariadb` - 1 replica, 1GB buffer pool, 2GB memory limit, slow query logging
- `redis-cache` - 1 replica, 512MB max memory
- `redis-queue` - 1 replica, 512MB max memory, AOF persistence

**Characteristics**:
- High availability (2+ replicas for stateless services)
- Daily automated backups
- Resource reservations and limits
- Sticky sessions for load balancing
- Slow query logging
- Production-grade monitoring hooks

### 6. Volume Strategy

**Volume Naming Pattern**: `brandclub-{env}-{purpose}`

**Application Stack Volumes**:
- `brandclub-{env}-sites` - Frappe sites data
- `brandclub-{env}-logs` - Application logs
- `backups` - Production backups (bind mount to `/opt/brand-club/backups`)

**Database Stack Volumes**:
- `brandclub-{env}-mariadb` - MariaDB data files
- `brandclub-{env}-redis-cache` - Redis cache persistence
- `brandclub-{env}-redis-queue` - Redis queue persistence (AOF enabled)

**Volume Ownership**:
- Application stacks own application data volumes
- Database stacks own database data volumes
- Clear separation ensures proper lifecycle management

**Rationale**:
- Clear ownership per environment
- Easy to backup/restore per environment
- Migration-friendly (can move volumes independently)
- Database volumes persist independently of application deployments

### 7. Backup Strategy

**Design**: Embedded backup service in production application stack

**How It Works**:
1. Uses same image as backend (has bench CLI)
2. Runs as daemon with custom entrypoint
3. Sleeps until 2 AM UTC daily
4. Executes `bench backup --with-files`
5. Stores in dated directories
6. Auto-cleanup after 7 days

**Database Access**:
- Backup service runs in application stack
- Connects to database stack via external network (`brandclub-prod-mariadb`)
- Uses `DB_HOST: mariadb` to access MariaDB service
- This design allows backup service updates without database restarts

**Alternative Considered**:
- External cron job on host
- Separate backup container image
- Backup service in database stack

**Why Application Stack**:
- Same volume access as backend for site files
- No host dependencies
- Portable (works in any swarm)
- Version-locked with app
- Can be updated independently of database layer

**Backup Location**:
```
/backups/brandclub.com/
├── 2026-02-20/
│   ├── database.sql.gz
│   ├── files.tar
│   └── private-files.tar
├── 2026-02-19/
└── ...
```

### 8. CI/CD Pipeline

**Flow**:
```
Developer → Git Push → GitHub Actions → Build Image → Push to Registry
                                                            ↓
                                              Trigger Portainer Webhook
                                                            ↓
                                              Portainer Pulls New Image
                                                            ↓
                                              Rolling Update (Zero Downtime)
```

**Branch-to-Environment Mapping**:
- `develop` → `brandclub-dev` stack
- `staging` → `brandclub-staging` stack
- `main` → `brandclub-prod` stack

**Build Process**:
1. Checkout code
2. Prepare environment-specific `apps.json`
3. Encode to base64
4. Build Docker image with multi-stage build
5. Tag with branch name
6. Push to registry
7. Trigger Portainer webhook

**Why Portainer Webhooks**:
- Decouples CI from deployment
- No SSH keys or server access needed
- Portainer handles authentication
- Simple HTTP POST trigger
- Built-in rollback on failure

### 9. Security Considerations

**SSL/TLS**:
- Automatic Let's Encrypt certificates via Traefik
- HTTP to HTTPS redirect
- HSTS headers on production

**Database**:
- Not exposed to public
- Isolated network per environment
- Password rotation supported

**Secrets**:
- Environment variables for non-sensitive config
- Docker secrets for passwords (future enhancement)
- .env files chmod 600

**Headers**:
- Security headers via Traefik middlewares
- X-Robots-Tag on staging (prevent indexing)
- Content Security Policy ready

### 10. Scalability

**Horizontal Scaling**:
```bash
# Scale workers
docker service scale brandclub-prod_queue-default=4

# Scale backend
docker service scale brandclub-prod_backend=4
```

**Vertical Scaling**:
- Adjust resource limits in compose files
- Update MariaDB buffer pool size
- Increase Redis maxmemory

**Load Balancing**:
- Traefik automatically load balances
- Sticky sessions for Frappe
- Round-robin for stateless services

### 11. Monitoring & Observability

**Built-in**:
- Docker service health checks
- Traefik access logs
- MariaDB slow query log (prod)

**Future Additions**:
- Prometheus metrics export
- Grafana dashboards
- Log aggregation (ELK/Loki)
- APM (New Relic, Datadog)

### 12. Disaster Recovery

**RTO (Recovery Time Objective)**: < 1 hour
**RPO (Recovery Point Objective)**: 24 hours (daily backups)

**Recovery Steps**:
1. Deploy fresh stack
2. Create new site
3. Restore backup
4. Update DNS if needed

**Backup Locations**:
- Local: `/backups/` (7 day retention)
- Off-site: S3/rsync (manual setup)

---

## Design Decisions Summary

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Orchestrator | Docker Swarm | Simpler than K8s, built-in to Docker |
| Reverse Proxy | Traefik | Auto SSL, Docker integration, modern |
| Image Registry | GHCR | Free, integrated with GitHub |
| CI/CD | GitHub Actions | Native to repo, good free tier |
| Deployment | Portainer Webhooks | Simple, no SSH needed |
| Database | MariaDB 10.6 | Frappe requirement |
| Cache | Redis 7 | Frappe requirement |
| SSL | Let's Encrypt | Free, automated |
| Backup | Embedded Service | Portable, version-locked |
| Networks | Multiple Overlays | Isolation + shared services |

---

## Future Enhancements

1. **Docker Secrets**: Replace env vars with Docker secrets
2. **Health Monitoring**: Add Prometheus + Grafana
3. **Log Aggregation**: ELK or Loki stack
4. **Off-site Backups**: Automated S3 sync
5. **Blue-Green Deployments**: Zero-downtime migrations
6. **Multi-node Swarm**: HA across multiple servers
7. **Shared SMTP Relay**: Centralized mail service
8. **Database Replication**: Master-slave setup for prod

---

**Last Updated**: February 2026
**Maintainer**: DevOps Team
