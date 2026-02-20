#!/usr/bin/env bash

# =====================================================
# Brand Club - Multi-Environment Setup Script
# =====================================================
# Purpose: Initialize Docker Swarm and deploy all stacks
# Usage: ./setup-brandclub.sh
# =====================================================

set -e

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Print functions
print_header() {
    echo -e "\n${CYAN}========================================${NC}"
    echo -e "${CYAN}$1${NC}"
    echo -e "${CYAN}========================================${NC}\n"
}

print_success() {
    echo -e "${GREEN}✔ $1${NC}"
}

print_error() {
    echo -e "${RED}✘ $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠ $1${NC}"
}

print_info() {
    echo -e "${BLUE}ℹ $1${NC}"
}

# Prompt for input with default value
prompt() {
    local prompt_text="$1"
    local default_value="$2"
    local result
    
    if [ -n "$default_value" ]; then
        read -p "$(echo -e ${CYAN}${prompt_text}${NC} [${default_value}]: )" result
        echo "${result:-$default_value}"
    else
        read -p "$(echo -e ${CYAN}${prompt_text}${NC}: )" result
        echo "$result"
    fi
}

# Prompt for password (hidden input)
prompt_password() {
    local prompt_text="$1"
    local result
    
    read -s -p "$(echo -e ${CYAN}${prompt_text}${NC}: )" result
    echo ""
    echo "$result"
}

# Check if command exists
command_exists() {
    command -v "$1" >/dev/null 2>&1
}

# Banner
clear
echo -e "${CYAN}"
cat << "EOF"
╔═══════════════════════════════════════════════════════╗
║                                                       ║
║       Brand Club Multi-Environment Setup             ║
║       Production-Grade Docker Swarm Deployment       ║
║                                                       ║
╚═══════════════════════════════════════════════════════╝
EOF
echo -e "${NC}"

# =====================================================
# Step 1: Check Prerequisites
# =====================================================

print_header "Step 1: Checking Prerequisites"

if ! command_exists docker; then
    print_error "Docker is not installed. Please install Docker first."
    exit 1
fi
print_success "Docker is installed"

DOCKER_VERSION=$(docker --version | grep -oP '\d+\.\d+\.\d+' | head -1)
print_info "Docker version: $DOCKER_VERSION"

if ! command_exists curl; then
    print_warning "curl is not installed. Installing..."
    sudo apt-get update && sudo apt-get install -y curl
fi
print_success "curl is available"

# =====================================================
# Step 2: Gather Configuration
# =====================================================

print_header "Step 2: Configuration"

print_info "Please provide the following information:\n"

# Docker Registry Configuration
DOCKER_REGISTRY=$(prompt "Docker Registry URL" "ghcr.io")
DOCKER_ORG=$(prompt "Docker Organization/Username" "")

# Domain Configuration
print_info "\nDomain Configuration:"
DEV_DOMAIN=$(prompt "Development domain" "dev.brandclub.com")
MAILPIT_DOMAIN=$(prompt "Mailpit domain (dev only)" "mailpit.dev.brandclub.com")
STAGING_DOMAIN=$(prompt "Staging domain" "staging.brandclub.com")
PROD_DOMAIN=$(prompt "Production domain" "brandclub.com")
PROD_SITE=$(prompt "Production site name" "$PROD_DOMAIN")

# Database Configuration
print_info "\nDatabase Configuration:"
DB_ROOT_PASSWORD_DEV=$(prompt_password "MariaDB root password (DEV)")
DB_ROOT_PASSWORD_STAGING=$(prompt_password "MariaDB root password (STAGING)")
DB_ROOT_PASSWORD_PROD=$(prompt_password "MariaDB root password (PROD)")

# Frappe Admin Password
print_info "\nFrappe Configuration:"
ADMIN_PASSWORD=$(prompt_password "Frappe admin password (all environments)")

# Performance Settings
print_info "\nPerformance Settings:"
CLIENT_MAX_BODY_SIZE=$(prompt "Max upload size" "50m")

# Backup Configuration
print_info "\nBackup Configuration (Production only):"
BACKUP_DIR=$(prompt "Backup directory (host path)" "/backups")

# Email Configuration
print_info "\nEmail Configuration:"
LETSENCRYPT_EMAIL=$(prompt "Let's Encrypt email (for SSL)" "admin@${PROD_DOMAIN}")

# =====================================================
# Step 3: Initialize Docker Swarm
# =====================================================

print_header "Step 3: Initializing Docker Swarm"

