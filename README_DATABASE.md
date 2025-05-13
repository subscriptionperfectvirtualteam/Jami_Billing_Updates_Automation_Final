# RDN Fee Scraper with Database Integration

This application scrapes fee information from the Recovery Database Network (RDN) and provides database operations for storing and fetching fee data.

## Features

- Scrapes fee information from RDN cases
- Categorizes fees based on patterns
- Extracts and displays fee data
- Connects to Azure SQL Database
- Saves fee data to the database
- Fetches fee data from the database based on filtering criteria

## Setup

1. Install required Python packages:

```bash
pip install flask flask-socketio selenium pyodbc
```

2. Install ODBC Driver for SQL Server:

For Windows:
Download and install from Microsoft: "ODBC Driver 17 for SQL Server"

For Linux (Ubuntu/Debian):
```bash
curl https://packages.microsoft.com/keys/microsoft.asc | apt-key add -
curl https://packages.microsoft.com/config/ubuntu/$(lsb_release -rs)/prod.list > /etc/apt/sources.list.d/mssql-release.list
apt-get update
apt-get install -y unixodbc-dev msodbcsql17
```

For other systems, check Microsoft documentation.

3. Configure database connection in `config.txt`:

The file should have this format:
```
Server - your-server.database.windows.net
USername - your-username
Password - your-password
Database - your-database
```

## Usage

1. Start the web portal:

```bash
python server-upgraded.py
```

2. Open a web browser and navigate to: http://localhost:5050

3. Enter your RDN credentials and case ID to start scraping

4. Use the Database Fee Search section to fetch fee information from the database

## Database Operations

### Fetch Fee Data

You can search for fee data using any combination of:
- Client name
- Lienholder name
- Fee type

The search uses partial matching (LIKE) for all fields.

## Adding New Fee Categories

To add new fee categories, edit the `fee_categories` dictionary in `server-upgraded.py`.
Each category should have a list of keywords that identify fees of that type.

## Database Schema

The application works with the following database schema:

- `dbo.FeeDetails2`: Contains the fee details with foreign keys to clients, fee types, and lien holders
- `dbo.RDN_Client`: Contains client information 
- `dbo.FeeType`: Contains fee type definitions
- `dbo.LienHolder`: Contains lien holder information
- `dbo.LienHolderFeeType`: Maps relationships between lien holders and fee types

## Note

This application contains credentials for connecting to a database in the config.txt file.
For security reasons, do not share this file or commit it to version control systems.