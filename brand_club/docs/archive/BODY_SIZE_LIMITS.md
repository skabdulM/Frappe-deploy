# Traefik Body Size Configuration

## Overview

Traefik has body size limits configured via middleware. This document explains the configuration.

## Configuration

### Global Middleware (in traefik.yml)

```yaml
# Body Size Limit Middleware (100MB for large file uploads)
- traefik.http.middlewares.body-size-limit.buffering.maxRequestBodyBytes=104857600
- traefik.http.middlewares.body-size-limit.buffering.memRequestBodyBytes=104857600
```

**Values**:
- `maxRequestBodyBytes`: Maximum size of request body (100MB = 104857600 bytes)
- `memRequestBodyBytes`: Maximum size stored in memory before buffering to disk

### Usage in Stack Files

To apply body size limits to a service, add the middleware to the router:

```yaml
labels:
  - traefik.http.routers.myapp.middlewares=body-size-limit
```

### Current Setup

**Development**:
- Nginx: `CLIENT_MAX_BODY_SIZE=50m`
- Traefik: Global middleware allows up to 100MB

**Staging**:
- Nginx: `CLIENT_MAX_BODY_SIZE=50m`
- Traefik: Global middleware allows up to 100MB

**Production**:
- Nginx: `CLIENT_MAX_BODY_SIZE=100m`
- Traefik: Global middleware allows up to 100MB

## Why Both Nginx and Traefik Limits?

1. **Traefik (Reverse Proxy)**: 
   - First layer, handles SSL termination
   - Sets maximum allowed request size globally
   - Prevents extremely large requests from reaching backend

2. **Nginx (Frontend Service)**:
   - Second layer, serves static files and proxies to Gunicorn
   - Can have environment-specific limits
   - More granular control per environment

## Adjusting Limits

### Increase Traefik Limit (Global)

Edit `stacks/traefik.yml`:

```yaml
# Example: 500MB limit
- traefik.http.middlewares.body-size-limit.buffering.maxRequestBodyBytes=524288000
- traefik.http.middlewares.body-size-limit.buffering.memRequestBodyBytes=524288000
```

Then redeploy:
```bash
docker stack deploy -c stacks/traefik.yml traefik
```

### Increase Nginx Limit (Per Environment)

Edit environment config (e.g., `config/prod.env`):

```bash
CLIENT_MAX_BODY_SIZE=200m
```

Then redeploy the stack:
```bash
docker stack deploy -c stacks/brandclub-prod.yml brandclub-prod
```

## Common Upload Sizes

| Use Case | Recommended Size |
|----------|-----------------|
| Form submissions | 10m |
| Document uploads | 50m |
| Large files/imports | 100m |
| Bulk data imports | 500m |
| Database backups | 1000m (1g) |

## Troubleshooting

### "413 Request Entity Too Large"

**Nginx Error**: The client_max_body_size is too small.
- Check nginx logs: `docker service logs brandclub-prod_frontend`
- Increase `CLIENT_MAX_BODY_SIZE` in environment config

**Traefik Error**: The buffering limit is too small.
- Check Traefik logs: `docker service logs traefik_traefik`
- Increase `maxRequestBodyBytes` in Traefik middleware

### Check Current Limits

```bash
# Nginx limit (from container)
docker exec -it <container> grep client_max_body_size /etc/nginx/conf.d/frappe.conf

# Environment variable
docker service inspect brandclub-prod_frontend | grep CLIENT_MAX_BODY_SIZE
```

## Best Practices

1. **Set Traefik limit higher than Nginx**: Allows Nginx to handle the limit message
2. **Environment-specific limits**: Dev can be lower, Prod higher
3. **Monitor upload patterns**: Adjust based on actual usage
4. **Consider disk space**: Large uploads need storage
5. **Security**: Don't set unlimited - prevents DoS attacks

## References

- [Traefik Buffering Middleware](https://doc.traefik.io/traefik/middlewares/http/buffering/)
- [Nginx client_max_body_size](http://nginx.org/en/docs/http/ngx_http_core_module.html#client_max_body_size)
