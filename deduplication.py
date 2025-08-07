import json
import os
import logging
from typing import Set, List
from utils import setup_logging

# Setup logging
setup_logging()
logger = logging.getLogger(__name__)

class DeduplicationManager:
    """Manages synced invoice tracking to prevent duplicates"""
    
    def __init__(self, file_path: str = 'synced_invoices.json'):
        self.file_path = file_path
        self.synced_invoices: Set[str] = set()
        self._load_synced_invoices()
    
    def _load_synced_invoices(self) -> None:
        """Load previously synced invoice numbers from JSON file"""
        try:
            if os.path.exists(self.file_path):
                with open(self.file_path, 'r') as f:
                    data = json.load(f)
                    self.synced_invoices = set(data.get('synced_invoices', []))
                logger.info(f"Loaded {len(self.synced_invoices)} previously synced invoices")
            else:
                logger.info("No existing synced invoices file found, starting fresh")
        except Exception as e:
            logger.error(f"Error loading synced invoices: {e}")
            self.synced_invoices = set()
    
    def _save_synced_invoices(self) -> None:
        """Save synced invoice numbers to JSON file"""
        try:
            data = {
                'synced_invoices': list(self.synced_invoices),
                'last_updated': str(os.path.getmtime(self.file_path)) if os.path.exists(self.file_path) else None
            }
            with open(self.file_path, 'w') as f:
                json.dump(data, f, indent=2)
            logger.info(f"Saved {len(self.synced_invoices)} synced invoices to {self.file_path}")
        except Exception as e:
            logger.error(f"Error saving synced invoices: {e}")
    
    def is_already_synced(self, invoice_number: str) -> bool:
        """Check if an invoice has already been synced"""
        return invoice_number in self.synced_invoices
    
    def mark_as_synced(self, invoice_number: str) -> None:
        """Mark an invoice as synced"""
        self.synced_invoices.add(invoice_number)
        self._save_synced_invoices()
    
    def mark_multiple_as_synced(self, invoice_numbers: List[str]) -> None:
        """Mark multiple invoices as synced"""
        for invoice_number in invoice_numbers:
            self.synced_invoices.add(invoice_number)
        self._save_synced_invoices()
        logger.info(f"Marked {len(invoice_numbers)} invoices as synced")
    
    def get_synced_count(self) -> int:
        """Get the total number of synced invoices"""
        return len(self.synced_invoices)
    
    def cleanup_old_records(self, max_records: int = 10000) -> None:
        """Clean up old records if the file gets too large"""
        if len(self.synced_invoices) > max_records:
            # Keep only the most recent records (this is a simple implementation)
            # In production, you might want to implement a more sophisticated cleanup
            logger.warning(f"Synced invoices count ({len(self.synced_invoices)}) exceeds limit ({max_records})")
            # For now, we'll keep all records but log the warning 