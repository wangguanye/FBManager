import shutil
import os
import glob
from datetime import datetime, timedelta
import yaml
from loguru import logger
from sqlalchemy import text
from db.database import AsyncSessionLocal

def load_config():
    with open("config.yaml", "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

async def perform_backup():
    """
    Perform database backup.
    """
    config = load_config()
    backup_config = config.get("backup", {})
    backup_dir = backup_config.get("backup_dir", "backups/")
    max_backups = backup_config.get("max_backups", 30)
    
    # Ensure backup directory exists
    if not os.path.exists(backup_dir):
        os.makedirs(backup_dir)
        
    # Source database file
    db_file = "fb_manager.db"
    if not os.path.exists(db_file):
        logger.warning(f"Database file {db_file} not found, skipping backup.")
        return False, "Database file not found"

    # Create backup filename
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_filename = f"fb_manager_{timestamp}.db"
    backup_path = os.path.join(backup_dir, backup_filename)
    
    try:
        shutil.copy2(db_file, backup_path)
        logger.info(f"Database backup created at {backup_path}")
        
        # Cleanup old backups
        _cleanup_old_backups(backup_dir, max_backups)
        
        return True, f"Backup created: {backup_filename}"
    except Exception as e:
        logger.error(f"Backup failed: {e}")
        return False, str(e)

def _cleanup_old_backups(backup_dir, max_backups):
    """
    Keep only the latest max_backups files.
    """
    try:
        # Get list of backup files
        files = glob.glob(os.path.join(backup_dir, "fb_manager_*.db"))
        # Sort by modification time (newest first)
        files.sort(key=os.path.getmtime, reverse=True)
        
        if len(files) > max_backups:
            files_to_delete = files[max_backups:]
            for f in files_to_delete:
                try:
                    os.remove(f)
                    logger.info(f"Deleted old backup: {f}")
                except Exception as e:
                    logger.warning(f"Failed to delete old backup {f}: {e}")
    except Exception as e:
        logger.error(f"Error cleaning up old backups: {e}")

async def perform_log_cleanup():
    """
    Clean up old action logs based on retention policy.
    """
    config = load_config()
    retention_config = config.get("log_retention", {})
    info_days = retention_config.get("info_days", 30)
    warn_error_days = retention_config.get("warn_error_days", 90)
    
    logger.info("Starting log cleanup...")
    
    async with AsyncSessionLocal() as db:
        try:
            # Delete INFO logs
            info_date_threshold = datetime.now() - timedelta(days=info_days)
            stmt_info = text("DELETE FROM action_logs WHERE level = 'INFO' AND created_at < :date")
            res_info = await db.execute(stmt_info, {"date": info_date_threshold})
            logger.info(f"Deleted {res_info.rowcount} old INFO logs.")
            
            # Delete WARN/ERROR/CRITICAL logs
            warn_date_threshold = datetime.now() - timedelta(days=warn_error_days)
            stmt_warn = text("DELETE FROM action_logs WHERE level IN ('WARN', 'ERROR', 'CRITICAL') AND created_at < :date")
            res_warn = await db.execute(stmt_warn, {"date": warn_date_threshold})
            logger.info(f"Deleted {res_warn.rowcount} old WARN/ERROR/CRITICAL logs.")
            
            await db.commit()
            return True
        except Exception as e:
            logger.error(f"Log cleanup failed: {e}")
            await db.rollback()
            return False
