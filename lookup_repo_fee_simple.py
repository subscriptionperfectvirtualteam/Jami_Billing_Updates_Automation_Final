"""
Simplified function to look up repo fees from the database
based on client name, lienholder name, and fee type.

This implements the exact query from SQL_Query.sql with hardcoded 
column names matching the exact schema in feedetails2.json:

- FeeDetails2: fd_id, client_id, lh_id, ft_id, amount
- RDN_Client: id, client_name
- Lienholder: id, lienholder_name
- FeeType: id, fee_type_name
"""

import pyodbc
import logging
import traceback

def log(message, level="info"):
    """Log messages to the console with appropriate formatting"""
    level_upper = level.upper()
    print(f"[{level_upper}] {message}")
    
    if hasattr(logging, level.lower()):
        getattr(logging, level.lower())(message)

def log_query(query_type, query, params):
    """Log SQL query with parameters for debugging"""
    log(f"[SQL {query_type}] Executing query:")
    log(f"{query}")
    log(f"Parameters: {params}")

def get_db_connection(config_file='config.txt'):
    """Create a connection to the Azure SQL database using config file"""
    db_config = {
        "server": "",
        "username": "",
        "password": "",
        "database": ""
    }

    try:
        with open(config_file, 'r') as f:
            for line in f:
                if 'Server' in line:
                    db_config["server"] = line.split('-')[1].strip()
                elif 'USername' in line or 'Username' in line:
                    db_config["username"] = line.split('-')[1].strip()
                elif 'Password' in line:
                    db_config["password"] = line.split('-')[1].strip()
                elif 'Database' in line:
                    db_config["database"] = line.split('-')[1].strip()
        log(f"Database configuration loaded successfully")
    except Exception as e:
        log(f"Error loading database configuration: {str(e)}", "error")
        return None

    try:
        # Create the connection string for Azure SQL
        conn_str = (
            f"DRIVER={{ODBC Driver 17 for SQL Server}};"
            f"SERVER={db_config['server']};"
            f"DATABASE={db_config['database']};"
            f"UID={db_config['username']};"
            f"PWD={db_config['password']}"
        )

        # Connect to the database
        conn = pyodbc.connect(conn_str)
        log("Successfully connected to Azure SQL Database")
        return conn
    except Exception as e:
        log(f"Error connecting to database: {str(e)}", "error")
        return None