if docker info 2>/dev/null | grep -q "Swarm: active"; then
    print_warning "Docker Swarm is already initialized"
    SWARM_INIT=$(prompt "Re-initialize Swarm? (will leave current swarm)" "no")
    
    if [ "$SWARM_INIT" = "yes" ]; then
        print_info "Leaving current swarm..."
        docker swarm leave --force
        print_info "Initializing new swarm..."
        docker swarm init
        print_success "Docker Swarm initialized"
    fi
else
    print_info "Initializing Docker Swarm..."
    docker swarm init
    print_success "Docker Swarm initialized"
fi

# Show swarm info
NODE_ID=$(docker node ls --format "{{.ID}}" | head -1)
print_info "Swarm Manager Node ID: $NODE_ID"

# =====================================================
# Step 4: Create Networks
# =====================================================

print_header "Step 4: Creating Overlay Networks"

# Function to create network if it doesn't exist
create_network() {
    local network_name=$1
    if docker network ls --format "{{.Name}}" | grep -q "^${network_name}$"; then
        print_warning "Network '$network_name' already exists"
    else
        docker network create --driver overlay --attachable "$network_name"
        print_success "Created network: $network_name"
    fi
}

# Create shared networks
create_network "traefik-public"
create_network "shared-services"

print_success "All networks created"

# =====================================================
# Step 5: Create Directories
# =====================================================

print_header "Step 5: Creating Directories"

# Create backup directory for production
if [ ! -d "$BACKUP_DIR" ]; then
    sudo mkdir -p "$BACKUP_DIR"
    sudo chmod 755 "$BACKUP_DIR"
    print_success "Created backup directory: $BACKUP_DIR"
else
    print_warning "Backup directory already exists: $BACKUP_DIR"
fi

# Create site-specific backup directory
sudo mkdir -p "$BACKUP_DIR/$PROD_SITE"
print_success "Created site backup directory: $BACKUP_DIR/$PROD_SITE"

# Create config directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_DIR="$SCRIPT_DIR/../config"
mkdir -p "$CONFIG_DIR"
print_success "Created config directory: $CONFIG_DIR"

# =====================================================
# Step 6: Generate Environment Files
# =====================================================

print_header "Step 6: Generating Environment Files"

# Development environment
cat > "$CONFIG_DIR/dev.env" << EOF
# Brand Club - Development Environment
# Generated: $(date)

# Docker Registry
DOCKER_REGISTRY=$DOCKER_REGISTRY
DOCKER_ORG=$DOCKER_ORG

# Domains
DEV_DOMAIN=$DEV_DOMAIN
MAILPIT_DOMAIN=$MAILPIT_DOMAIN

# Database
DB_ROOT_PASSWORD=$DB_ROOT_PASSWORD_DEV

# Performance
CLIENT_MAX_BODY_SIZE=$CLIENT_MAX_BODY_SIZE
EOF
print_success "Created dev.env"

# Staging environment
cat > "$CONFIG_DIR/staging.env" << EOF
# Brand Club - Staging Environment
# Generated: $(date)

# Docker Registry
DOCKER_REGISTRY=$DOCKER_REGISTRY
DOCKER_ORG=$DOCKER_ORG

# Domains
STAGING_DOMAIN=$STAGING_DOMAIN

# Database
DB_ROOT_PASSWORD=$DB_ROOT_PASSWORD_STAGING

# Performance
CLIENT_MAX_BODY_SIZE=$CLIENT_MAX_BODY_SIZE
EOF
print_success "Created staging.env"

# Production environment
cat > "$CONFIG_DIR/prod.env" << EOF
# Brand Club - Production Environment
# Generated: $(date)

# Docker Registry
DOCKER_REGISTRY=$DOCKER_REGISTRY
DOCKER_ORG=$DOCKER_ORG

# Domains
PROD_DOMAIN=$PROD_DOMAIN
PROD_SITE=$PROD_SITE

# Database
DB_ROOT_PASSWORD=$DB_ROOT_PASSWORD_PROD

# Backup
BACKUP_DIR=$BACKUP_DIR

# Performance
CLIENT_MAX_BODY_SIZE=$CLIENT_MAX_BODY_SIZE
EOF
print_success "Created prod.env"

