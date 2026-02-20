# Portainer Multi-Environment Configuration

This guide explains how to set up Portainer to manage multiple Brand Club environments.

## Installation

### Option 1: Quick Deploy (Single-node Swarm)

```bash
docker network create --driver overlay portainer-agent-network

docker stack deploy -c - portainer <<EOF
version: '3.8'

services:
  agent:
    image: portainer/agent:latest
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
      - /var/lib/docker/volumes:/var/lib/docker/volumes
    networks:
      - portainer-agent
    deploy:
      mode: global
      placement:
        constraints: [node.platform.os == linux]

  portainer:
    image: portainer/portainer-ce:latest
    command: -H tcp://tasks.agent:9001 --tlsskipverify
    ports:
      - "9443:9443"
      - "9000:9000"
    volumes:
      - portainer-data:/data
    networks:
      - portainer-agent
      - traefik-public
    deploy:
      mode: replicated
      replicas: 1
      placement:
        constraints: [node.role == manager]
      labels:
        - traefik.enable=true
        - traefik.http.routers.portainer.rule=Host(\`portainer.example.com\`)
        - traefik.http.routers.portainer.entrypoints=https
        - traefik.http.routers.portainer.tls=true
        - traefik.http.routers.portainer.tls.certresolver=le
        - traefik.http.services.portainer.loadbalancer.server.port=9000

networks:
  portainer-agent:
    driver: overlay
    attachable: true
  traefik-public:
    external: true

volumes:
  portainer-data:
EOF
```

### Option 2: Production Setup with Traefik

Already included in `stacks/portainer.yml`

## Initial Setup

1. **Access Portainer**: Navigate to `https://portainer.yourdomain.com`
2. **Create Admin User**: Set username and password
3. **Select Environment**: Choose "Docker Swarm" as environment type

## Creating Stacks

### 1. Development Stack

1. Go to **Stacks** → **Add stack**
2. Name: `brandclub-dev`
3. Build method: **Git Repository**
   - Repository URL: `https://github.com/YOUR_ORG/brand_club`
   - Repository reference: `refs/heads/develop`
   - Compose path: `stacks/brandclub-dev.yml`
4. Environment variables:
   ```
   DOCKER_REGISTRY=ghcr.io
   DOCKER_ORG=your-org
   DEV_DOMAIN=dev.brandclub.com
   MAILPIT_DOMAIN=mailpit.dev.brandclub.com
   DB_ROOT_PASSWORD=changeme
   CLIENT_MAX_BODY_SIZE=50m
   ```
5. **Deploy the stack**

### 2. Staging Stack

Repeat above with:
- Name: `brandclub-staging`
- Reference: `refs/heads/staging`
- Compose path: `stacks/brandclub-staging.yml`

### 3. Production Stack

Repeat above with:
- Name: `brandclub-prod`
- Reference: `refs/heads/main`
- Compose path: `stacks/brandclub-prod.yml`

## Creating Webhooks

Webhooks allow GitHub Actions to trigger stack updates.

### For Each Stack:

1. Navigate to **Stacks** → Select stack → Scroll to **Webhook**
2. Click **Create a webhook**
3. Copy the webhook URL (looks like):
   ```
   https://portainer.yourdomain.com/api/webhooks/01234567-89ab-cdef-0123-456789abcdef
   ```
4. Save this URL in GitHub Secrets:
   - DEV: `PORTAINER_WEBHOOK_DEV`
   - STAGING: `PORTAINER_WEBHOOK_STAGING`
   - PROD: `PORTAINER_WEBHOOK_PROD`

### Test Webhook

```bash
curl -X POST "https://portainer.yourdomain.com/api/webhooks/YOUR_WEBHOOK_ID"
```

You should see the stack redeploy.

## Environment Management Best Practices

### 1. Use Environment Variables

Store sensitive data in Portainer environment variables rather than in Git:
- Database passwords
- API keys
- Secrets

