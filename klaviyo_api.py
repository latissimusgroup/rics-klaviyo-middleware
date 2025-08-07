import requests
import json
import logging
from typing import Dict, List, Any, Optional
from utils import setup_logging, safe_get

# Setup logging
setup_logging()
logger = logging.getLogger(__name__)

class KlaviyoAPI:
    """Handles communication with Klaviyo API"""
    
    def __init__(self, api_key: str, list_id: str):
        self.api_key = api_key
        self.list_id = list_id
        self.base_url = "https://a.klaviyo.com/api"
        self.api_version = "2023-10-15"
        self.session = requests.Session()
        self.session.headers.update({
            'Authorization': f'Klaviyo-API-Key {api_key}',
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'revision': self.api_version
        })
    
    def _make_request(self, endpoint: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """Make HTTP request to Klaviyo API"""
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        
        try:
            logger.info(f"Making request to Klaviyo API: {url}")
            response = self.session.post(url, json=data, timeout=30)
            
            # Log response status
            logger.info(f"Klaviyo API response status: {response.status_code}")
            
            # Handle 202 Accepted (asynchronous processing)
            if response.status_code == 202:
                logger.info("Klaviyo API request accepted (202) - event will be processed asynchronously")
                return {"status": "accepted", "message": "Event queued for processing"}
            
            # Handle other successful status codes
            if response.status_code in [200, 201]:
                try:
                    result = response.json()
                    logger.info(f"Klaviyo API response received successfully")
                    return result
                except json.JSONDecodeError:
                    logger.info("Klaviyo API returned empty response (expected for 202)")
                    return {"status": "success", "message": "Event processed"}
            
            # Handle errors
            response.raise_for_status()
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Klaviyo API request failed: {e}")
            if hasattr(e, 'response') and e.response is not None:
                logger.error(f"Response status: {e.response.status_code}")
                logger.error(f"Response body: {e.response.text}")
            raise
    
    def send_purchase_event(self, event_data: Dict[str, Any]) -> bool:
        """Send a purchase event to Klaviyo"""
        try:
            # Format the event for Klaviyo API with correct structure
            klaviyo_event = {
                "data": {
                    "type": "event",
                    "attributes": {
                        "properties": event_data.get('properties', {}),
                        "time": event_data.get('properties', {}).get('Timestamp'),
                        "value": event_data.get('properties', {}).get('Value', 0),
                        "unique_id": event_data.get('event_id'),
                        "metric": {
                            "data": {
                                "type": "metric",
                                "attributes": {
                                    "name": "Purchase"
                                }
                            }
                        },
                        "profile": {
                            "data": {
                                "type": "profile",
                                "attributes": {
                                    "email": event_data.get('profile', {}).get('email', 'unknown')
                                }
                            }
                        }
                    }
                }
            }
            
            result = self._make_request('/events/', klaviyo_event)
            logger.info(f"Successfully sent purchase event for invoice: {event_data.get('event_id')}")
            return True
            
        except Exception as e:
            logger.error(f"Error sending purchase event to Klaviyo: {e}")
            return False
    
    def send_purchase_item_event(self, event_data: Dict[str, Any]) -> bool:
        """Send a purchase item event to Klaviyo"""
        try:
            # Format the event for Klaviyo API with correct structure
            klaviyo_event = {
                "data": {
                    "type": "event",
                    "attributes": {
                        "properties": event_data.get('properties', {}),
                        "time": event_data.get('properties', {}).get('Timestamp'),
                        "value": event_data.get('properties', {}).get('Value', 0),
                        "unique_id": f"{event_data.get('event_id')}_item",
                        "metric": {
                            "data": {
                                "type": "metric",
                                "attributes": {
                                    "name": "Purchase Item"
                                }
                            }
                        },
                        "profile": {
                            "data": {
                                "type": "profile",
                                "attributes": {
                                    "email": event_data.get('profile', {}).get('email', 'unknown')
                                }
                            }
                        }
                    }
                }
            }
            
            result = self._make_request('/events/', klaviyo_event)
            logger.info(f"Successfully sent purchase item event for invoice: {event_data.get('event_id')}")
            return True
            
        except Exception as e:
            logger.error(f"Error sending purchase item event to Klaviyo: {e}")
            return False
    
    def send_multiple_events(self, events: List[Dict[str, Any]], event_type: str = "Purchase") -> Dict[str, int]:
        """Send multiple events to Klaviyo and return success/failure counts"""
        success_count = 0
        failure_count = 0
        
        for event in events:
            try:
                if event_type == "Purchase":
                    success = self.send_purchase_event(event)
                elif event_type == "Purchase Item":
                    success = self.send_purchase_item_event(event)
                else:
                    logger.warning(f"Unknown event type: {event_type}")
                    failure_count += 1
                    continue
                
                if success:
                    success_count += 1
                else:
                    failure_count += 1
                    
            except Exception as e:
                logger.error(f"Error sending event {event.get('event_id', 'unknown')}: {e}")
                failure_count += 1
        
        logger.info(f"Sent {success_count} successful {event_type} events, {failure_count} failures")
        return {
            'success_count': success_count,
            'failure_count': failure_count,
            'total_count': len(events)
        }
    
    def add_profile_to_list(self, email: str, properties: Optional[Dict[str, Any]] = None) -> bool:
        """Add a profile to the specified Klaviyo list"""
        try:
            # First, create or get the profile
            profile_data = {
                "data": {
                    "type": "profile",
                    "attributes": {
                        "email": email
                    }
                }
            }
            
            # Add properties if provided
            if properties:
                profile_data["data"]["attributes"]["properties"] = properties
            
            # Create/update profile first
            profile_response = self.session.post(f"{self.base_url}/profiles/", json=profile_data, timeout=30)
            
            profile_id = None
            
            if profile_response.status_code in [200, 201, 202]:
                # Profile created successfully
                try:
                    profile_result = profile_response.json()
                    if profile_result.get('data', {}).get('id'):
                        profile_id = profile_result['data']['id']
                        logger.info(f"Got profile ID from creation response: {profile_id}")
                except Exception as e:
                    logger.error(f"Error parsing profile creation response: {e}")
                    
            elif profile_response.status_code == 409:
                # Profile already exists - get ID from conflict response
                try:
                    conflict_result = profile_response.json()
                    if conflict_result.get('errors') and len(conflict_result['errors']) > 0:
                        duplicate_profile_id = conflict_result['errors'][0].get('meta', {}).get('duplicate_profile_id')
                        if duplicate_profile_id:
                            profile_id = duplicate_profile_id
                            logger.info(f"Got profile ID from conflict response: {profile_id}")
                        else:
                            # Fallback: try to get profile by email
                            profile_id = self._get_profile_id_by_email(email)
                    else:
                        profile_id = self._get_profile_id_by_email(email)
                except Exception as e:
                    logger.error(f"Error parsing conflict response: {e}")
                    profile_id = self._get_profile_id_by_email(email)
            else:
                logger.error(f"Failed to create profile: {profile_response.status_code} - {profile_response.text}")
                return False
            
            # If we still don't have a profile ID, try to get it by email
            if not profile_id:
                profile_id = self._get_profile_id_by_email(email)
            
            if not profile_id:
                logger.error(f"Could not get profile ID for email: {email}")
                return False
            
            # Now add the profile to the list using the correct relationship format
            list_relationship_data = {
                "data": [
                    {
                        "type": "profile",
                        "id": profile_id  # Use the actual profile ID
                    }
                ]
            }
            
            # Add profile to list
            url = f"{self.base_url}/lists/{self.list_id}/relationships/profiles/"
            response = self.session.post(url, json=list_relationship_data, timeout=30)
            
            if response.status_code in [200, 201, 202, 204]:
                logger.info(f"Successfully added profile {email} (ID: {profile_id}) to list {self.list_id}")
                return True
            else:
                logger.error(f"Failed to add profile to list: {response.status_code} - {response.text}")
                return False
                
        except Exception as e:
            logger.error(f"Error adding profile to list: {e}")
            return False
    
    def _get_profile_id_by_email(self, email: str) -> Optional[str]:
        """Get profile ID by email address"""
        try:
            profile_get_response = self.session.get(
                f"{self.base_url}/profiles/?filter=equals(email,\"{email}\")",
                timeout=30
            )
            if profile_get_response.status_code == 200:
                profile_data = profile_get_response.json()
                if profile_data.get('data') and len(profile_data['data']) > 0:
                    profile_id = profile_data['data'][0]['id']
                    logger.info(f"Got profile ID from lookup: {profile_id}")
                    return profile_id
        except Exception as e:
            logger.error(f"Error getting profile ID by email: {e}")
        return None
    
    def test_connection(self) -> bool:
        """Test the connection to Klaviyo API"""
        try:
            # Make a simple request to test the connection
            test_data = {
                "data": {
                    "type": "event",
                    "attributes": {
                        "properties": {"test": True},
                        "time": "2023-01-01T00:00:00Z",
                        "value": 0,
                        "metric": {
                            "data": {
                                "type": "metric",
                                "attributes": {
                                    "name": "Test"
                                }
                            }
                        },
                        "profile": {
                            "data": {
                                "type": "profile",
                                "attributes": {
                                    "email": "test@example.com"
                                }
                            }
                        },
                        "unique_id": "test_connection"
                    }
                }
            }
            
            self._make_request('/events/', test_data)
            logger.info("Klaviyo API connection test successful")
            return True
            
        except Exception as e:
            logger.error(f"Klaviyo API connection test failed: {e}")
            return False 