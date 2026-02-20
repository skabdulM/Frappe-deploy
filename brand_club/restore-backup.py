#!/usr/bin/env python3
"""
Restore Frappe backup to any site/environment
Usage: python3 restore-backup.py --backup-dir /backups --sites-dir /home/frappe/frappe-bench/sites
"""

import os
import sys
import gzip
import subprocess
import json
from pathlib import Path
from datetime import datetime
import argparse


class BackupRestorer:
    def __init__(self, backup_dir, sites_dir):
        self.backup_dir = Path(backup_dir)
        self.sites_dir = Path(sites_dir)
        self.db_host = os.getenv('DB_HOST', 'mariadb')
        self.db_user = 'root'
        self.db_password = os.getenv('DB_ROOT_PASSWORD', '')
        
        # Validate paths
        if not self.backup_dir.exists():
            print(f"❌ Backup directory not found: {self.backup_dir}")
            sys.exit(1)
        if not self.sites_dir.exists():
            print(f"❌ Sites directory not found: {self.sites_dir}")
            sys.exit(1)

    def list_backups(self):
        """List all available backups"""
        backups = list(self.backup_dir.glob('*.sql.gz'))
        
        if not backups:
            print("❌ No backups found in", self.backup_dir)
            sys.exit(1)
        
        # Sort by modification time (newest first)
        backups.sort(key=lambda x: x.stat().st_mtime, reverse=True)
        
        print("\n📦 Available Backups:\n")
        for i, backup in enumerate(backups, 1):
            size_mb = backup.stat().st_size / (1024 * 1024)
            mtime = datetime.fromtimestamp(backup.stat().st_mtime)
            print(f"  {i}. {backup.name}")
            print(f"     Size: {size_mb:.2f} MB | Modified: {mtime.strftime('%Y-%m-%d %H:%M:%S')}\n")
        
        return backups

    def list_sites(self):
        """List all available sites"""
        sites = [d for d in self.sites_dir.iterdir() if d.is_dir() and not d.name.startswith('.')]
        
        if not sites:
            print("❌ No sites found in", self.sites_dir)
            sys.exit(1)
        
        sites.sort()
        
        print("\n🏢 Available Sites:\n")
        for i, site in enumerate(sites, 1):
            print(f"  {i}. {site.name}")
        print()
        
        return sites

    def get_site_db_name(self, site_name):
        """Extract database name from site config"""
        site_config = self.sites_dir / site_name / 'site_config.json'
        
        if site_config.exists():
            try:
                with open(site_config) as f:
                    config = json.load(f)
                    return config.get('db_name', site_name)
            except:
                pass
        
        # Default: replace dots with underscores
        return site_name.replace('.', '_')

    def restore_backup(self, backup_file, target_site):
        """Restore backup to target site"""
        print(f"\n🔄 Restoring backup to {target_site}...")
        
        # Get database name
        db_name = self.get_site_db_name(target_site)
        
        # Extract and restore database
        print(f"   → Restoring database: {db_name}")
        try:
            with gzip.open(backup_file, 'rb') as f:
                cmd = [
                    'mysql',
                    f'-h{self.db_host}',
                    f'-u{self.db_user}',
                    f'-p{self.db_password}',
                    db_name
                ]
                subprocess.run(cmd, stdin=f, check=True, capture_output=True)
            print(f"   ✅ Database restored successfully")
        except subprocess.CalledProcessError as e:
            print(f"   ❌ Database restore failed: {e.stderr.decode()}")
            return False
        
        # Check for files backup
        files_backup = backup_file.parent / backup_file.name.replace('.sql.gz', '-files.tar.gz')
        if files_backup.exists():
            print(f"   → Restoring files from {files_backup.name}")
            try:
                target_path = self.sites_dir / target_site
                subprocess.run(
                    ['tar', 'xzf', str(files_backup), '-C', str(target_path)],
                    check=True,
                    capture_output=True
                )
                print(f"   ✅ Files restored successfully")
            except subprocess.CalledProcessError as e:
                print(f"   ⚠️  Files restore failed (continuing): {e.stderr.decode()}")
        
        print(f"\n✅ Restore completed for {target_site}\n")
        return True

    def run(self):
        """Interactive restore workflow"""
        print("\n" + "="*60)
        print("  🔧 Frappe Backup Restore Tool")
        print("="*60)
        
        # List and select backup
        backups = self.list_backups()
        while True:
            try:
                choice = input("Select backup number (or 'q' to quit): ").strip()
                if choice.lower() == 'q':
                    sys.exit(0)
                backup_idx = int(choice) - 1
                if 0 <= backup_idx < len(backups):
                    selected_backup = backups[backup_idx]
                    break
                print("❌ Invalid selection. Try again.")
            except ValueError:
                print("❌ Invalid input. Try again.")
        
        # List and select target site
        sites = self.list_sites()
        while True:
            try:
                choice = input("Select target site number: ").strip()
                site_idx = int(choice) - 1
                if 0 <= site_idx < len(sites):
                    selected_site = sites[site_idx].name
                    break
                print("❌ Invalid selection. Try again.")
            except ValueError:
                print("❌ Invalid input. Try again.")
        
        # Confirm
        print(f"\n⚠️  WARNING: This will overwrite data in {selected_site}")
        confirm = input(f"Type 'yes' to restore {selected_backup.name} to {selected_site}: ").strip()
        
        if confirm != 'yes':
            print("❌ Restore cancelled.")
            sys.exit(0)
        
        # Restore
        if self.restore_backup(selected_backup, selected_site):
            print(f"Run 'bench --site {selected_site} migrate' to complete restoration (if needed)")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='Restore Frappe backup to any site'
    )
    parser.add_argument(
        '--backup-dir',
        default='/backups',
        help='Backup directory (default: /backups)'
    )
    parser.add_argument(
        '--sites-dir',
        default='/home/frappe/frappe-bench/sites',
        help='Frappe sites directory'
    )
    
    args = parser.parse_args()
    
    restorer = BackupRestorer(args.backup_dir, args.sites_dir)
    restorer.run()