### 2. Stack Naming Convention

```
{app-name}-{environment}
```

Examples:
- `brandclub-dev`
- `brandclub-staging`
- `brandclub-prod`

### 3. Git-based Deployment

**Advantages**:
- Version controlled
- Easy rollback
- Audit trail
- No manual file uploads

**Disadvantages**:
- Repository must be accessible
- Environment variables separate from code

### 4. Access Control

Create separate users/teams for each environment:
- **Developers**: Access to dev + staging
- **DevOps**: Access to all environments
- **Admins**: Full access

## Monitoring Stacks

### Stack Dashboard

Shows:
- Service status
- Container count
- Resource usage

### Service Logs

1. **Stacks** → Select stack → Click service name
2. **Logs** tab
3. Filter by:
   - Timestamp
   - Search term
   - Tail lines

### Service Scaling

1. Select service
2. **Scaling/Placement** tab
3. Adjust replica count
4. **Apply changes**

## Stack Updates

### Manual Update

1. Go to **Stacks** → Select stack
2. Click **Update stack**
3. Choose update method:
   - Pull latest Git changes
   - Manual edit
4. **Update the stack**

### Automated Update (Webhook)

When GitHub Actions triggers webhook:
1. Portainer pulls latest image
2. Recreates services with new image
3. Performs rolling update
4. Services updated with zero downtime

## Troubleshooting

### Webhook Not Working

**Check**:
1. Webhook URL is correct
2. Portainer is accessible from GitHub
3. Stack name matches webhook
4. Check Portainer logs:
   ```bash
   docker service logs portainer_portainer
   ```

### Stack Deploy Failed

**Common Causes**:
1. Network not created: Create manually first
2. Volume permission: Check host path permissions
3. Environment variable missing: Add in Portainer UI
4. Image not found: Check registry access

**View Error**:
- **Stacks** → Select stack → **Events** tab

### Services Not Starting

1. **Stacks** → Select stack → Click service
2. Check **Tasks** tab for error messages
3. View **Logs** for detailed errors
4. Verify:
   - Image exists in registry
   - Networks are created
   - Volumes are available
   - Placement constraints met

## Advanced Features

### Custom Templates

Create reusable stack templates:

1. **App Templates** → **Add template**
2. Define template with variables
3. Deploy from template with environment-specific values

### Edge Environments

Deploy to remote Docker hosts:

1. Install Edge Agent on remote host
2. Connect to Portainer
3. Deploy stacks to edge environment

### Automated Backups

Backup Portainer configuration:

```bash
docker run --rm \
  -v portainer-data:/data \
  -v $(pwd):/backup \
  alpine tar czf /backup/portainer-backup.tar.gz /data
```

Restore:

```bash
docker run --rm \
  -v portainer-data:/data \
  -v $(pwd):/backup \
  alpine tar xzf /backup/portainer-backup.tar.gz -C /
```

## Security Best Practices

1. **Enable SSL**: Use Traefik for HTTPS
2. **Strong Passwords**: Use password manager
3. **Limited API Access**: Rotate webhook URLs
4. **RBAC**: Use teams and user permissions
5. **Audit Logs**: Review regularly
6. **Updates**: Keep Portainer updated

## Useful Portainer API Calls

### Get Stack Info

```bash
curl -X GET \
  -H "X-API-Key: YOUR_API_KEY" \
  https://portainer.domain.com/api/stacks
```

### Trigger Webhook

```bash
curl -X POST \
  https://portainer.domain.com/api/webhooks/WEBHOOK_ID
```

### Get Service Logs

```bash
curl -X GET \
  -H "X-API-Key: YOUR_API_KEY" \
  "https://portainer.domain.com/api/endpoints/1/docker/containers/CONTAINER_ID/logs?stdout=true&stderr=true&tail=100"
```

---

**Reference**: [Portainer Documentation](https://docs.portainer.io/)
