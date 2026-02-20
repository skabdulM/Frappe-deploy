#!/usr/bin/env python3
"""
Backup Frappe production site to /backups directory
Usage: python3 backup-prod.py --site develop-erp.brandclub.site
"""

import os
import sys
import gzip
import subprocess
from pathlib import Path
from datetime import datetime
import argparse
import json


class ProdBackupCreator:
    def __init__(self, backup_dir):
        self.backup_dir = Path(backup_dir)
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        
        self.db_host = os.getenv('DB_HOST', 'mariadb')
        self.db_user = 'root'
        self.db_password = os.getenv('DB_ROOT_PASSWORD', '')
        self.sites_dir = Path('/home/frappe/frappe-bench/sites')

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
        
        return site_name.replace('.', '_')

    def backup_database(self, site_name, backup_file):
        """Backup site database"""
        db_name = self.get_site_db_name(site_name)
        
        print(f"   → Backing up database: {db_name}")
        try:
            with open(backup_file, 'wb') as f_out:
                cmd = [
                    'mysqldump',
                    f'-h{self.db_host}',
                    f'-u{self.db_user}',
                    f'-p{self.db_password}',
                    '--single-transaction',
                    '--lock-tables=false',
                    db_name
                ]
                result = subprocess.run(cmd, stdout=subprocess.PIPE, check=True, 
                                      capture_output=False)
                
                # Gzip the output
                with gzip.open(backup_file, 'wb') as f_gz:
                    f_gz.write(result.stdout)
            
            size_mb = backup_file.stat().st_size / (1024 * 1024)
            print(f"   ✅ Database backup complete ({size_mb:.2f} MB)")
            return True
            
        except subprocess.CalledProcessError as e:
            print(f"   ❌ Database backup failed: {e.stderr.decode() if e.stderr else str(e)}")
            return False

    def backup_files(self, site_name, backup_file):
        """Backup site files"""
        site_path = self.sites_dir / site_name
        files_backup = backup_file.parent / backup_file.name.replace('.sql.gz', '-files.tar.gz')
        
        print(f"   → Backing up site files")
        try:
            cmd = [
                'tar', 'czf', str(files_backup),
                '-C', str(self.sites_dir),
                site_name
            ]
            subprocess.run(cmd, check=True, capture_output=True)
            
            size_mb = files_backup.stat().st_size / (1024 * 1024)
            print(f"   ✅ Files backup complete ({size_mb:.2f} MB)")
            return True
            
        except subprocess.CalledProcessError as e:
            print(f"   ⚠️  Files backup failed (continuing): {e.stderr.decode() if e.stderr else str(e)}")
            return False

    def run(self, site_name):
        """Create backup for site"""
        print("\n" + "="*60)
        print("  💾 Production Backup Tool")
        print("="*60)
        
        # Validate site exists
        site_path = self.sites_dir / site_name
        if not site_path.exists():
            print(f"❌ Site not found: {site_name}")
            sys.exit(1)
        
        # Create backup filename
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_file = self.backup_dir / f"{site_name}-{timestamp}.sql.gz"
        
        print(f"\n🔄 Creating backup for {site_name}")
        print(f"   Location: {self.backup_dir}\n")
        
        # Backup database
        if not self.backup_database(site_name, backup_file):
            sys.exit(1)
        
        # Backup files
        self.backup_files(site_name, backup_file)
        
        print(f"\n✅ Backup created successfully!\n")
        return True


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='Backup Frappe production site'
    )
    parser.add_argument(
        '--site',
        required=True,
        help='Site name to backup (e.g., develop-erp.brandclub.site)'
    )
    parser.add_argument(
        '--backup-dir',
        default='/backups',
        help='Backup directory (default: /backups)'
    )
    
    args = parser.parse_args()
    
    creator = ProdBackupCreator(args.backup_dir)
    creator.run(args.site)
