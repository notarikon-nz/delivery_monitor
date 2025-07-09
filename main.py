#!/usr/bin/env python3
"""
Gmail Parcel Tracker

A comprehensive parcel tracking system that monitors Gmail for shipping notifications
and tracks package status through various courier APIs.

Features:
- Gmail API integration for email monitoring
- Multi-courier tracking support
- Terminal-based status display
- Configurable polling intervals
- Persistent parcel database
- Error handling and logging
"""

import yaml
import json
import sqlite3
import re
import time
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict
from pathlib import Path
from contextlib import contextmanager
import threading
from abc import ABC, abstractmethod

# Gmail API imports
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# HTTP requests for courier APIs
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


# Configuration and Data Models
@dataclass
class ParcelInfo:
    """Data model for parcel information"""
    tracking_number: str
    courier: str
    company: str
    status: str
    eta: Optional[str] = None
    last_updated: Optional[datetime] = None
    email_subject: Optional[str] = None
    created_at: Optional[datetime] = None

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now()
        if self.last_updated is None:
            self.last_updated = datetime.now()


@dataclass
class Config:
    """Configuration data model"""
    gmail_credentials_path: str
    gmail_token_path: str
    email_address: str
    check_interval_minutes: int
    database_path: str
    log_level: str
    max_emails_per_check: int
    courier_apis: Dict[str, str]
    email_search_query: Optional[str] = None
    terminal_refresh_seconds: int = 30
    max_display_parcels: int = 20

    @classmethod
    def from_yaml(cls, config_path: str) -> 'Config':
        """Load configuration from YAML file"""
        with open(config_path, 'r') as f:
            data = yaml.safe_load(f)
        
        # Handle optional fields with defaults
        if 'email_search_query' not in data:
            data['email_search_query'] = None
        if 'terminal_refresh_seconds' not in data:
            data['terminal_refresh_seconds'] = 30
        if 'max_display_parcels' not in data:
            data['max_display_parcels'] = 20
            
        return cls(**data)


# Courier Tracking Strategy Pattern
class CourierTracker(ABC):
    """Abstract base class for courier tracking implementations"""
    
    @abstractmethod
    def track_parcel(self, tracking_number: str) -> Tuple[str, Optional[str]]:
        """
        Track a parcel and return (status, eta)
        Returns ("unknown", None) if tracking fails
        """
        pass

    @abstractmethod
    def can_handle(self, tracking_number: str, company: str) -> bool:
        """Check if this tracker can handle the given tracking number/company"""
        pass


