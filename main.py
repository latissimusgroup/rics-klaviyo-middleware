import os
import json
import logging
from datetime import datetime
from typing import Dict, List, Any
from utils import setup_logging, load_config, get_date_range
from rics_api import RICSAPI
from klaviyo_api import KlaviyoAPI
from deduplication import DeduplicationManager

# Setup logging
setup_logging()
logger = logging.getLogger(__name__)

class RICSKlaviyoSync:
    """Main sync orchestration class"""
    
    def __init__(self):
        self.config = load_config()
        self.rics_api = RICSAPI(
            api_key=self.config['RICS_API_KEY'],
            api_url=self.config['RICS_API_URL'],
            store_code=self.config['RICS_STORE_CODE']
        )
        self.klaviyo_api = KlaviyoAPI(
            api_key=self.config['KLAVIYO_API_KEY'],
            list_id=self.config['KLAVIYO_LIST_ID']
        )
        self.deduplication = DeduplicationManager()
        self.lookback_days = self.config.get('LOOKBACK_DAYS', 7)
    
    def sync_sales_and_purchases(self, from_date: datetime = None, to_date: datetime = None) -> Dict[str, Any]:
        """Main sync function that orchestrates the entire process"""
        try:
            # Determine date range
            if from_date is None or to_date is None:
                from_date, to_date = get_date_range(self.lookback_days)
            
            logger.info(f"Starting sync for period: {from_date} to {to_date}")
            
            # Fetch data from RICS
            sales = self.rics_api.get_sales(from_date, to_date)
            
            # Try to fetch purchases (may fail due to permissions)
            purchases = []
            try:
                purchases = self.rics_api.get_purchases(from_date, to_date)
                logger.info(f"Successfully fetched {len(purchases)} purchases")
            except Exception as e:
                logger.warning(f"Purchase API failed (likely permissions issue): {e}")
                logger.info("Continuing with sales sync only")
            
            total_records = len(sales) + len(purchases)
            if total_records == 0:
                logger.info("No sales or purchases found for the period.")
                return {
                    'status': 'success',
                    'message': 'No sales or purchases found for the period.',
                    'sales_synced': 0,
                    'purchases_synced': 0,
                    'duplicates_skipped': 0
                }
            
            logger.info(f"Found {len(sales)} sales and {len(purchases)} purchases")
            
            # Process sales
            sales_results = self._process_sales(sales)
            
            # Process purchases (if available)
            purchases_results = {'synced_count': 0, 'duplicate_count': 0}
            if purchases:
                purchases_results = self._process_purchases(purchases)
            
            # Summary
            total_synced = sales_results['synced_count'] + purchases_results['synced_count']
            total_duplicates = sales_results['duplicate_count'] + purchases_results['duplicate_count']
            total_profiles_added = sales_results.get('profiles_added', 0)
            
            logger.info(f"Sync completed. Synced: {total_synced}, Duplicates skipped: {total_duplicates}, Profiles added: {total_profiles_added}")
            
            return {
                'status': 'success',
                'sales_synced': sales_results['synced_count'],
                'purchases_synced': purchases_results['synced_count'],
                'duplicates_skipped': total_duplicates,
                'profiles_added': total_profiles_added,
                'total_processed': total_records,
                'period': {
                    'from_date': from_date.isoformat(),
                    'to_date': to_date.isoformat()
                }
            }
            
        except Exception as e:
            logger.error(f"Sync failed: {e}")
            return {
                'status': 'error',
                'message': str(e),
                'sales_synced': 0,
                'purchases_synced': 0,
                'duplicates_skipped': 0
            }
    
    def _process_sales(self, sales: List[Dict[str, Any]]) -> Dict[str, int]:
        """Process sales data and send to Klaviyo"""
        new_sales = []
        duplicate_count = 0
        profiles_added = 0
        
        for sale in sales:
            invoice_number = sale.get('TicketNumber')
            if not invoice_number:
                logger.warning("Sale missing TicketNumber, skipping")
                continue
            
            if self.deduplication.is_already_synced(invoice_number):
                logger.info(f"Skipping duplicate sale: {invoice_number}")
                duplicate_count += 1
                continue
            
            # Format for Klaviyo
            klaviyo_event = self.rics_api.format_sale_for_klaviyo(sale)
            new_sales.append(klaviyo_event)
        
        if not new_sales:
            logger.info("No new sales to sync")
            return {'synced_count': 0, 'duplicate_count': duplicate_count, 'profiles_added': 0}
        
        # Send to Klaviyo
        results = self.klaviyo_api.send_multiple_events(new_sales, "Purchase")
        
        # Mark successful events as synced and add profiles to list
        if results['success_count'] > 0:
            successful_invoices = [
                sale.get('TicketNumber') for sale in sales 
                if not self.deduplication.is_already_synced(sale.get('TicketNumber'))
            ][:results['success_count']]
            self.deduplication.mark_multiple_as_synced(successful_invoices)
            
            # Add profiles to list for successful sales
            for sale in sales[:results['success_count']]:
                customer_email = sale.get('Customer', {}).get('Email')
                if customer_email and '@' in customer_email:
                    # Add customer profile to list
                    profile_properties = {
                        'First Name': sale.get('Customer', {}).get('FirstName', ''),
                        'Last Name': sale.get('Customer', {}).get('LastName', ''),
                        'Phone': sale.get('Customer', {}).get('Phone', ''),
                        'Store Code': sale.get('StoreCode', ''),
                        'Customer Since': sale.get('TicketDateTime', '')
                    }
                    
                    if self.klaviyo_api.add_profile_to_list(customer_email, profile_properties):
                        profiles_added += 1
                        logger.info(f"Added profile {customer_email} to list")
                    else:
                        logger.warning(f"Failed to add profile {customer_email} to list")
        
        return {
            'synced_count': results['success_count'],
            'duplicate_count': duplicate_count,
            'profiles_added': profiles_added
        }
    
    def _process_purchases(self, purchases: List[Dict[str, Any]]) -> Dict[str, int]:
        """Process purchase data and send to Klaviyo"""
        new_purchases = []
        duplicate_count = 0
        
        for purchase in purchases:
            invoice_number = purchase.get('PurchaseOrderNumber')
            if not invoice_number:
                logger.warning("Purchase missing PurchaseOrderNumber, skipping")
                continue
            
            if self.deduplication.is_already_synced(invoice_number):
                logger.info(f"Skipping duplicate purchase: {invoice_number}")
                duplicate_count += 1
                continue
            
            # Format for Klaviyo
            klaviyo_event = self.rics_api.format_purchase_for_klaviyo(purchase)
            new_purchases.append(klaviyo_event)
        
        if not new_purchases:
            logger.info("No new purchases to sync")
            return {'synced_count': 0, 'duplicate_count': duplicate_count}
        
        # Send to Klaviyo
        results = self.klaviyo_api.send_multiple_events(new_purchases, "Purchase")
        
        # Mark successful events as synced
        if results['success_count'] > 0:
            successful_invoices = [
                purchase.get('PurchaseOrderNumber') for purchase in purchases 
                if not self.deduplication.is_already_synced(purchase.get('PurchaseOrderNumber'))
            ][:results['success_count']]
            self.deduplication.mark_multiple_as_synced(successful_invoices)
        
        return {
            'synced_count': results['success_count'],
            'duplicate_count': duplicate_count
        }
    
    def test_connections(self) -> Dict[str, bool]:
        """Test connections to both APIs"""
        results = {}
        
        # Test RICS API
        try:
            from_date, to_date = get_date_range(1)
            test_sales = self.rics_api.get_sales(from_date, to_date)
            results['rics_api'] = True
            logger.info("RICS API connection test successful")
        except Exception as e:
            results['rics_api'] = False
            logger.error(f"RICS API connection test failed: {e}")
        
        # Test Klaviyo API
        try:
            results['klaviyo_api'] = self.klaviyo_api.test_connection()
        except Exception as e:
            results['klaviyo_api'] = False
            logger.error(f"Klaviyo API connection test failed: {e}")
        
        return results

