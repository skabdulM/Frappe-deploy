# Brand Club - Multi-Environment Frappe Deployment

Production-ready Docker Swarm deployment for Brand Club ERP with Frappe Insights and Drive.

---

## Stack Components

- **Frappe Framework:** version-15 (Python 3.11, Node 18)
- **Applications:**
  - Frappe Insights v3.2.31 - Business intelligence and analytics
  - Frappe Drive v0.3.0 - File management system
  - Brand Club ERP - Custom business application
- **Database:** MariaDB 10.6
- **Cache & Queue:** Redis 6.2-alpine
- **Reverse Proxy:** Traefik v3.0
- **Orchestration:** Docker Swarm

---

## Quick Start

**📖 For detailed step-by-step instructions, see [DEPLOYMENT_GUIDE.md](DEPLOYMENT_GUIDE.md)**

### Prerequisites

- Ubuntu Server 22.04 LTS
- Docker Engine 24.0+
- Docker Compose 2.20+
- 4GB RAM minimum (8GB recommended for production)

### Basic Deployment

```bash
# 1. Install Docker and initialize Swarm
docker swarm init

# 2. Clone repository
git clone https://github.com/brandclub/brand-club-erp.git
cd brand-club-erp/brand_club

# 3. Create networks
docker network create --driver=overlay --attachable traefik-public
docker network create --driver=overlay --attachable shared-services

# 4. Configure environment
cp config/dev.env.example config/dev.env
nano config/dev.env  # Edit with your settings

# 5. Deploy (in order)
set -a && source config/dev.env && set +a
docker stack deploy -c stacks/traefik.yml traefik
docker stack deploy -c stacks/database-dev.yml brandclub-db-dev
# Wait 60 seconds for database initialization
docker stack deploy -c stacks/brandclub-dev.yml brandclub-dev

# 6. Create site and install apps
CONTAINER=$(docker ps -q -f name=brandclub-dev_backend)
docker exec -it $CONTAINER bench new-site dev.brandclub.local \
  --admin-password 'admin' \
  --db-root-password 'your_db_password'
docker exec -it $CONTAINER bench --site dev.brandclub.local install-app insights
docker exec -it $CONTAINER bench --site dev.brandclub.local install-app drive
docker exec -it $CONTAINER bench --site dev.brandclub.local install-app brand_club
```

---

## Architecture

### Environment Isolation

| Environment | Branch | Stack Name | Database Stack | Purpose |
|------------|--------|------------|----------------|---------|
| Development | `develop` | `brandclub-dev` | `brandclub-db-dev` | Testing |
| Staging | `staging` | `brandclub-staging` | `brandclub-db-staging` | Pre-production |
| Production | `main` | `brandclub-prod` | `brandclub-db-prod` | Live |

### Key Design Decisions

**1. Separated Database Stacks**
- Database services (MariaDB, Redis) run in dedicated stacks
- Application updates don't restart databases (zero downtime)
- Clear separation between data and application layers

**2. Image Tagging Strategy**
- Images tagged by branch: `brand_club:develop`, `brand_club:staging`, `brand_club:main`
- Simple rollback via image tag switching

**3. Network Topology**
```
Internet → Traefik (SSL/Routing) → Application Services → Database Services
```

---

## Project Structure

```
brand_club/
├── DEPLOYMENT_GUIDE.md        # Step-by-step deployment instructions
├── README.md                   # This file (overview)
├── Dockerfile                  # Multi-stage build for Frappe
├── stacks/                     # Docker Compose stack files
│   ├── traefik.yml            # Reverse proxy with SSL
│   ├── database-dev.yml       # Dev database stack
│   ├── database-staging.yml   # Staging database stack
│   ├── database-prod.yml      # Production database stack
│   ├── brandclub-dev.yml      # Dev application stack
│   ├── brandclub-staging.yml  # Staging application stack
│   └── brandclub-prod.yml     # Production application stack
├── ci/                         # Build configuration
│   ├── apps-develop.json      # Apps for development
│   ├── apps-staging.json      # Apps for staging
│   ├── apps-production.json   # Apps for production
│   └── build.env              # Build-time variables
├── config/                     # Environment configurations
│   ├── dev.env.example
│   ├── staging.env.example
│   └── prod.env.example
├── resources/                  # Nginx templates
│   ├── nginx-template.conf
│   └── nginx-entrypoint.sh
├── scripts/                    # Automation scripts
│   └── setup-brandclub.sh     # Automated setup script
└── .github/workflows/          # CI/CD pipelines
    ├── deploy-dev.yml
    ├── deploy-staging.yml
    └── deploy-prod.yml
```

