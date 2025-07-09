# Gmail Parcel Tracker Setup Instructions

## Overview
This application monitors your Gmail account for shipping notifications and automatically tracks parcels through various courier APIs, displaying status updates in a terminal interface.

## Prerequisites
- Python 3.8 or higher
- Gmail account with API access enabled
- (Optional) API keys for courier services

## Installation Steps

### 1. Install Python Dependencies
```bash
pip install -r requirements.txt
```

### 2. Set up Gmail API Access

#### Enable Gmail API:
1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project or select existing one
3. Enable the Gmail API for your project
4. Create credentials (OAuth 2.0 Client ID) for a desktop application
5. Download the credentials file and save as `credentials.json`

#### Configure OAuth Consent Screen:
1. In Google Cloud Console, go to "APIs & Services" → "OAuth consent screen"
2. Add your email address as a test user
3. Add the following scopes:
   - `https://www.googleapis.com/auth/gmail.readonly`

### 3. Configure Application

#### Create config.yaml:
```bash
cp config.yaml.template config.yaml
```

#### Edit config.yaml:
- Set your Gmail address in `email_address`
- Adjust `check_interval_minutes` as needed
- Add courier API keys if available (optional)

#### File Structure:
```
parcel_tracker/
├── parcel_tracker.py
├── config.yaml
├── credentials.json
├── requirements.txt
├── README.md
└── parcels.db (created automatically)
```

### 4. First Run Authentication

When you first run the application, it will:
1. Open a browser window for Gmail authentication
2. Ask for permission to read your emails
3. Save the authentication token for future use

## Usage

### Basic Usage:
```bash
python parcel_tracker.py
```

### Check emails once and exit:
```bash
python parcel_tracker.py --check-once
```

### Use custom config file:
```bash
python parcel_tracker.py --config my_config.yaml
```

### Terminal Display:
The application displays a continuously updating table showing:
- Tracking number
- Company (Amazon, eBay, etc.)
- Courier (UPS, FedEx, etc.)
- Current status
- Estimated delivery date

## Features

### Automatic Detection:
- Scans Gmail for shipping notifications
- Extracts tracking numbers using regex patterns
- Identifies courier services automatically
- Detects company/retailer from email content

### Multi-Courier Support:
- UPS tracking
- FedEx tracking
- USPS tracking
- DHL tracking
- Generic fallback for unknown couriers

### Data Persistence:
- SQLite database for parcel storage
- Automatic status updates
- Historical tracking data
- Duplicate detection

### Error Handling:
- Robust API error handling
- Retry mechanisms for failed requests
- Comprehensive logging
- Graceful degradation when APIs are unavailable

## Configuration Options

### Email Search Configuration:
The application searches for emails using configurable patterns:
- Subject line keywords (shipped, tracking, delivery, etc.)
- Sender domains (amazon.com, ups.com, fedex.com, etc.)
- Date ranges (default: last 7 days)

### Tracking Number Patterns:
Supports various tracking number formats:
- UPS: `1Z[0-9A-Z]{16}`
- FedEx Express: `[0-9]{12}`
- FedEx Ground: `[0-9]{14}`
- USPS: `[A-Z]{2}[0-9]{9}[A-Z]{2}`
- Generic: `[0-9]{20,22}`

### Courier API Configuration:
Add your API keys to `config.yaml`:
```yaml
courier_apis:
  fedex: "your-fedex-api-key"
  ups: "your-ups-api-key"
  usps: "your-usps-api-key"
  dhl: "your-dhl-api-key"
```

**Note:** API keys are optional. Without them, the application will still detect and store parcels but won't provide real-time status updates.

## Troubleshooting

### Common Issues:

#### Gmail Authentication Errors:
- Ensure Gmail API is enabled in Google Cloud Console
- Check that `credentials.json` is in the correct location
- Verify your email is added as a test user
- Delete `token.json` and re-authenticate if needed

#### No Parcels Detected:
- Check email search query in config
- Verify tracking numbers are in expected format
- Review application logs for parsing errors
- Test with known shipping emails

#### API Rate Limits:
- Reduce `check_interval_minutes` if hitting rate limits
- Implement exponential backoff (already included)
- Monitor API usage quotas

#### Database Issues:
- Ensure write permissions for database file
- Check disk space availability
- Review SQLite connection errors in logs

### Logging:
Application logs are written to:
- Console output (INFO level and above)
- `parcel_tracker.log` file (configurable level)

To increase log verbosity:
```yaml
log_level: "DEBUG"
```

## Advanced Usage

### Custom Email Queries:
Modify the email search query in `config.yaml`:
```yaml
email_search_query: >
  subject:(your custom search terms)
  OR from:(specific-sender@domain.com)
  newer_than:30d
```

### Database Management:
The SQLite database can be queried directly:
```bash
sqlite3 parcels.db
.tables
SELECT * FROM parcels;
```

### Extending Courier Support:
To add new courier tracking:

1. Create a new courier tracker class:
```python
class NewCourierTracker(CourierTracker):
    def can_handle(self, tracking_number: str, company: str) -> bool:
        # Implement detection logic
        return pattern_matches
    
    def track_parcel(self, tracking_number: str) -> Tuple[str, Optional[str]]:
        # Implement API call
        return status, eta
```

2. Add to `CourierTrackerFactory`:
```python
self.trackers = [
    FedExTracker(courier_apis.get('fedex', '')),
    UPSTracker(courier_apis.get('ups', '')),
    NewCourierTracker(courier_apis.get('new_courier', '')),
    GenericTracker()
]
```

## Security Considerations

### API Key Management:
- Store API keys in config file (not in code)
- Use environment variables for production
- Rotate keys regularly
- Monitor API usage

### Email Access:
- Uses read-only Gmail API scope
- OAuth token stored locally
- No email content stored (only tracking numbers)
- Respects Gmail rate limits

### Data Storage:
- Local SQLite database
- No cloud storage of personal data
- Tracking numbers only (no personal info)
- Database can be encrypted if needed

## Performance Optimization

### Efficient Email Processing:
- Configurable email batch size
- Date-based filtering
- Duplicate detection
- Incremental updates

### API Rate Limiting:
- Exponential backoff on failures
- Cached results to reduce API calls
- Configurable update intervals
- Request batching where supported

### Memory Management:
- Streaming email processing
- Database connection pooling
- Efficient regex compilation
- Garbage collection friendly

## Maintenance

### Regular Tasks:
- Monitor log files for errors
- Update API keys as needed
- Clean old tracking data
- Update tracking patterns for new formats

### Updates:
- Keep dependencies updated
- Monitor courier API changes
- Add new tracking patterns as needed
- Backup database periodically

## License and Disclaimer

This application is provided as-is for personal use. Users are responsible for:
- Complying with Gmail API terms of service
- Obtaining proper API keys for courier services
- Respecting rate limits and usage policies
- Ensuring data privacy and security

The application does not guarantee 100% accuracy of tracking information and should not be relied upon for critical shipping decisions.

## Support

For issues and questions:
1. Check the troubleshooting section
2. Review application logs
3. Verify configuration settings
4. Test with minimal setup

## Future Enhancements

Potential improvements:
- Web dashboard interface
- Mobile notifications
- More courier integrations
- Advanced filtering options
- Export capabilities
- Multiple email account support
