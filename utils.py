import os
import logging
import json
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, Union
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

def setup_logging(log_level: str = "INFO") -> None:
    """Setup logging configuration"""
    logging.basicConfig(
        level=getattr(logging, log_level.upper()),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler('logs/sync.log')
        ]
    )

def get_date_range(lookback_days: int = 7) -> tuple[datetime, datetime]:
    """Get date range for sync (from X days ago to today)"""
    end_date = datetime.now()
    start_date = end_date - timedelta(days=lookback_days)
    return start_date, end_date

def format_timestamp(dt: Union[datetime, str]) -> str:
    """Format datetime or date string to ISO 8601 format with 'Z'"""
    if isinstance(dt, str):
        # Handle date strings like "YYYY-MM-DD" or "YYYY-MM-DDTHH:MM:SS"
        try:
            # Try parsing as datetime first
            if 'T' in dt:
                dt = datetime.fromisoformat(dt.replace('Z', '+00:00'))
            else:
                # Parse as date only
                dt = datetime.strptime(dt, "%Y-%m-%d")
        except ValueError:
            raise ValueError(f"Invalid date format: {dt}")
    
    # Ensure it's a datetime object
    if not isinstance(dt, datetime):
        raise ValueError(f"Expected datetime or date string, got {type(dt)}")
    
    # Format to ISO 8601 with 'Z'
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")

def format_currency(amount: float) -> str:
    """Format amount as currency"""
    return f"${amount:.2f}"

def validate_email(email: str) -> bool:
    """Basic email validation"""
    if not email or '@' not in email:
        return False
    return True

def safe_get(data: Dict[str, Any], key: str, default: Any = None) -> Any:
    """Safely get value from nested dictionary"""
    keys = key.split('.')
    value = data
    
    for k in keys:
        if isinstance(value, dict) and k in value:
            value = value[k]
        else:
            return default
    
    return value

def load_config() -> Dict[str, Any]:
    """Load configuration from environment variables"""
    config = {
        'RICS_API_KEY': os.getenv('RICS_API_KEY'),
        'RICS_API_URL': os.getenv('RICS_API_URL'),
        'RICS_STORE_CODE': os.getenv('RICS_STORE_CODE'),
        'KLAVIYO_API_KEY': os.getenv('KLAVIYO_API_KEY'),
        'KLAVIYO_LIST_ID': os.getenv('KLAVIYO_LIST_ID'),
        'LOOKBACK_DAYS': int(os.getenv('LOOKBACK_DAYS', '7')),
        'LOG_LEVEL': os.getenv('LOG_LEVEL', 'INFO'),
        'AWS_REGION': os.getenv('AWS_REGION', 'us-east-1')
    }
    
    # Validate required fields
    required_fields = ['RICS_API_KEY', 'RICS_API_URL', 'RICS_STORE_CODE', 'KLAVIYO_API_KEY', 'KLAVIYO_LIST_ID']
    missing_fields = [field for field in required_fields if not config[field]]
    
    if missing_fields:
        raise ValueError(f"Missing required environment variables: {', '.join(missing_fields)}")
    
    return config 