---

## Common Operations

### View Service Status
```bash
docker service ls
docker stack ps brandclub-dev
```

### View Logs
```bash
docker service logs brandclub-dev_backend --tail 100 --follow
```

### Run Bench Commands
```bash
CONTAINER=$(docker ps -q -f name=brandclub-dev_backend)
docker exec -it $CONTAINER bench --site your-site.com migrate
docker exec -it $CONTAINER bench --site your-site.com clear-cache
```

### Update Application (Pull New Image)
```bash
docker service update --image ghcr.io/brandclub/brand_club:develop brandclub-dev_backend --force
```

### Scale Services
```bash
docker service scale brandclub-prod_backend=3
docker service scale brandclub-prod_queue-default=2
```

---

## Deployment Order (Critical)

**Always follow this sequence:**

```
1. Traefik (reverse proxy)
2. Database Stacks (MariaDB + Redis)
   ↓ Wait 30-60 seconds
3. Application Stacks
   ↓ Wait 2-3 minutes for initialization
4. Create Sites & Install Apps
```

**Why?** Database stacks create overlay networks that application stacks reference as external. Deploying apps first will fail with "network not found" errors.

---

## Troubleshooting

### Service Won't Start

```bash
# Check service status
docker service ps <service-name> --no-trunc

# View recent logs
docker service logs <service-name> --tail 200

# Check if networks exist
docker network ls | grep brandclub
```

### Database Connection Failed

```bash
# Test database connectivity
CONTAINER=$(docker ps -q -f name=brandclub-dev_backend)
docker exec -it $CONTAINER ping mariadb
docker exec -it $CONTAINER nc -zv mariadb 3306
docker exec -it $CONTAINER nc -zv redis-cache 6379
```

### Site Not Loading

1. Verify all services are healthy: `docker service ls`
2. Check backend logs: `docker service logs brandclub-dev_backend --tail 200`
3. Ensure site was created: `docker exec -it $CONTAINER bench --site your-site.com list-apps`
4. Check Traefik routing: Access `http://your-server-ip:8080` (Traefik dashboard)

---

## CI/CD Pipeline

GitHub Actions workflows automatically deploy on push:

- **develop branch** → Development environment
- **staging branch** → Staging environment  
- **main branch** → Production environment (requires manual approval)

### GitHub Secrets Required

```
DOCKER_REGISTRY_TOKEN      # GHCR token with write:packages scope
PORTAINER_WEBHOOK_DEV      # Portainer webhook for dev stack
PORTAINER_WEBHOOK_STAGING  # Portainer webhook for staging stack
PORTAINER_WEBHOOK_PROD     # Portainer webhook for production stack
```

---

## Documentation

- **[DEPLOYMENT_GUIDE.md](DEPLOYMENT_GUIDE.md)** - Complete step-by-step deployment for Ubuntu Server
- **[docs/DATABASE_MANAGEMENT.md](docs/DATABASE_MANAGEMENT.md)** - Database operations and troubleshooting

---

## Support

**Getting Started:** Follow [DEPLOYMENT_GUIDE.md](DEPLOYMENT_GUIDE.md) for Ubuntu server setup

**Issues:** Check service logs first: `docker service logs <service> --tail 200`

**Common Problems:**
1. **Network not found** → Deploy database stack first
2. **Database connection failed** → Wait 60 seconds after database stack deployment
3. **Site not accessible** → Check Traefik logs and DNS configuration

---

**Quick Start:** See [DEPLOYMENT_GUIDE.md](DEPLOYMENT_GUIDE.md)  
**Last Updated:** February 2026