# Secure environment files
chmod 600 "$CONFIG_DIR"/*.env
print_success "Secured environment files (chmod 600)"

# =====================================================
# Step 7: Deploy Traefik
# =====================================================

print_header "Step 7: Deploying Traefik (Reverse Proxy)"

TRAEFIK_STACK="$SCRIPT_DIR/../stacks/traefik.yml"
if [ -f "$TRAEFIK_STACK" ]; then
    print_info "Deploying Traefik stack..."
    
    # Create htpasswd for Traefik dashboard (optional)
    TRAEFIK_USER=$(prompt "Traefik dashboard username" "admin")
    TRAEFIK_PASSWORD=$(prompt_password "Traefik dashboard password")
    
    # Install htpasswd if not available
    if ! command_exists htpasswd; then
        print_info "Installing apache2-utils for htpasswd..."
        sudo apt-get update && sudo apt-get install -y apache2-utils
    fi
    
    TRAEFIK_HASHED_PASSWORD=$(htpasswd -nb "$TRAEFIK_USER" "$TRAEFIK_PASSWORD" | sed 's/\$/\$\$/g')
    
    # Deploy Traefik
    LETSENCRYPT_EMAIL="$LETSENCRYPT_EMAIL" \
    TRAEFIK_AUTH="$TRAEFIK_HASHED_PASSWORD" \
    docker stack deploy -c "$TRAEFIK_STACK" traefik
    
    print_success "Traefik deployed"
else
    print_warning "Traefik stack file not found, skipping..."
    print_info "You can deploy Traefik manually later"
fi

# =====================================================
# Step 8: Deploy Database Stacks
# =====================================================

print_header "Step 8: Deploying Database Stacks"

STACK_DIR="$SCRIPT_DIR/../stacks"

print_info "Database stacks must be deployed BEFORE application stacks"
print_info "They provide persistent MariaDB and Redis services\n"

# Function to deploy database stack
deploy_database_stack() {
    local env_name=$1
    local stack_name=$2
    local env_file=$3
    local stack_file="$STACK_DIR/database-${env_name}.yml"
    
    if [ -f "$stack_file" ]; then
        print_info "Deploying $stack_name..."
        
        # Load environment variables and deploy
        set -a
        source "$env_file"
        set +a
        
        docker stack deploy -c "$stack_file" "$stack_name"
        print_success "$stack_name deployed"
    else
        print_error "Database stack file not found: $stack_file"
    fi
}

# Ask which database stacks to deploy
DEPLOY_DEV=$(prompt "Deploy Development database stack?" "yes")
DEPLOY_STAGING=$(prompt "Deploy Staging database stack?" "yes")
DEPLOY_PROD=$(prompt "Deploy Production database stack?" "yes")

if [ "$DEPLOY_DEV" = "yes" ]; then
    deploy_database_stack "dev" "brandclub-db-dev" "$CONFIG_DIR/dev.env"
fi

if [ "$DEPLOY_STAGING" = "yes" ]; then
    deploy_database_stack "staging" "brandclub-db-staging" "$CONFIG_DIR/staging.env"
fi

if [ "$DEPLOY_PROD" = "yes" ]; then
    deploy_database_stack "prod" "brandclub-db-prod" "$CONFIG_DIR/prod.env"
fi

# Wait for database services to be ready
if [ "$DEPLOY_DEV" = "yes" ] || [ "$DEPLOY_STAGING" = "yes" ] || [ "$DEPLOY_PROD" = "yes" ]; then
    print_info "\nWaiting 20 seconds for database services to initialize..."
    sleep 20
fi

# =====================================================
# Step 9: Deploy Application Stacks
# =====================================================

print_header "Step 9: Deploying Application Stacks"

# Function to deploy application stack
deploy_app_stack() {
    local env_name=$1
    local stack_name=$2
    local env_file=$3
    local stack_file="$STACK_DIR/brandclub-${env_name}.yml"
    
    if [ -f "$stack_file" ]; then
        print_info "Deploying $stack_name..."
        
        # Load environment variables and deploy
        set -a
        source "$env_file"
        set +a
        
        docker stack deploy -c "$stack_file" "$stack_name"
        print_success "$stack_name deployed"
    else
        print_error "Stack file not found: $stack_file"
    fi
}

# Deploy application stacks (using same variables from database deployment)
if [ "$DEPLOY_DEV" = "yes" ]; then
    deploy_app_stack "dev" "brandclub-dev" "$CONFIG_DIR/dev.env"
fi

if [ "$DEPLOY_STAGING" = "yes" ]; then
    deploy_app_stack "staging" "brandclub-staging" "$CONFIG_DIR/staging.env"
fi

if [ "$DEPLOY_PROD" = "yes" ]; then
    deploy_app_stack "prod" "brandclub-prod" "$CONFIG_DIR/prod.env"
fi

# =====================================================
# Step 10: Wait for Services
# =====================================================

print_header "Step 10: Waiting for Services to Start"

print_info "Waiting 30 seconds for services to initialize..."
sleep 30

docker stack ls
echo ""

# =====================================================
# Step 11: Create Frappe Sites
# =====================================================

print_header "Step 11: Frappe Site Creation"

print_warning "Services are starting. Please wait 2-3 minutes for all containers to be healthy."
print_info "\nTo create sites, wait for services to be ready, then run:\n"

if [ "$DEPLOY_DEV" = "yes" ]; then
    echo -e "${YELLOW}# Development Site:${NC}"
    echo "CONTAINER=\$(docker ps -q -f name=brandclub-dev_backend)"
    echo "docker exec -it \$CONTAINER bench new-site $DEV_DOMAIN \\"
    echo "  --admin-password '$ADMIN_PASSWORD' \\"
    echo "  --db-root-password '$DB_ROOT_PASSWORD_DEV'"
    echo "docker exec -it \$CONTAINER bench --site $DEV_DOMAIN install-app brand_club"
    echo ""
fi

if [ "$DEPLOY_STAGING" = "yes" ]; then
    echo -e "${YELLOW}# Staging Site:${NC}"
    echo "CONTAINER=\$(docker ps -q -f name=brandclub-staging_backend)"
    echo "docker exec -it \$CONTAINER bench new-site $STAGING_DOMAIN \\"
    echo "  --admin-password '$ADMIN_PASSWORD' \\"
    echo "  --db-root-password '$DB_ROOT_PASSWORD_STAGING'"
    echo "docker exec -it \$CONTAINER bench --site $STAGING_DOMAIN install-app brand_club"
    echo ""
fi

if [ "$DEPLOY_PROD" = "yes" ]; then
    echo -e "${YELLOW}# Production Site:${NC}"
    echo "CONTAINER=\$(docker ps -q -f name=brandclub-prod_backend)"
    echo "docker exec -it \$CONTAINER bench new-site $PROD_DOMAIN \\"
    echo "  --admin-password '$ADMIN_PASSWORD' \\"
    echo "  --db-root-password '$DB_ROOT_PASSWORD_PROD'"
    echo "docker exec -it \$CONTAINER bench --site $PROD_DOMAIN install-app brand_club"
    echo ""
fi

# =====================================================
# Summary
# =====================================================

print_header "Setup Complete! 🎉"

echo -e "${GREEN}Your Brand Club multi-environment deployment is ready!${NC}\n"

echo -e "${CYAN}Environments Deployed:${NC}"
[ "$DEPLOY_DEV" = "yes" ] && echo -e "  ✔ Development: https://$DEV_DOMAIN"
[ "$DEPLOY_DEV" = "yes" ] && echo -e "  ✔ Mailpit: https://$MAILPIT_DOMAIN"
[ "$DEPLOY_STAGING" = "yes" ] && echo -e "  ✔ Staging: https://$STAGING_DOMAIN"
[ "$DEPLOY_PROD" = "yes" ] && echo -e "  ✔ Production: https://$PROD_DOMAIN"

echo -e "\n${CYAN}Next Steps:${NC}"
echo -e "  1. Wait 2-3 minutes for all services to be healthy"
echo -e "  2. Create Frappe sites using commands above"
echo -e "  3. Configure GitHub secrets for CI/CD"
echo -e "  4. Set up Portainer webhooks"
echo -e "  5. Push to branches to trigger automated deployments"

echo -e "\n${CYAN}Useful Commands:${NC}"
echo -e "  docker stack ls                  # List all stacks"
echo -e "  docker stack ps <stack-name>     # List services in stack"
echo -e "  docker service logs <service>    # View service logs"
echo -e "  docker service scale <service>=N # Scale service"

echo -e "\n${CYAN}Configuration Files:${NC}"
echo -e "  Environment configs: $CONFIG_DIR/"
echo -e "  Backups directory: $BACKUP_DIR/"

echo -e "\n${YELLOW}Important:${NC}"
echo -e "  • Keep environment files secure (already set to chmod 600)"
echo -e "  • Configure DNS before accessing sites"
echo -e "  • Monitor first deployment closely"
echo -e "  • Test backup service in production"

print_success "\nSetup completed successfully!"
echo ""
