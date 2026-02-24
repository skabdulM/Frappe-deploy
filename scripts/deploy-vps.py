#!/usr/bin/env python3
"""
Frappe ERP Multi-Environment VPS Deployment Script
Deploys: Traefik → Portainer → Database Stacks → App Stacks → Ofelia → Frappe Sites

Senior DevOps Edition with proper sequencing, error handling, and state tracking.
"""

import os
import sys
import json
import subprocess
import logging
from pathlib import Path
from time import sleep
from datetime import datetime
from typing import Dict, Tuple

# ============================================================================
# CONFIGURATION
# ============================================================================

class Config:
    # Auto-detect base directory
    BASE_DIR = None  # Will be set during initialization
    STACKS_DIR = None
    LOGS_DIR = None
    STATE_FILE = None
    BACKUPS_DIR = Path("/backups")
    
    @classmethod
    def initialize(cls, base_dir: str = None):
        """Initialize paths based on base directory"""
        if base_dir:
            cls.BASE_DIR = Path(base_dir).resolve()
        else:
            # Try to auto-detect from current directory
            if (Path.cwd() / "brand_club" / "stacks").exists():
                cls.BASE_DIR = Path.cwd()
            else:
                # Prompt user
                print("\n📍 Where are your stack files located?")
                provided_dir = input("Enter base directory path (or press Enter for current dir): ").strip()
                cls.BASE_DIR = Path(provided_dir).resolve() if provided_dir else Path.cwd()
        
        cls.STACKS_DIR = cls.BASE_DIR / "brand_club" / "stacks"
        cls.LOGS_DIR = cls.BASE_DIR / "logs"
        cls.STATE_FILE = cls.BASE_DIR / ".deploy_state.json"
        
        logger.info(f"Base directory: {cls.BASE_DIR}")
    
    # Deployment sequence
    DEPLOY_SEQUENCE = [
        "traefik",
        "portainer",
        "registry_config",
        "database_stacks",
        "app_stacks",
        "ofelia",
        "frappe_sites",
        "summary"
    ]


# ============================================================================
# LOGGING SETUP
# ============================================================================

def setup_logging():
    """Configure logging to file and console"""
    Config.LOGS_DIR.mkdir(parents=True, exist_ok=True)
    
    log_file = Config.LOGS_DIR / f"deploy-{datetime.now().strftime('%Y%m%d-%H%M%S')}.log"
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)-8s - %(message)s',
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler()
        ]
    )
    
    return logging.getLogger("Deployer")


logger = setup_logging()


# ============================================================================
# STATE MANAGEMENT
# ============================================================================

class StateManager:
    """Manages deployment state for resumability"""
    
    @staticmethod
    def load():
        """Load deployment state"""
        if Config.STATE_FILE and Config.STATE_FILE.exists():
            with open(Config.STATE_FILE) as f:
                return json.load(f)
        return {
            "started_at": None,
            "completed_steps": [],
            "env_vars": {},
            "registry_config": {},
            "errors": []
        }
    
    @staticmethod
    def save(state: Dict):
        """Save deployment state"""
        with open(Config.STATE_FILE, 'w') as f:
            json.dump(state, f, indent=2)
    
    @staticmethod
    def mark_complete(state: Dict, step: str):
        """Mark step as completed"""
        if step not in state["completed_steps"]:
            state["completed_steps"].append(step)
        StateManager.save(state)
        logger.info(f"✅ Step '{step}' marked as complete")
    
    @staticmethod
    def record_error(state: Dict, step: str, error: str):
        """Record deployment error"""
        state["errors"].append({"step": step, "error": error, "time": datetime.now().isoformat()})
        StateManager.save(state)


# ============================================================================
# SHELL EXECUTION
# ============================================================================

class Shell:
    """Execute shell commands with proper error handling"""
    
    @staticmethod
    def run(cmd: str, check: bool = True, silent: bool = False) -> Tuple[int, str, str]:
        """
        Execute shell command
        Returns: (return_code, stdout, stderr)
        """
        if not silent:
            logger.debug(f"Executing: {cmd}")
        
        result = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            executable="/bin/bash"
        )
        
        if check and result.returncode != 0:
            logger.error(f"Command failed with exit code {result.returncode}")
            logger.error(f"Command: {cmd}")
            logger.error(f"Stderr: {result.stderr}")
            raise RuntimeError(f"Command failed: {cmd}\n{result.stderr}")
        
        return result.returncode, result.stdout, result.stderr
    
    @staticmethod
    def run_interactive(cmd: str):
        """Run command with interactive output"""
        logger.info(f"Running: {cmd}")
        return subprocess.run(cmd, shell=True, executable="/bin/bash").returncode