def lambda_handler(event, context):
    """AWS Lambda handler function"""
    try:
        logger.info("Lambda function started")
        
        # Initialize sync
        sync = RICSKlaviyoSync()
        
        # Run sync
        result = sync.sync_sales_and_purchases()
        
        logger.info(f"Lambda function completed: {result}")
        return {
            'statusCode': 200 if result['status'] == 'success' else 500,
            'body': json.dumps(result)
        }
        
    except Exception as e:
        logger.error(f"Lambda function failed: {e}")
        return {
            'statusCode': 500,
            'body': json.dumps({
                'status': 'error',
                'message': str(e)
            })
        }

def main():
    """Main function for local testing"""
    try:
        logger.info("Starting RICS to Klaviyo sync")
        
        # Initialize sync
        sync = RICSKlaviyoSync()
        
        # Test connections
        connection_results = sync.test_connections()
        if not all(connection_results.values()):
            logger.error("API connection tests failed")
            return
        
        # Run sync
        result = sync.sync_sales_and_purchases()
        
        if result['status'] == 'success':
            logger.info("Sync completed successfully")
        else:
            logger.error(f"Sync failed: {result.get('message', 'Unknown error')}")
        
    except Exception as e:
        logger.error(f"Main function failed: {e}")

if __name__ == "__main__":
    main() 