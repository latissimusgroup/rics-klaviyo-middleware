import requests
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from utils import format_timestamp, format_currency, safe_get, validate_email

logger = logging.getLogger(__name__)

class RICSAPI:
    """Handles all interactions with the RICS API"""
    
    def __init__(self, api_key: str, api_url: str, store_code: str):
        self.api_key = api_key
        self.api_url = api_url
        self.store_code = store_code
        self.session = requests.Session()
        self.session.headers.update({
            'Token': api_key,
            'Content-Type': 'application/json'
        })
    
    def _make_request(self, endpoint: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Make a POST request to the RICS API"""
        url = f"{self.api_url.rstrip('/')}{endpoint}"
        
        try:
            logger.info(f"Making request to: {url}")
            logger.debug(f"Parameters: {params}")
            
            response = self.session.post(url, json=params, timeout=30)
            
            logger.info(f"Response status: {response.status_code}")
            
            if response.status_code == 200:
                return response.json()
            else:
                logger.error(f"RICS API request failed with status {response.status_code}")
                logger.error(f"Response: {response.text}")
                raise Exception(f"RICS API request failed with status {response.status_code}")
                
        except requests.exceptions.RequestException as e:
            logger.error(f"Network error calling RICS API: {str(e)}")
            raise
    
    def get_sales(self, start_date: datetime, end_date: datetime) -> List[Dict[str, Any]]:
        """Fetch sales transactions from RICS API"""
        logger.info(f"Fetching sales from {start_date} to {end_date}")
        
        params = {
            "BatchStartDate": start_date.strftime("%Y-%m-%d"),
            "BatchEndDate": end_date.strftime("%Y-%m-%d"),
            "TicketDateStart": start_date.strftime("%Y-%m-%d"),
            "TicketDateEnd": end_date.strftime("%Y-%m-%d"),
            "StoreCode": int(self.store_code),
            "Skip": 0,
            "Take": 100
        }
        
        try:
            response = self._make_request("/POS/GetPOSTransaction", params)
            
            if not response.get("IsSuccessful", False):
                logger.error(f"RICS API returned unsuccessful response: {response.get('Message', 'Unknown error')}")
                return []
            
            sales_data = response.get("Sales", [])
            logger.info(f"Retrieved {len(sales_data)} sales batches")
            
            # Extract all sale headers from all batches
            all_sales = []
            for batch in sales_data:
                sale_headers = batch.get("SaleHeaders", [])
                for sale in sale_headers:
                    if self._validate_sale_data(sale):
                        all_sales.append(sale)
            
            logger.info(f"Validated {len(all_sales)} sales transactions")
            return all_sales
            
        except Exception as e:
            logger.error(f"Error fetching sales from RICS API: {str(e)}")
            return []
    
    def get_purchases(self, start_date: datetime, end_date: datetime) -> List[Dict[str, Any]]:
        """Fetch purchase orders from RICS API"""
        logger.info(f"Fetching purchases from {start_date} to {end_date}")
        
        # Purchase order API parameters - simplified approach
        params = {
            "BillToStoreCode": int(self.store_code),
            "Skip": 0,
            "Take": 100
        }
        
        try:
            response = self._make_request("/PurchaseOrder/GetPurchaseOrder", params)
            
            if not response.get("IsSuccessful", False):
                logger.warning(f"Purchase API returned unsuccessful response: {response.get('Message', 'Unknown error')}")
                logger.info("This may indicate no purchase data exists or API requires different parameters")
                return []
            
            purchases_data = response.get("PurchaseOrders", [])
            logger.info(f"Retrieved {len(purchases_data)} purchase orders")
            
            # Filter purchase orders by date range
            filtered_purchases = []
            for purchase in purchases_data:
                ordered_on = safe_get(purchase, "OrderedOn")
                if ordered_on and ordered_on != "0001-01-01":
                    try:
                        # Parse the date string
                        purchase_date = datetime.strptime(ordered_on.split('T')[0], "%Y-%m-%d")
                        if start_date <= purchase_date <= end_date:
                            if self._validate_purchase_data(purchase):
                                filtered_purchases.append(purchase)
                    except (ValueError, TypeError) as e:
                        logger.warning(f"Could not parse purchase date '{ordered_on}': {str(e)}")
                        continue
            
            logger.info(f"Filtered to {len(filtered_purchases)} purchase orders in date range")
            return filtered_purchases
            
        except Exception as e:
            logger.error(f"Error fetching purchases from RICS API: {str(e)}")
            return []
    
    def _validate_sale_data(self, sale: Dict[str, Any]) -> bool:
        """Validate sale data has required fields"""
        try:
            # Check required fields
            ticket_number = safe_get(sale, "TicketNumber")
            if not ticket_number:
                logger.warning("Sale missing TicketNumber")
                return False
            
            # Check if customer has email
            customer = safe_get(sale, "Customer", {})
            customer_email = safe_get(customer, "Email", "").strip()
            if not customer_email or not validate_email(customer_email):
                logger.warning(f"Sale {ticket_number} missing valid customer email")
                return False
            
            # Check if sale has details
            sale_details = safe_get(sale, "SaleDetails", [])
            if not sale_details:
                logger.warning(f"Sale {ticket_number} has no sale details")
                return False
            
            # Check if sale has tenders (payment info)
            tenders = safe_get(sale, "Tenders", [])
            if not tenders:
                logger.warning(f"Sale {ticket_number} has no tender information")
                return False
            
            # Calculate total from sale details
            total_amount = sum(
                safe_get(detail, "AmountPaid", 0) 
                for detail in sale_details
            )
            
            if total_amount <= 0:
                logger.warning(f"Sale {ticket_number} has zero or negative total amount")
                return False
            
            return True
            
        except Exception as e:
            logger.error(f"Error validating sale data: {str(e)}")
            return False
    
    def _validate_purchase_data(self, purchase: Dict[str, Any]) -> bool:
        """Validate purchase data has required fields"""
        try:
            # Check required fields
            purchase_order_number = safe_get(purchase, "PurchaseOrderNumber")
            if not purchase_order_number:
                logger.warning("Purchase missing PurchaseOrderNumber")
                return False
            
            # Check if purchase has details
            details = safe_get(purchase, "Details", [])
            if not details:
                logger.warning(f"Purchase {purchase_order_number} has no details")
                return False
            
            # Calculate total cost from details
            total_cost = sum(
                safe_get(detail, "Cost", 0) * safe_get(detail, "OrderQuantity", 0)
                for detail in details
            )
            
            if total_cost <= 0:
                logger.warning(f"Purchase {purchase_order_number} has zero or negative total cost")
                return False
            
            return True
            
        except Exception as e:
            logger.error(f"Error validating purchase data: {str(e)}")
            return False
    
    def format_sale_for_klaviyo(self, sale: Dict[str, Any]) -> Dict[str, Any]:
        """Format RICS sale data for Klaviyo event"""
        try:
            ticket_number = safe_get(sale, "TicketNumber")
            customer = safe_get(sale, "Customer", {})
            sale_details = safe_get(sale, "SaleDetails", [])
            tenders = safe_get(sale, "Tenders", [])
            
            # Get customer email
            customer_email = safe_get(customer, "Email", "").strip()
            
            # Calculate total amount from sale details
            total_amount = sum(
                safe_get(detail, "AmountPaid", 0) 
                for detail in sale_details
            )
            
            # Get products information
            products = []
            for detail in sale_details:
                product = safe_get(detail, "ProductItem", {})
                sku = safe_get(product, "Sku", "")
                summary = safe_get(product, "Summary", "")
                quantity = safe_get(detail, "Quantity", 0)
                
                if sku and summary:
                    products.append(f"{summary} (SKU: {sku}, Qty: {quantity})")
            
            # Get payment method from tenders
            payment_method = "Unknown"
            if tenders:
                tender = tenders[0]
                payment_method = safe_get(tender, "TenderDescription", "Unknown")
            
            # Format timestamp
            ticket_datetime = safe_get(sale, "TicketDateTime")
            if ticket_datetime and ticket_datetime != "0001-01-01":
                timestamp = format_timestamp(ticket_datetime)
            else:
                timestamp = datetime.now().isoformat()
            
            return {
                "event_id": f"RICS_SALE_{ticket_number}",
                "profile": {
                    "email": customer_email
                },
                "properties": {
                    "InvoiceNumber": str(ticket_number),
                    "Products": "; ".join(products) if products else "Unknown Product",
                    "Value": format_currency(total_amount),
                    "PaymentMethod": payment_method,
                    "StoreCode": safe_get(sale, "StoreCode", ""),
                    "Timestamp": timestamp,
                    "CustomerName": f"{safe_get(customer, 'FirstName', '')} {safe_get(customer, 'LastName', '')}".strip(),
                    "CustomerPhone": safe_get(customer, "PhoneNumber", ""),
                    "SaleType": safe_get(sale, "SaleType", ""),
                    "PromotionCode": safe_get(sale, "PromotionCode", ""),
                    "TicketComment": safe_get(sale, "TicketComment", "")
                }
            }
            
        except Exception as e:
            logger.error(f"Error formatting sale for Klaviyo: {str(e)}")
            return {}
    
    def format_purchase_for_klaviyo(self, purchase: Dict[str, Any]) -> Dict[str, Any]:
        """Format RICS purchase data for Klaviyo event"""
        try:
            purchase_order_number = safe_get(purchase, "PurchaseOrderNumber")
            details = safe_get(purchase, "Details", [])
            
            # Calculate total cost from details
            total_cost = sum(
                safe_get(detail, "Cost", 0) * safe_get(detail, "OrderQuantity", 0)
                for detail in details
            )
            
            # Get products information
            products = []
            for detail in details:
                product_item = safe_get(detail, "ProductItem", {})
                sku = safe_get(product_item, "Sku", "")
                summary = safe_get(product_item, "Summary", "")
                quantity = safe_get(detail, "OrderQuantity", 0)
                
                if sku and summary:
                    products.append(f"{summary} (SKU: {sku}, Qty: {quantity})")
            
            # Format timestamp
            ordered_on = safe_get(purchase, "OrderedOn")
            if ordered_on and ordered_on != "0001-01-01":
                timestamp = format_timestamp(ordered_on)
            else:
                timestamp = datetime.now().isoformat()
            
            return {
                "event_id": f"RICS_PURCHASE_{purchase_order_number}",
                "profile": {
                    "email": "admin@store.com"  # Default email for purchase events
                },
                "properties": {
                    "InvoiceNumber": str(purchase_order_number),
                    "Products": "; ".join(products) if products else "Unknown Product",
                    "Value": format_currency(total_cost),
                    "StoreCode": safe_get(purchase, "BillToStoreCode", ""),
                    "Timestamp": timestamp,
                    "SupplierCode": safe_get(purchase, "SupplierCode", ""),
                    "SupplierName": safe_get(purchase, "SupplierName", ""),
                    "PurchaseOrderType": safe_get(purchase, "PurchaseOrderType", ""),
                    "ConfirmationNumber": safe_get(purchase, "ConfirmationNumber", ""),
                    "Terms": safe_get(purchase, "Terms", ""),
                    "ShipVia": safe_get(purchase, "ShipVia", ""),
                    "CustomerOrderNumber": safe_get(purchase, "CustomerOrderNumber", "")
                }
            }
            
        except Exception as e:
            logger.error(f"Error formatting purchase for Klaviyo: {str(e)}")
            return {} 