# ============================================================================
# PREREQUISITE CHECKS
# ============================================================================

class PreflightChecks:
    
    @staticmethod
    def docker_installed():
        """Verify Docker is installed"""
        logger.info("🔍 Checking Docker installation...")
        try:
            code, stdout, _ = Shell.run("docker --version", silent=True)
            logger.info(f"✅ {stdout.strip()}")
            return True
        except:
            logger.error("❌ Docker not found!")
            return False
    
    @staticmethod
    def swarm_initialized():
        """Verify Docker Swarm is initialized"""
        logger.info("🔍 Checking Docker Swarm...")
        try:
            code, stdout, _ = Shell.run("docker info 2>/dev/null | grep -i 'swarm'", silent=True)
            if "inactive" in stdout.lower():
                logger.warning("⚠️  Docker Swarm not initialized")
                if PreflightChecks._prompt_yn("Initialize Docker Swarm?"):
                    Shell.run("docker swarm init")
                    logger.info("✅ Docker Swarm initialized")
                    return True
                else:
                    logger.error("❌ Docker Swarm required for deployment!")
                    return False
            logger.info("✅ Docker Swarm active")
            return True
        except Exception as e:
            logger.error(f"❌ Swarm check failed: {e}")
            return False
    
    @staticmethod
    def directories_ready():
        """Create required directories"""
        logger.info("🔍 Checking directories...")
        
        required_dirs = [
            Config.STACKS_DIR,
            Config.BACKUPS_DIR,
            Config.LOGS_DIR
        ]
        
        for dir_path in required_dirs:
            dir_path.mkdir(parents=True, exist_ok=True)
            logger.info(f"  ✓ {dir_path}")
        
        # Set backups permissions
        try:
            Shell.run(f"sudo chmod 777 {Config.BACKUPS_DIR}")
            logger.info(f"✅ Directory permissions set")
        except:
            logger.warning(f"⚠️  Could not set permissions on {Config.BACKUPS_DIR}")
        
        return True
    
    @staticmethod
    def _prompt_yn(question: str) -> bool:
        """Yes/No prompt"""
        while True:
            response = input(f"\n{question} (y/n): ").lower().strip()
            if response in ['y', 'yes']:
                return True
            elif response in ['n', 'no']:
                return False
    
    @staticmethod
    def run_all():
        """Run all preflight checks"""
        logger.info("=" * 70)
        logger.info("Running Preflight Checks")
        logger.info("=" * 70)
        
        checks = [
            ("Docker", PreflightChecks.docker_installed),
            ("Swarm", PreflightChecks.swarm_initialized),
            ("Directories", PreflightChecks.directories_ready),
        ]
        
        for name, check in checks:
            try:
                if not check():
                    logger.error(f"❌ {name} check failed!")
                    return False
            except Exception as e:
                logger.error(f"❌ {name} check error: {e}")
                return False
        
        logger.info("✅ All preflight checks passed\n")
        return True


# ============================================================================
# ENVIRONMENT VARIABLES
# ============================================================================