class FedExTracker(CourierTracker):
    """FedEx tracking implementation"""
    
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.session = self._create_session()
    
    def _create_session(self) -> requests.Session:
        """Create HTTP session with retry strategy"""
        session = requests.Session()
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        return session
    
    def can_handle(self, tracking_number: str, company: str) -> bool:
        """Check if this is a FedEx tracking number"""
        fedex_patterns = [
            r'^[0-9]{12}$',  # FedEx Express
            r'^[0-9]{14}$',  # FedEx Ground
            r'^[0-9]{20}$',  # FedEx Ground 96
        ]
        return (any(re.match(pattern, tracking_number) for pattern in fedex_patterns) or 
                'fedex' in company.lower())
    
    def track_parcel(self, tracking_number: str) -> Tuple[str, Optional[str]]:
        """Track FedEx parcel"""
        try:
            # Note: This is a simplified example. Real FedEx API requires authentication
            # and has a more complex request structure
            response = self.session.get(
                f"https://api.fedex.com/track/v1/trackingnumbers",
                params={"trackingNumber": tracking_number},
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                # Parse FedEx response (simplified)
                status = data.get('status', 'unknown')
                eta = data.get('estimatedDeliveryDate')
                return status, eta
            else:
                logging.warning(f"FedEx API returned status {response.status_code}")
                return "unknown", None
                
        except Exception as e:
            logging.error(f"Error tracking FedEx parcel {tracking_number}: {e}")
            return "unknown", None


class UPSTracker(CourierTracker):
    """UPS tracking implementation"""
    
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.session = self._create_session()
    
    def _create_session(self) -> requests.Session:
        session = requests.Session()
        retry_strategy = Retry(total=3, backoff_factor=1)
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        return session
    
    def can_handle(self, tracking_number: str, company: str) -> bool:
        """Check if this is a UPS tracking number"""
        ups_patterns = [
            r'^1Z[0-9A-Z]{16}$',  # UPS standard
            r'^[0-9]{18}$',       # UPS Mail Innovations
        ]
        return (any(re.match(pattern, tracking_number) for pattern in ups_patterns) or 
                'ups' in company.lower())
    
    def track_parcel(self, tracking_number: str) -> Tuple[str, Optional[str]]:
        """Track UPS parcel"""
        try:
            # Simplified UPS API call
            response = self.session.get(
                f"https://onlinetools.ups.com/track/v1/details/{tracking_number}",
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                status = data.get('status', 'unknown')
                eta = data.get('estimatedDeliveryDate')
                return status, eta
            else:
                return "unknown", None
                
        except Exception as e:
            logging.error(f"Error tracking UPS parcel {tracking_number}: {e}")
            return "unknown", None


class GenericTracker(CourierTracker):
    """Generic/fallback tracker for unknown couriers"""
    
    def can_handle(self, tracking_number: str, company: str) -> bool:
        """Generic tracker handles everything as fallback"""
        return True
    
    def track_parcel(self, tracking_number: str) -> Tuple[str, Optional[str]]:
        """Generic tracking (placeholder)"""
        return "pending", None


# Factory for courier trackers
class CourierTrackerFactory:
    """Factory for creating appropriate courier trackers"""
    
    def __init__(self, courier_apis: Dict[str, str]):
        self.trackers = [
            FedExTracker(courier_apis.get('fedex', '')),
            UPSTracker(courier_apis.get('ups', '')),
            GenericTracker()  # Always last as fallback
        ]
    
    def get_tracker(self, tracking_number: str, company: str) -> CourierTracker:
        """Get appropriate tracker for tracking number and company"""
        for tracker in self.trackers:
            if tracker.can_handle(tracking_number, company):
                return tracker
        return self.trackers[-1]  # Return generic tracker as fallback


# Database Manager
class DatabaseManager:
    """Manages SQLite database operations for parcel storage"""
    
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._init_database()
    
    def _init_database(self):
        """Initialize database with required tables"""
        with self._get_connection() as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS parcels (
                    tracking_number TEXT PRIMARY KEY,
                    courier TEXT NOT NULL,
                    company TEXT NOT NULL,
                    status TEXT NOT NULL,
                    eta TEXT,
                    last_updated TIMESTAMP,
                    email_subject TEXT,
                    created_at TIMESTAMP
                )
            ''')
            conn.commit()
    
    @contextmanager
    def _get_connection(self):
        """Context manager for database connections"""
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()
    
    def save_parcel(self, parcel: ParcelInfo):
        """Save or update parcel information"""
        with self._get_connection() as conn:
            conn.execute('''
                INSERT OR REPLACE INTO parcels 
                (tracking_number, courier, company, status, eta, last_updated, email_subject, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                parcel.tracking_number,
                parcel.courier,
                parcel.company,
                parcel.status,
                parcel.eta,
                parcel.last_updated,
                parcel.email_subject,
                parcel.created_at
            ))
            conn.commit()
    
    def get_all_parcels(self) -> List[ParcelInfo]:
        """Retrieve all parcels from database"""
        with self._get_connection() as conn:
            rows = conn.execute('SELECT * FROM parcels ORDER BY created_at DESC').fetchall()
            return [ParcelInfo(**dict(row)) for row in rows]
    
    def get_parcel(self, tracking_number: str) -> Optional[ParcelInfo]:
        """Retrieve specific parcel by tracking number"""
        with self._get_connection() as conn:
            row = conn.execute(
                'SELECT * FROM parcels WHERE tracking_number = ?', 
                (tracking_number,)
            ).fetchone()
            return ParcelInfo(**dict(row)) if row else None
    
    def remove_parcel(self, tracking_number: str):
        """Remove parcel from database"""
        with self._get_connection() as conn:
            conn.execute('DELETE FROM parcels WHERE tracking_number = ?', (tracking_number,))
            conn.commit()


# Gmail Integration
class GmailClient:
    """Gmail API client for reading emails"""
    
    SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']
    
    def __init__(self, credentials_path: str, token_path: str):
        self.credentials_path = credentials_path
        self.token_path = token_path
        self.service = self._authenticate()
    
    def _authenticate(self):
        """Authenticate with Gmail API"""
        creds = None
        
        # Load existing token
        if Path(self.token_path).exists():
            creds = Credentials.from_authorized_user_file(self.token_path, self.SCOPES)
        
        # If no valid credentials, get new ones
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(
                    self.credentials_path, self.SCOPES)
                
                try:
                    # Try with fixed port first
                    creds = flow.run_local_server(port=8080)
                except OSError:
                    # If port 8080 is busy, try 8081
                    try:
                        creds = flow.run_local_server(port=8081)
                    except OSError:
                        # If both ports are busy, let the system choose
                        creds = flow.run_local_server(port=0)
            
            # Save credentials for next run
            with open(self.token_path, 'w') as token:
                token.write(creds.to_json())
        
        return build('gmail', 'v1', credentials=creds)
    
    def search_emails(self, query: str, max_results: int = 10) -> List[Dict]:
        """Search emails by query"""
        try:
            results = self.service.users().messages().list(
                userId='me', q=query, maxResults=max_results).execute()
            
            messages = results.get('messages', [])
            email_data = []
            
            for message in messages:
                msg = self.service.users().messages().get(
                    userId='me', id=message['id']).execute()
                email_data.append(msg)
            
            return email_data
            
        except HttpError as error:
            logging.error(f'Gmail API error: {error}')
            return []


# Email Parser
class EmailParser:
    """Parses emails to extract tracking information"""
    
    # Common tracking number patterns
    TRACKING_PATTERNS = [
        r'\b1Z[0-9A-Z]{16}\b',  # UPS
        r'\b[0-9]{12}\b',       # FedEx Express
        r'\b[0-9]{14}\b',       # FedEx Ground
        r'\b[0-9]{20,22}\b',    # Various long formats
        r'\b[A-Z]{2}[0-9]{9}[A-Z]{2}\b',  # USPS
    ]
    
    # Company detection patterns
    COMPANY_PATTERNS = {
        'amazon': r'amazon|amzn',
        'ups': r'ups|united parcel',
        'fedex': r'fedex|federal express',
        'usps': r'usps|united states postal|post office',
        'dhl': r'dhl',
        'shopify': r'shopify',
        'ebay': r'ebay',
    }
    
    def extract_tracking_info(self, email_data: Dict) -> List[ParcelInfo]:
        """Extract tracking information from email"""
        parcels = []
        
        try:
            # Get email content
            subject = self._get_header_value(email_data, 'Subject')
            body = self._get_email_body(email_data)
            full_content = f"{subject} {body}".lower()
            
            # Find tracking numbers
            tracking_numbers = []
            for pattern in self.TRACKING_PATTERNS:
                matches = re.findall(pattern, body, re.IGNORECASE)
                tracking_numbers.extend(matches)
            
            # Detect company
            company = self._detect_company(full_content)
            
            # Create parcel info for each tracking number
            for tracking_number in tracking_numbers:
                courier = self._detect_courier(tracking_number, company)
                
                parcel = ParcelInfo(
                    tracking_number=tracking_number,
                    courier=courier,
                    company=company,
                    status="pending",
                    email_subject=subject
                )
                parcels.append(parcel)
                
        except Exception as e:
            logging.error(f"Error parsing email: {e}")
        
        return parcels
    
    def _get_header_value(self, email_data: Dict, header_name: str) -> str:
        """Extract header value from email"""
        headers = email_data.get('payload', {}).get('headers', [])
        for header in headers:
            if header.get('name') == header_name:
                return header.get('value', '')
        return ''
    
    def _get_email_body(self, email_data: Dict) -> str:
        """Extract body text from email"""
        payload = email_data.get('payload', {})
        
        # Handle multipart emails
        if 'parts' in payload:
            for part in payload['parts']:
                if part.get('mimeType') == 'text/plain':
                    data = part.get('body', {}).get('data', '')
                    if data:
                        import base64
                        return base64.urlsafe_b64decode(data).decode('utf-8')
        
        # Handle single part emails
        elif payload.get('mimeType') == 'text/plain':
            data = payload.get('body', {}).get('data', '')
            if data:
                import base64
                return base64.urlsafe_b64decode(data).decode('utf-8')
        
        return ''
    
    def _detect_company(self, content: str) -> str:
        """Detect company from email content"""
        for company, pattern in self.COMPANY_PATTERNS.items():
            if re.search(pattern, content, re.IGNORECASE):
                return company
        return 'unknown'
    
    def _detect_courier(self, tracking_number: str, company: str) -> str:
        """Detect courier from tracking number pattern"""
        if re.match(r'^1Z[0-9A-Z]{16}$', tracking_number):
            return 'UPS'
        elif re.match(r'^[0-9]{12}$', tracking_number):
            return 'FedEx'
        elif re.match(r'^[0-9]{14}$', tracking_number):
            return 'FedEx'
        elif company in ['ups']:
            return 'UPS'
        elif company in ['fedex']:
            return 'FedEx'
        else:
            return 'Unknown'


# Main Application
class ParcelTracker:
    """Main application class coordinating all components"""
    
    def __init__(self, config_path: str):
        self.config = Config.from_yaml(config_path)
        self._setup_logging()
        
        # Initialize components
        self.db_manager = DatabaseManager(self.config.database_path)
        self.gmail_client = GmailClient(
            self.config.gmail_credentials_path,
            self.config.gmail_token_path
        )
        self.email_parser = EmailParser()
        self.courier_factory = CourierTrackerFactory(self.config.courier_apis)
        
        # Threading control
        self.running = False
        self.update_thread = None
    
    def _setup_logging(self):
        """Configure logging"""
        logging.basicConfig(
            level=getattr(logging, self.config.log_level.upper()),
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler('parcel_tracker.log'),
                logging.StreamHandler()
            ]
        )
    
    def check_new_emails(self):
        """Check Gmail for new shipping emails"""
        logging.info("Checking for new shipping emails...")
        
        # Use configurable search query or default
        if self.config.email_search_query:
            query = self.config.email_search_query
        else:
            query = (
                'subject:(shipped OR tracking OR delivery OR "on its way" OR "out for delivery") '
                'OR from:(amazon.com OR ups.com OR fedex.com OR usps.com OR dhl.com)'
            )
        
        emails = self.gmail_client.search_emails(query, self.config.max_emails_per_check)
        
        new_parcels = 0
        for email in emails:
            parcels = self.email_parser.extract_tracking_info(email)
            
            for parcel in parcels:
                # Check if parcel already exists
                existing = self.db_manager.get_parcel(parcel.tracking_number)
                if not existing:
                    self.db_manager.save_parcel(parcel)
                    new_parcels += 1
                    logging.info(f"New parcel added: {parcel.tracking_number}")
        
        logging.info(f"Found {new_parcels} new parcels")
    
    def update_parcel_status(self):
        """Update status for all tracked parcels"""
        logging.info("Updating parcel statuses...")
        
        parcels = self.db_manager.get_all_parcels()
        
        for parcel in parcels:
            # Skip if recently updated (within last hour)
            if (parcel.last_updated and 
                datetime.now() - parcel.last_updated < timedelta(hours=1)):
                continue
            
            try:
                tracker = self.courier_factory.get_tracker(
                    parcel.tracking_number, parcel.company
                )
                
                status, eta = tracker.track_parcel(parcel.tracking_number)
                
                # Update if status changed
                if status != parcel.status or eta != parcel.eta:
                    parcel.status = status
                    parcel.eta = eta
                    parcel.last_updated = datetime.now()
                    
                    self.db_manager.save_parcel(parcel)
                    logging.info(f"Updated {parcel.tracking_number}: {status}")
                
            except Exception as e:
                logging.error(f"Error updating parcel {parcel.tracking_number}: {e}")
    
    def display_parcels(self):
        """Display parcel information in terminal"""
        parcels = self.db_manager.get_all_parcels()
        
        if not parcels:
            print("No parcels currently being tracked.")
            return
        
        # Limit display to configured maximum
        display_parcels = parcels[:self.config.max_display_parcels]
        
        # Clear screen
        import os
        os.system('clear' if os.name == 'posix' else 'cls')
        
        print("=" * 80)
        print("PARCEL TRACKING DASHBOARD")
        print("=" * 80)
        print(f"Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print()
        
        # Display parcels in table format
        print(f"{'Tracking Number':<20} {'Company':<12} {'Courier':<8} {'Status':<15} {'ETA':<12}")
        print("-" * 80)
        
        for parcel in display_parcels:
            eta_str = parcel.eta if parcel.eta else "TBD"
            print(f"{parcel.tracking_number:<20} {parcel.company:<12} "
                  f"{parcel.courier:<8} {parcel.status:<15} {eta_str:<12}")
        
        print("-" * 80)
        print(f"Showing {len(display_parcels)} of {len(parcels)} parcels")
        if len(parcels) > self.config.max_display_parcels:
            print(f"(Limited to {self.config.max_display_parcels} parcels - see config to adjust)")
        
        print(f"Next refresh in {self.config.terminal_refresh_seconds} seconds (Ctrl+C to exit)")
    
    def run_update_loop(self):
        """Background thread for periodic updates"""
        while self.running:
            try:
                self.check_new_emails()
                self.update_parcel_status()
                
                # Wait for next check
                time.sleep(self.config.check_interval_minutes * 60)
                
            except Exception as e:
                logging.error(f"Error in update loop: {e}")
                time.sleep(60)  # Wait 1 minute before retrying
    
    def start(self):
        """Start the parcel tracker"""
        logging.info("Starting parcel tracker...")
        
        # Initial check
        self.check_new_emails()
        self.update_parcel_status()
        
        # Start background update thread
        self.running = True
        self.update_thread = threading.Thread(target=self.run_update_loop)
        self.update_thread.daemon = True
        self.update_thread.start()
        
        # Main display loop
        try:
            while True:
                self.display_parcels()
                time.sleep(self.config.terminal_refresh_seconds)
                
        except KeyboardInterrupt:
            logging.info("Shutting down...")
            self.stop()
    
    def stop(self):
        """Stop the parcel tracker"""
        self.running = False
        if self.update_thread:
            self.update_thread.join(timeout=5)


# CLI Interface
def main():
    """Main entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Gmail Parcel Tracker')
    parser.add_argument('--config', default='config.yaml', 
                      help='Path to configuration file')
    parser.add_argument('--check-once', action='store_true',
                      help='Check emails once and exit')
    
    args = parser.parse_args()
    
    # Ensure config file exists
    if not Path(args.config).exists():
        print(f"Configuration file not found: {args.config}")
        print("Please create a config.yaml file with the following structure:")
        print("""
gmail_credentials_path: "credentials.json"
gmail_token_path: "token.json"
email_address: "your-email@gmail.com"
check_interval_minutes: 15
database_path: "parcels.db"
log_level: "INFO"
max_emails_per_check: 50
courier_apis:
  fedex: "your-fedex-api-key"
  ups: "your-ups-api-key"
        """)
        return
    
    tracker = ParcelTracker(args.config)
    
    if args.check_once:
        tracker.check_new_emails()
        tracker.update_parcel_status()
        tracker.display_parcels()
    else:
        tracker.start()


if __name__ == "__main__":
    main()