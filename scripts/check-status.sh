#!/bin/bash
# Quick status check script for Frappe ERP deployment
# Shows health of all stacks and services

set -e

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "\n${BLUE}╔════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║  Frappe ERP Deployment Status Check             ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════════════╝${NC}\n"

# Function to print section header
print_section() {
    echo -e "\n${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${BLUE}$1${NC}"
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
}

# Function to check service status
check_service_status() {
    local service=$1
    local expected_replicas=$2
    
    local running=$(docker service ls --filter "name=$service" --format "{{.RunningCount}}" 2>/dev/null || echo "0")
    local desired=$(docker service ls --filter "name=$service" --format "{{.Replicas}}" | cut -d'/' -f2 2>/dev/null || echo "0")
    
    if [ -z "$running" ] || [ "$running" = "0" ] && [ "$desired" = "0" ]; then
        echo -e "  ${YELLOW}○${NC} $service: Not deployed"
    elif [ "$running" = "$desired" ] && [ ! -z "$running" ] && [ "$running" != "0" ]; then
        echo -e "  ${GREEN}✓${NC} $service: Running ($running/$desired)"
    else
        echo -e "  ${RED}✗${NC} $service: Degraded ($running/$desired)"
    fi
}

# Check Docker Swarm
print_section "Docker Swarm Status"
if docker info | grep -q "Swarm: active"; then
    echo -e "${GREEN}✓ Docker Swarm: Active${NC}"
    
    NODES=$(docker node ls --format "table {{.Hostname}}\t{{.Status}}\t{{.ManagerStatus}}")
    NODE_COUNT=$(echo "$NODES" | tail -n +2 | wc -l)
    echo -e "  Nodes: $NODE_COUNT"
    echo "$NODES" | tail -n +2 | while read line; do
        host=$(echo "$line" | awk '{print $1}')
        status=$(echo "$line" | awk '{print $2}')
        manager=$(echo "$line" | awk '{print $3}')
        if [ "$status" = "Ready" ]; then
            echo -e "    ${GREEN}●${NC} $host ($manager)"
        else
            echo -e "    ${RED}●${NC} $host ($status)"
        fi
    done
else
    echo -e "${RED}✗ Docker Swarm: Inactive${NC}"
fi

# Check stacks
print_section "Docker Stacks"
STACKS=$(docker stack ls --format "table {{.Name}}\t{{.Services}}" | tail -n +2)

if [ -z "$STACKS" ]; then
    echo -e "${YELLOW}⚠ No stacks deployed${NC}"
else
    echo "$STACKS" | while read stack_line; do
        STACK=$(echo "$stack_line" | awk '{print $1}')
        SERVICES=$(echo "$stack_line" | awk '{print $2}')
        echo -e "  ${GREEN}✓${NC} $STACK: $SERVICES services"
    done
fi

# Check key services
print_section "Key Services Status"

# Infrastructure
echo -e "${BLUE}Infrastructure:${NC}"
check_service_status "traefik" 1
check_service_status "portainer" 1
check_service_status "ofelia" 1

# Development
echo -e "\n${BLUE}Development Environment:${NC}"
check_service_status "brandclub-dev_backend" 1
check_service_status "brandclub-dev_frontend" 1
check_service_status "brandclub-dev_websocket" 1
check_service_status "brandclub-db-dev_mariadb" 1
check_service_status "brandclub-dev_redis-cache" 1

# Staging
echo -e "\n${BLUE}Staging Environment:${NC}"
check_service_status "brandclub-staging_backend" 1
check_service_status "brandclub-staging_frontend" 1
check_service_status "brandclub-staging_websocket" 1
check_service_status "brandclub-db-staging_mariadb" 1
check_service_status "brandclub-staging_redis-cache" 1

# Production
echo -e "\n${BLUE}Production Environment:${NC}"
check_service_status "brandclub-prod_backend" 1
check_service_status "brandclub-prod_frontend" 1
check_service_status "brandclub-prod_websocket" 1
check_service_status "brandclub-db-prod_mariadb" 1
check_service_status "brandclub-prod_redis-cache" 1
check_service_status "brandclub-prod_backup" 0

# System resources
print_section "System Resources"

DISK_USAGE=$(df -h / | tail -1 | awk '{print $5}')
DISK_TOTAL=$(df -h / | tail -1 | awk '{print $2}')
MEMORY=$(free -h | grep Mem | awk '{printf "%s / %s (%d%%)", $3, $2, int($3/$2*100)}')

echo -e "  Disk: $DISK_USAGE used of $DISK_TOTAL"
echo -e "  Memory: $MEMORY"

# Docker resources
RUNNING_CONTAINERS=$(docker ps -q | wc -l)
echo -e "  Running containers: $RUNNING_CONTAINERS"

# Check backups
print_section "Backups"

if [ -d "/backups" ]; then
    BACKUP_COUNT=$(find /backups -name "*-database*" 2>/dev/null | wc -l)
    BACKUP_SIZE=$(du -sh /backups 2>/dev/null | cut -f1)
    
    if [ $BACKUP_COUNT -gt 0 ]; then
        echo -e "  ${GREEN}✓${NC} Backups found: $BACKUP_COUNT"
        echo -e "  Total size: $BACKUP_SIZE"
        echo -e "  Latest backups:"
        find /backups -name "*-database*" -type f 2>/dev/null | sort -r | head -3 | while read backup; do
            size=$(du -h "$backup" | cut -f1)
            mtime=$(stat -c %y "$backup" | cut -d' ' -f1,2)
            echo -e "    • $(basename "$backup") ($size) - $mtime"
        done
    else
        echo -e "  ${YELLOW}⚠${NC} No backups yet (first backup runs at 2 AM)"
    fi
else
    echo -e "  ${RED}✗${NC} /backups directory does not exist"
fi

# Summary
print_section "Quick Links"

echo -e "  📍 Traefik Dashboard:     https://traefik.$(grep PROD_DOMAIN /home/abdul/Projects/Frappe-deploy/brand_club/stacks/brandclub-prod.yml | head -1 | awk '{print $2}' | tr -d '${}')"
echo -e "  🎛️  Portainer UI:          https://portainer.brandclub.site"
echo -e "  📧 Mailpit:               https://mailpit.brandclub.site"
echo -e "  🌍 Dev:                   https://erp-dev.brandclub.site"
echo -e "  🌍 Staging:               https://erp-staging.brandclub.site"
echo -e "  🌍 Production:            https://erp.brandclub.site"

print_section "Useful Commands"

echo -e "  # View service logs"
echo -e "    ${YELLOW}docker service logs <stack>_<service> -f${NC}"
echo -e ""
echo -e "  # Access container shell"
echo -e "    ${YELLOW}docker exec -it <container-id> bash${NC}"
echo -e ""
echo -e "  # Check stack details"
echo -e "    ${YELLOW}docker stack ps <stack-name>${NC}"
echo -e ""
echo -e "  # Update service image"
echo -e "    ${YELLOW}docker service update --image <new-image> <service-name>${NC}"
echo -e ""
echo -e "  # Scale service"
echo -e "    ${YELLOW}docker service scale <service-name>=<replicas>${NC}"

echo -e "\n${BLUE}════════════════════════════════════════════════${NC}\n"