class EnvironmentSetup:
    
    DEFAULTS = {
        "DB_ROOT_PASSWORD": "mannan@123",
        "DEV_DOMAIN": "erp-dev.brandclub.site",
        "STAGING_DOMAIN": "erp-staging.brandclub.site",
        "PROD_DOMAIN": "erp.brandclub.site",
        "MAILPIT_DOMAIN": "mailpit.brandclub.site",
        "PORTAINER_DOMAIN": "portainer.brandclub.site",
        "TAG_NAME": "main",
        "LETS_ENCRYPT_EMAIL": "admin@brandclub.site",
    }
    
    REGISTRY_DEFAULTS = {
        "GITHUB_USERNAME": "",
        "GITHUB_TOKEN": "",
    }
    
    @staticmethod
    def gather_registry_credentials(state: Dict) -> Dict:
        """Gather GitHub registry credentials for GHCR"""
        logger.info("=" * 70)
        logger.info("Container Registry Configuration (GHCR)")
        logger.info("=" * 70)
        
        registry = state.get("registry_config", {})
        
        if registry and registry.get("GITHUB_USERNAME"):
            use_saved = input("\n✓ Previously configured registry found. Use it? (y/n): ").lower()
            if use_saved == 'y':
                logger.info("✅ Using saved registry credentials")
                return registry
        
        logger.info("\n🐙 GitHub Container Registry Credentials")
        logger.info("   (Required for pulling private images from ghcr.io)\n")
        
        while True:
            username = input("  GitHub Username: ").strip()
            if username:
                registry["GITHUB_USERNAME"] = username
                break
            logger.warning("  Username is required!")
        
        while True:
            token = input("  GitHub PAT Token (read:packages): ").strip()
            if token:
                registry["GITHUB_TOKEN"] = token
                break
            logger.warning("  Token is required!")
        
        state["registry_config"] = registry
        StateManager.save(state)
        
        logger.info("\n✅ Registry credentials configured")
        return registry
    
    @staticmethod
    def gather_variables(state: Dict) -> Dict:
        """Interactively gather environment variables"""
        logger.info("=" * 70)
        logger.info("Environment Variables Configuration")
        logger.info("=" * 70)
        
        env_vars = state.get("env_vars", {})
        
        # Check if variables already configured
        if env_vars and len(env_vars) > 3:
            use_saved = input("\n✓ Previously configured variables found. Use them? (y/n): ").lower()
            if use_saved == 'y':
                logger.info("✅ Using saved environment variables")
                return env_vars
        
        logger.info("\n📋 Please configure the following variables:")
        logger.info("   (Press Enter to use default values shown in brackets)\n")
        
        for var_name, default_value in EnvironmentSetup.DEFAULTS.items():
            prompt_text = f"  {var_name} [{default_value}]"
            value = input(f"{prompt_text}: ").strip()
            env_vars[var_name] = value if value else default_value
        
        # GitHub Token (required, no default)
        logger.info("\n🔐 Additional Credentials:")
        while True:
            github_token = input("  GITHUB_TOKEN (for GHCR access): ").strip()
            if github_token:
                env_vars["GITHUB_TOKEN"] = github_token
                break
            else:
                logger.warning("  ⚠️  GitHub token is required!")
        
        # Save to state
        state["env_vars"] = env_vars
        StateManager.save(state)
        
        logger.info("\n✅ Environment variables configured")
        EnvironmentSetup._display_summary(env_vars)
        
        return env_vars
    
    @staticmethod
    def _display_summary(env_vars: Dict):
        """Display configured variables"""
        logger.info("\n📝 Configuration Summary:")
        for key, value in env_vars.items():
            if "TOKEN" in key or "PASSWORD" in key:
                display_val = "*" * len(value)
            else:
                display_val = value
            logger.info(f"  {key}: {display_val}")


# ============================================================================
# STACK DEPLOYMENT
# ============================================================================

class StackDeployer:
    
    @staticmethod
    def verify_stacks_exist():
        """Check if all required stack files exist"""
        logger.info("🔍 Checking stack files...")
        
        required_stacks = [
            "traefik.yml",
            "portainer.yml",
            "database-dev.yml",
            "database-staging.yml",
            "database-prod.yml",
            "brandclub-dev.yml",
            "brandclub-staging.yml",
            "brandclub-prod.yml",
        ]
        
        missing = []
        for stack in required_stacks:
            stack_path = Config.STACKS_DIR / stack
            if stack_path.exists():
                logger.info(f"  ✓ {stack}")
            else:
                logger.warning(f"  ✗ {stack} (MISSING)")
                missing.append(stack)
        
        if missing:
            logger.warning(f"\n⚠️  Missing {len(missing)} stack files!")
            logger.info("   Please copy/create these files to continue:")
            for stack in missing:
                logger.info(f"   - {Config.STACKS_DIR / stack}")
            return False
        
        logger.info("✅ All stack files present")
        return True
    
    @staticmethod
    def deploy_stack(stack_name: str, stack_file: str, wait_time: int = 5):
        """Deploy a Docker stack"""
        stack_path = Config.STACKS_DIR / stack_file
        
        if not stack_path.exists():
            logger.error(f"❌ Stack file not found: {stack_path}")
            raise FileNotFoundError(f"Stack file: {stack_path}")
        
        logger.info(f"📦 Deploying {stack_name}...")
        
        cmd = f"docker stack deploy -c {stack_path} {stack_name}"
        Shell.run(cmd)
        
        logger.info(f"   ⏳ Waiting {wait_time}s for deployment...")
        sleep(wait_time)
        
        # Show stack status
        code, stdout, _ = Shell.run(f"docker stack ps {stack_name} 2>/dev/null || echo 'Stack not ready'", check=False)
        if code == 0:
            logger.info(f"   ✅ {stack_name} deployed")
        else:
            logger.warning(f"   ⚠️  Status check failed for {stack_name}")
        
        return True