def lookup_repo_fee(client_name, lienholder_name, fee_type_name):
    """
    Lookup repo fee from database based on client name, lienholder name, and fee type.
    Uses hardcoded column names to avoid any schema detection issues.
    
    Args:
        client_name (str): The name of the client
        lienholder_name (str): The name of the lienholder
        fee_type_name (str): The name of the fee type (e.g., 'Involuntary Repo')
        
    Returns:
        dict: A dictionary containing fee details, or None if no matching fee is found
    """
    log(f'Looking up repo fee for: Client="{client_name}", Lienholder="{lienholder_name}", FeeType="{fee_type_name}"')
    
    conn = get_db_connection()
    if not conn:
        log("Could not connect to database. Unable to look up repo fee.", "error")
        return None
    
    try:
        cursor = conn.cursor()
        
        # Check that tables exist with the expected column names
        try:
            # Quick test query to confirm FeeDetails2 exists with expected columns
            test_query = """
            SELECT TOP 0 
                fd.fd_id, fd.client_id, fd.lh_id, fd.ft_id, fd.amount, 
                c.id, c.client_name, 
                lh.id, lh.lienholder_name, 
                ft.id, ft.fee_type_name
            FROM FeeDetails2 fd
            JOIN RDN_Client c ON 1=0
            JOIN Lienholder lh ON 1=0
            JOIN FeeType ft ON 1=0
            """
            cursor.execute(test_query)
            log("Successfully confirmed database schema")
        except Exception as e:
            log(f"Schema test failed. Using explicit schema detection. Error: {str(e)}", "warning")
            
            # Check tables and required columns exist
            tables_to_check = {
                "FeeDetails2": ["fd_id", "client_id", "lh_id", "ft_id", "amount"],
                "RDN_Client": ["id", "client_name"],
                "Lienholder": ["id", "lienholder_name"],
                "FeeType": ["id", "fee_type_name"]
            }
            
            for table, columns in tables_to_check.items():
                try:
                    cursor.execute(f"SELECT TOP 0 * FROM dbo.{table}")
                    actual_columns = [column[0] for column in cursor.description]
                    log(f"Table {table} found with columns: {', '.join(actual_columns)}")
                    
                    # Check required columns exist
                    missing_columns = [col for col in columns if col not in actual_columns]
                    if missing_columns:
                        log(f"Table {table} is missing required columns: {', '.join(missing_columns)}", "error")
                        log(f"Available columns: {', '.join(actual_columns)}")
                        return None
                        
                except Exception as table_e:
                    log(f"Error checking table {table}: {str(table_e)}", "error")
                    return None
        
        # Step 1: Get foreign keys from names (exactly as in SQL_Query.sql)
        log("Getting foreign keys from names...")
        try:
            cursor.execute("SELECT TOP 1 id FROM dbo.RDN_Client WHERE client_name = ?", client_name)
            client_row = cursor.fetchone()
            if not client_row:
                log(f"Client '{client_name}' not found in database", "warning")
                return None
            client_id = client_row[0]
            
            cursor.execute("SELECT TOP 1 id FROM dbo.Lienholder WHERE lienholder_name = ?", lienholder_name)
            lienholder_row = cursor.fetchone()
            if not lienholder_row:
                log(f"Lienholder '{lienholder_name}' not found in database", "warning")
                lienholder_id = None  # We'll handle this in the fallback logic
            else:
                lienholder_id = lienholder_row[0]
            
            cursor.execute("SELECT TOP 1 id FROM dbo.FeeType WHERE fee_type_name = ?", fee_type_name)
            fee_type_row = cursor.fetchone()
            if not fee_type_row:
                log(f"Fee type '{fee_type_name}' not found in database", "warning")
                return None
            fee_type_id = fee_type_row[0]
            
        except Exception as key_e:
            log(f"Error getting foreign keys: {str(key_e)}", "error")
            log(traceback.format_exc(), "error")
            return None
        
        # Step 2: Check if a matching record exists and return it if found (primary logic)
        if lienholder_id:
            try:
                # Using parameterized query for safety with explicit column names
                query = """
                    SELECT 
                        fd.fd_id,
                        c.client_name,
                        lh.lienholder_name,
                        ft.fee_type_name,
                        fd.amount
                    FROM dbo.FeeDetails2 fd
                    JOIN dbo.RDN_Client c ON fd.client_id = c.id
                    JOIN dbo.Lienholder lh ON fd.lh_id = lh.id
                    JOIN dbo.FeeType ft ON fd.ft_id = ft.id
                    WHERE fd.client_id = ? AND fd.lh_id = ? AND fd.ft_id = ?
                """
                log_query("PRIMARY LOOKUP", query, [client_id, lienholder_id, fee_type_id])
                cursor.execute(query, [client_id, lienholder_id, fee_type_id])
                row = cursor.fetchone()
                
                if row:
                    log(f"Found matching fee record for specific lienholder '{lienholder_name}'")
                    return {
                        'fd_id': row[0],
                        'client_name': row[1],
                        'lienholder_name': row[2],
                        'fee_type': row[3],
                        'amount': row[4],
                        'is_fallback': False
                    }
            except Exception as primary_e:
                log(f"Error in primary lookup: {str(primary_e)}", "error")
                log(traceback.format_exc(), "error")
                return None
        
        # Step 3: If no record found, try with 'Standard' lienholder (fallback logic)
        try:
            log(f"No specific record found. Looking up 'Standard' lienholder as fallback...")
            cursor.execute("SELECT TOP 1 id FROM dbo.Lienholder WHERE lienholder_name = 'Standard'")
            standard_row = cursor.fetchone()
            
            if not standard_row:
                log("'Standard' lienholder not found in database", "error")
                return None
            
            standard_lienholder_id = standard_row[0]
            
            # Look up using Standard lienholder with explicit column names
            fallback_query = """
                SELECT 
                    fd.fd_id,
                    c.client_name,
                    lh.lienholder_name,
                    ft.fee_type_name,
                    fd.amount
                FROM dbo.FeeDetails2 fd
                JOIN dbo.RDN_Client c ON fd.client_id = c.id
                JOIN dbo.Lienholder lh ON fd.lh_id = lh.id
                JOIN dbo.FeeType ft ON fd.ft_id = ft.id
                WHERE fd.client_id = ? AND fd.lh_id = ? AND fd.ft_id = ?
            """
            log_query("FALLBACK LOOKUP", fallback_query, [client_id, standard_lienholder_id, fee_type_id])
            cursor.execute(fallback_query, [client_id, standard_lienholder_id, fee_type_id])
            fallback_row = cursor.fetchone()
            
            if fallback_row:
                log(f"Found fallback fee using 'Standard' lienholder")
                return {
                    'fd_id': fallback_row[0],
                    'client_name': fallback_row[1],
                    'lienholder_name': fallback_row[2] + " (Standard Fallback)",
                    'fee_type': fallback_row[3],
                    'amount': fallback_row[4],
                    'is_fallback': True,
                    'message': f"Lienholder '{lienholder_name}' specific fee not found. Using Standard amount."
                }
        except Exception as fallback_e:
            log(f"Error in fallback lookup: {str(fallback_e)}", "error")
            log(traceback.format_exc(), "error")
            return None
        
        log("No fee record found with either specific lienholder or fallback", "warning")
        return None
        
    except Exception as e:
        log(f"General error looking up repo fee: {str(e)}", "error")
        log(traceback.format_exc(), "error")
        return None
    
    finally:
        if conn:
            conn.close()

# Import mechanism to choose between implementations
def get_lookup_repo_fee():
    return lookup_repo_fee

if __name__ == "__main__":
    # For testing purposes
    client_name = "Primeritus Specialized - IBEAM"
    lienholder_name = "Global CU fka Alaska USA FCU"
    fee_type = "Involuntary Repo"
    
    result = lookup_repo_fee(client_name, lienholder_name, fee_type)
    if result:
        print(f"Found fee: ${result['amount']:.2f} ({result['fee_type']})")
    else:
        print("No matching fee found")