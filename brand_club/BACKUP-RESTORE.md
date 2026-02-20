# Backup & Restore Guide

## Setup

Add to your app stacks (dev/staging/prod) in the volumes section:

```yaml
volumes:
  - backups:/backups
```

And at the end:

```yaml
volumes:
  backups:
    name: brandclub-{env}-backups
```

Or mount a host directory:
```yaml
volumes:
  - /var/backups/brandclub:/backups
```

---

## Backup Production Site

Run inside the production backend container:

```bash
docker exec -it <prod-backend-container> python3 /path/to/backup-prod.py \
  --site erp.brandclub.site \
  --backup-dir /backups
```

This creates:
- `{site}-YYYYMMDD_HHMMSS.sql.gz` - Database dump
- `{site}-YYYYMMDD_HHMMSS-files.tar.gz` - Site files (optional)

---

## Restore Backup to Any Site

Run inside any backend container (dev/staging/prod):

```bash
docker exec -it <backend-container> python3 /path/to/restore-backup.py \
  --backup-dir /backups
```

**Interactive Flow:**
1. Lists all available backups
2. Select which backup
3. Lists all available sites
4. Select target site
5. Confirm (type 'yes')
6. Restore completes

---

## Automate Backups

Add to Docker container as cron job, or use a backup service in the stack:

```yaml
backup-scheduler:
  image: ghcr.io/brandclub/brand-club-erp:prod
  deploy:
    restart_policy:
      condition: on-failure
  command:
    - bash
    - -c
    - |
      # Run backup daily at 2 AM
      echo "0 2 * * * python3 /path/to/backup-prod.py --site erp.brandclub.site --backup-dir /backups" | crontab -
      crond -f
  volumes:
    - sites:/home/frappe/frappe-bench/sites:ro
    - backups:/backups
  networks:
    - brandclub-prod-network
    - brandclub-prod-mariadb
```

---

## Notes

- Backups are **database + files combined** for complete restoration
- Only database dump is compressed (SQL)
- Files are optional (backup completes even if files backup fails)
- Always confirm before restoring (type 'yes' to prevent accidents)