# ============================================================================
# SITE CREATION
# ============================================================================

class SiteManager:
    
    SITES = {
        "dev": {
            "domain_var": "DEV_DOMAIN",
            "stack": "brandclub-dev",
        },
        "staging": {
            "domain_var": "STAGING_DOMAIN",
            "stack": "brandclub-staging",
        },
        "prod": {
            "domain_var": "PROD_DOMAIN",
            "stack": "brandclub-prod",
        }
    }
    
    @staticmethod
    def get_backend_container(stack_name: str) -> str:
        """Get backend container ID for a stack"""
        cmd = f"docker ps --filter 'label=com.docker.swarm.service.name={stack_name}_backend' --format '{{.ID}}' | head -1"
        code, container_id, _ = Shell.run(cmd, check=False, silent=True)
        
        container_id = container_id.strip()
        if not container_id:
            raise RuntimeError(f"Backend container not found for stack: {stack_name}")
        
        return container_id
    
    @staticmethod
    def wait_for_service(stack_name: str, service: str, timeout: int = 120, check_interval: int = 5):
        """Wait for a service to be running"""
        logger.info(f"   ⏳ Waiting for {service} to start (max {timeout}s)...")
        
        elapsed = 0
        while elapsed < timeout:
            try:
                code, stdout, _ = Shell.run(
                    f"docker ps --filter 'label=com.docker.swarm.service.name={stack_name}_{service}' --format '{{.State}}'",
                    check=False,
                    silent=True
                )
                
                if "running" in stdout.lower():
                    logger.info(f"   ✓ {service} is running")
                    return True
            except:
                pass
            
            sleep(check_interval)
            elapsed += check_interval
        
        logger.warning(f"   ⚠️  {service} did not start within {timeout}s")
        return False
    
    @staticmethod
    def set_frappe_config(container_id: str, site_name: str):
        """Set Frappe configuration before site creation"""
        logger.info(f"   → Setting Frappe configuration...")
        
        config_commands = [
            "cd /home/frappe/frappe-bench && bench set-config -g db_host mariadb",
            "cd /home/frappe/frappe-bench && bench set-config -g redis_cache_host redis-cache:6379",
            "cd /home/frappe/frappe-bench && bench set-config -g redis_queue_host redis-queue:6379",
        ]
        
        for config_cmd in config_commands:
            try:
                Shell.run(f"docker exec {container_id} bash -c '{config_cmd}'", check=False)
                sleep(1)
            except Exception as e:
                logger.warning(f"     ⚠️  Config command failed: {e}")
        
        logger.info(f"   ✓ Configuration set")
    
    @staticmethod
    def create_site(container_id: str, site_name: str, env: str):
        """Create Frappe site"""
        logger.info(f"   → Creating site: {site_name}...")
        
        cmd = (
            f"docker exec {container_id} bash -c "
            f'"cd /home/frappe/frappe-bench && '
            f'bench new-site {site_name} --db-host=mariadb --db-port=3306"'
        )
        
        try:
            code, stdout, stderr = Shell.run(cmd, check=False)
            
            if code != 0:
                # Site might already exist
                if "already exists" in stderr.lower():
                    logger.info(f"   ✓ {site_name} already exists")
                    return True
                else:
                    logger.error(f"   ❌ Site creation failed")
                    logger.error(f"   Error: {stderr}")
                    return False
            
            logger.info(f"   ✓ Site created: {site_name}")
            sleep(3)
            return True
        
        except Exception as e:
            logger.error(f"   ❌ Exception during site creation: {e}")
            return False
    
    @staticmethod
    def install_apps(container_id: str, site_name: str):
        """Install Frappe apps"""
        logger.info(f"   → Installing apps...")
        
        apps = ["insights", "drive", "brand_club"]
        
        cmd = (
            f"docker exec {container_id} bash -c "
            f'"cd /home/frappe/frappe-bench && '
            f'bench install-app {" ".join(apps)} --site {site_name}"'
        )
        
        try:
            code, stdout, stderr = Shell.run(cmd, check=False)
            
            if code == 0:
                logger.info(f"   ✓ Apps installed")
                return True
            else:
                logger.warning(f"   ⚠️  App installation had issues")
                logger.debug(f"   Output: {stderr[:500]}")
                return False
        
        except Exception as e:
            logger.warning(f"   ⚠️  Exception during app install: {e}")
            return False
    
    @staticmethod
    def create_all_sites(env_vars: Dict):
        """Create sites for all environments"""
        logger.info("=" * 70)
        logger.info("Creating Frappe Sites")
        logger.info("=" * 70)
        
        success_count = 0
        
        for env, config in SiteManager.SITES.items():
            try:
                site_name = env_vars.get(config["domain_var"], f"erp-{env}.brandclub.site")
                stack_name = config["stack"]
                
                logger.info(f"\n🌍 {env.upper()} Environment")
                logger.info(f"   Site: {site_name}")
                logger.info(f"   Stack: {stack_name}")
                
                # Wait for backend
                if not SiteManager.wait_for_service(stack_name, "backend", timeout=120):
                    logger.error(f"   ❌ Backend failed to start")
                    continue
                
                # Get container
                try:
                    container_id = SiteManager.get_backend_container(stack_name)
                except RuntimeError as e:
                    logger.error(f"   ❌ {e}")
                    continue
                
                # Set config BEFORE creating site (important!)
                SiteManager.set_frappe_config(container_id, site_name)
                sleep(2)
                
                # Create site
                if not SiteManager.create_site(container_id, site_name, env):
                    continue
                
                # Install apps
                if SiteManager.install_apps(container_id, site_name):
                    success_count += 1
                    logger.info(f"   ✅ {env.upper()} setup complete")
                else:
                    logger.warning(f"   ⚠️  {env.upper()} partially complete (apps may need install)")
            
            except Exception as e:
                logger.error(f"   ❌ Error setting up {env}: {e}")
                continue
        
        logger.info(f"\n✅ Site creation complete ({success_count}/{len(SiteManager.SITES)} successful)")
        return success_count > 0


# ============================================================================
# MAIN DEPLOYER
# ============================================================================

class VPSDeployer:
    
    def __init__(self):
        self.state = StateManager.load()
        self.env_vars = {}
    
    def deploy_traefik(self):
        """Deploy Traefik reverse proxy"""
        logger.info("=" * 70)
        logger.info("STEP 1: Traefik Reverse Proxy")
        logger.info("=" * 70)
        
        StackDeployer.deploy_stack("traefik", "traefik.yml", wait_time=10)
        
        logger.info("ℹ️  Access Traefik dashboard at: https://traefik.{PROD_DOMAIN}")
        StateManager.mark_complete(self.state, "traefik")
    
    def deploy_portainer(self):
        """Deploy Portainer management UI"""
        logger.info("\n" + "=" * 70)
        logger.info("STEP 2: Portainer Management UI")
        logger.info("=" * 70)
        
        StackDeployer.deploy_stack("portainer", "portainer.yml", wait_time=15)
        
        portainer_domain = self.env_vars.get("PORTAINER_DOMAIN", "portainer.brandclub.site")
        logger.info(f"📍 Access Portainer at: https://{portainer_domain}")
        logger.info("⚠️  Note: Portainer will be available in 30-60 seconds")
        
        StateManager.mark_complete(self.state, "portainer")
    
    def configure_registry(self):
        """Configure GHCR registry in Portainer"""
        logger.info("\n" + "=" * 70)
        logger.info("STEP 2.5: Container Registry Setup")
        logger.info("=" * 70)
        
        # Gather credentials
        registry = EnvironmentSetup.gather_registry_credentials(self.state)
        
        logger.info("\n📝 Registry credentials saved")
        logger.info("⚠️  IMPORTANT - Manual Step Required:")
        logger.info("   1. Go to: https://{portainer_domain}".format(
            portainer_domain=self.env_vars.get("PORTAINER_DOMAIN", "portainer.brandclub.site")
        ))
        logger.info("   2. Settings → Registries → Add Registry")
        logger.info("   3. Configure:")
        logger.info("      Name: ghcr")
        logger.info("      URL: ghcr.io")
        logger.info(f"      Username: {registry['GITHUB_USERNAME']}")
        logger.info("      Password: [your GitHub PAT token]")
        logger.info("   4. Click 'Add'")
        logger.info("\n   ℹ️  This allows Portainer to pull from ghcr.io")
        
        StateManager.mark_complete(self.state, "registry_config")
    
    def deploy_database_stacks(self):
        """Deploy MariaDB stacks for all environments"""
        logger.info("\n" + "=" * 70)
        logger.info("STEP 3: Database Stacks (MariaDB)")
        logger.info("=" * 70)
        
        for env in ["dev", "staging", "prod"]:
            try:
                StackDeployer.deploy_stack(f"brandclub-db-{env}", f"database-{env}.yml", wait_time=8)
            except Exception as e:
                logger.error(f"❌ Failed to deploy database-{env}: {e}")
                StateManager.record_error(self.state, "database_stacks", str(e))
        
        logger.info("\n⏳ Waiting 30s for MariaDB containers to fully initialize...")
        sleep(30)
        
        StateManager.mark_complete(self.state, "database_stacks")
    
    def deploy_app_stacks(self):
        """Deploy application stacks for all environments"""
        logger.info("\n" + "=" * 70)
        logger.info("STEP 4: Application Stacks")
        logger.info("=" * 70)
        
        for env in ["dev", "staging", "prod"]:
            try:
                StackDeployer.deploy_stack(f"brandclub-{env}", f"brandclub-{env}.yml", wait_time=10)
            except Exception as e:
                logger.error(f"❌ Failed to deploy brandclub-{env}: {e}")
                StateManager.record_error(self.state, "app_stacks", str(e))
        
        logger.info("\n⏳ Waiting 20s for services to stabilize...")
        sleep(20)
        
        StateManager.mark_complete(self.state, "app_stacks")
    
    def deploy_ofelia(self):
        """Deploy Ofelia cron scheduler"""
        logger.info("\n" + "=" * 70)
        logger.info("STEP 5: Ofelia Cron Scheduler")
        logger.info("=" * 70)
        
        stack_file = Config.STACKS_DIR / "ofelia.yml"
        
        if stack_file.exists():
            try:
                StackDeployer.deploy_stack("ofelia", "ofelia.yml", wait_time=8)
            except Exception as e:
                logger.error(f"❌ Failed to deploy ofelia: {e}")
                StateManager.record_error(self.state, "ofelia", str(e))
        else:
            logger.info("📦 Deploying Ofelia as service...")
            cmd = (
                "docker service create "
                "--name ofelia "
                "--constraint 'node.role==manager' "
                "--mount type=bind,source=/var/run/docker.sock,target=/var/run/docker.sock "
                "mcuadros/ofelia:latest "
                "daemon --docker"
            )
            try:
                Shell.run(cmd)
                sleep(8)
                logger.info("✅ Ofelia deployed")
            except Exception as e:
                logger.error(f"❌ Failed to deploy ofelia: {e}")
                StateManager.record_error(self.state, "ofelia", str(e))
        
        logger.info("✅ Cron scheduler ready - backups will run on schedule")
        StateManager.mark_complete(self.state, "ofelia")
    
    def create_sites(self):
        """Create Frappe sites in all environments"""
        logger.info("\n" + "=" * 70)
        logger.info("STEP 6: Creating Frappe Sites")
        logger.info("=" * 70)
        
        try:
            SiteManager.create_all_sites(self.env_vars)
        except Exception as e:
            logger.error(f"❌ Site creation failed: {e}")
            StateManager.record_error(self.state, "frappe_sites", str(e))
        
        StateManager.mark_complete(self.state, "frappe_sites")
    
    def display_summary(self):
        """Display deployment summary"""
        logger.info("\n" + "=" * 70)
        logger.info("🎉 DEPLOYMENT COMPLETE!")
        logger.info("=" * 70)
        
        logger.info("\n📍 Access Points:")
        
        prod_domain = self.env_vars.get("PROD_DOMAIN", "erp.brandclub.site")
        dev_domain = self.env_vars.get("DEV_DOMAIN", "erp-dev.brandclub.site")
        staging_domain = self.env_vars.get("STAGING_DOMAIN", "erp-staging.brandclub.site")
        mailpit_domain = self.env_vars.get("MAILPIT_DOMAIN", "mailpit.brandclub.site")
        portainer_domain = self.env_vars.get("PORTAINER_DOMAIN", "portainer.brandclub.site")
        
        logger.info(f"  🔗 Traefik:  https://traefik.{prod_domain}")
        logger.info(f"  🎛️  Portainer: https://{portainer_domain}")
        logger.info(f"  📧 Mailpit:  https://{mailpit_domain}")
        logger.info(f"  🌍 Dev ERP:     https://{dev_domain}")
        logger.info(f"  🌍 Staging ERP: https://{staging_domain}")
        logger.info(f"  🌍 Prod ERP:    https://{prod_domain}")
        
        logger.info("\n📋 Next Steps:")
        logger.info("  1. ✅ Access Portainer and set admin password")
        logger.info("  2. ✅ Add GHCR registry (Settings → Registries)")
        logger.info("  3. ✅ Verify all stacks are running")
        logger.info("  4. ⏳ Wait 1-2 minutes for sites to fully start")
        logger.info("  5. ⏳ Configure GitHub Actions (optional)")
        
        registry_user = self.state.get('registry_config', {}).get('GITHUB_USERNAME', 'configured')
        logger.info("\n🔐 Important Credentials:")
        logger.info(f"  • MariaDB Root: admin / {self.env_vars.get('DB_ROOT_PASSWORD')}")
        logger.info(f"  • GHCR User: {registry_user}")
        logger.info(f"  • Portainer: Set on first login")
        
        logger.info("\n📂 Locations:")
        logger.info(f"  • Logs: {Config.LOGS_DIR}")
        logger.info(f"  • Stacks: {Config.STACKS_DIR}")
        logger.info(f"  • Backups: {Config.BACKUPS_DIR}")
        logger.info(f"  • State: {Config.STATE_FILE}")
        
        logger.info("\n" + "=" * 70)
        StateManager.mark_complete(self.state, "summary")
    
    def run(self):
        """Execute full deployment"""
        logger.info("""
╔══════════════════════════════════════════════════════════════════════╗
║                                                                      ║
║       Frappe ERP Multi-Environment VPS Deployment                   ║
║            Traefik → Portainer → Stacks → Sites                     ║
║                                                                      ║
║                    Senior DevOps Edition                            ║
║                                                                      ║
╚══════════════════════════════════════════════════════════════════════╝
        """)
        
        try:
            # Initialize base directory
            Config.initialize()
            
            # Preflight checks
            if not PreflightChecks.run_all():
                logger.error("❌ Preflight checks failed!")
                return False
            
            # Gather environment variables
            self.env_vars = EnvironmentSetup.gather_variables(self.state)
            
            # Verify stacks exist
            if not StackDeployer.verify_stacks_exist():
                logger.error("❌ Stack files missing! Cannot continue.")
                return False
            
            # Check for resumed deployment
            remaining_steps = [s for s in Config.DEPLOY_SEQUENCE if s not in self.state["completed_steps"]]
            
            if len(remaining_steps) < len(Config.DEPLOY_SEQUENCE):
                logger.info(f"\n✓ Resuming deployment ({len(remaining_steps)} steps remaining)")
                logger.info(f"  Completed: {', '.join(self.state['completed_steps'])}")
            
            # Execute deployment steps
            if "traefik" in remaining_steps:
                self.deploy_traefik()
            
            if "portainer" in remaining_steps:
                self.deploy_portainer()
            
            if "registry_config" in remaining_steps:
                self.configure_registry()
            
            if "database_stacks" in remaining_steps:
                self.deploy_database_stacks()
            
            if "app_stacks" in remaining_steps:
                self.deploy_app_stacks()
            
            if "ofelia" in remaining_steps:
                self.deploy_ofelia()
            
            if "frappe_sites" in remaining_steps:
                self.create_sites()
            
            # Summary
            self.display_summary()
            
            logger.info("\n✅ Deployment succeeded! Logs saved to:")
            logger.info(f"   {Config.LOGS_DIR}")
            
            return True
        
        except KeyboardInterrupt:
            logger.info("\n\n⚠️  Deployment interrupted by user")
            logger.info(f"   To resume later, run this script again")
            return False
        
        except Exception as e:
            logger.error(f"\n❌ Deployment failed: {e}")
            logger.exception("Full traceback:")
            StateManager.record_error(self.state, "deployment", str(e))
            return False


# ============================================================================
# ENTRY POINT
# ============================================================================

if __name__ == "__main__":
    deployer = VPSDeployer()
    success = deployer.run()
    sys.exit(0 if success else 1)
