"""
Standalone function to look up repo fees from the database
based on client name, lienholder name, and fee type.

This implements the exact same logic as SQL_Query.sql but with
automatic column name detection to handle database schema variations.
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

def get_table_column_names(cursor, table_name):
    """Get the column names for a specific table"""
    try:
        cursor.execute(f"SELECT TOP 0 * FROM dbo.{table_name}")
        return [column[0] for column in cursor.description]
    except Exception as e:
        log(f"Error getting column names for table {table_name}: {str(e)}", "error")
        return []

def get_tables_with_columns(cursor):
    """Get a mapping of tables and their columns"""
    tables_info = {}
    
    try:
        # Get all user tables in the database
        cursor.execute("""
            SELECT table_name = t.name
            FROM sys.tables t
            INNER JOIN sys.schemas s ON t.schema_id = s.schema_id
            WHERE s.name = 'dbo'
            ORDER BY t.name
        """)
        
        tables = [row[0] for row in cursor.fetchall()]
        log(f"Found {len(tables)} tables in the database")
        
        # For each table, get the column names
        for table in tables:
            try:
                columns = get_table_column_names(cursor, table)
                tables_info[table] = columns
                log(f"Table {table} has columns: {', '.join(columns)}")
            except Exception as e:
                log(f"Error getting columns for table {table}: {str(e)}", "error")
                
        return tables_info
    except Exception as e:
        log(f"Error getting tables and columns: {str(e)}", "error")
        return {}

def find_matching_column(columns, possible_names):
    """Find a matching column name from a list of possibilities"""
    for col in columns:
        col_lower = col.lower()
        for name in possible_names:
            if name.lower() in col_lower or col_lower in name.lower():
                return col
    return None

def lookup_repo_fee(client_name, lienholder_name, fee_type_name):
    """
    Lookup repo fee from database based on client name, lienholder name, and fee type.
    Implements the exact query from SQL_Query.sql with automatic schema detection.
    
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
        
        # First, get information about all tables and their columns
        tables_info = get_tables_with_columns(cursor)
        if not tables_info:
            log("Could not get database schema information", "error")
            return None
        
        # Determine table names based on schema names we find
        fee_table = None
        client_table = None
        lienholder_table = None 
        feetype_table = None
        
        # Identify the tables we need
        for table, columns in tables_info.items():
            table_lower = table.lower()
            
            # Fee table detection
            if 'feedetails' in table_lower or 'fee_details' in table_lower:
                fee_table = table
                log(f"Using {table} as the fee details table")
                
            # Client table detection
            elif 'client' in table_lower:
                client_table = table
                log(f"Using {table} as the client table")
                
            # Lienholder table detection
            elif 'lienholder' in table_lower or 'lien_holder' in table_lower:
                lienholder_table = table
                log(f"Using {table} as the lienholder table")
                
            # Fee type table detection
            elif 'feetype' in table_lower or 'fee_type' in table_lower:
                feetype_table = table
                log(f"Using {table} as the fee type table")
        
        # Check if we found all required tables
        if not all([fee_table, client_table, lienholder_table, feetype_table]):
            missing = []
            if not fee_table: missing.append("Fee Details")
            if not client_table: missing.append("Client")
            if not lienholder_table: missing.append("Lienholder")
            if not feetype_table: missing.append("Fee Type")
            
            log(f"Could not find all required tables. Missing: {', '.join(missing)}", "error")
            
            # Try using default names as fallback
            fee_table = fee_table or "FeeDetails"
            client_table = client_table or "RDN_Client"
            lienholder_table = lienholder_table or "Lienholder"
            feetype_table = feetype_table or "FeeType"
            
            log(f"Using fallback table names: Fee={fee_table}, Client={client_table}, Lienholder={lienholder_table}, FeeType={feetype_table}", "warning")
        
        # Now identify the column names in each table
        # For client table
        client_columns = tables_info.get(client_table, [])
        client_id_col = find_matching_column(client_columns, ['id', 'client_id', 'clientid'])
        client_name_col = find_matching_column(client_columns, ['client_name', 'clientname', 'name'])
        
        if not client_id_col or not client_name_col:
            log(f"Could not identify required columns in client table {client_table}", "error")
            return None
            
        # For lienholder table
        lienholder_columns = tables_info.get(lienholder_table, [])
        lienholder_id_col = find_matching_column(lienholder_columns, ['id', 'lienholder_id', 'lienholderid', 'lh_id'])
        lienholder_name_col = find_matching_column(lienholder_columns, ['lienholder_name', 'lienholdername', 'name'])
        
        if not lienholder_id_col or not lienholder_name_col:
            log(f"Could not identify required columns in lienholder table {lienholder_table}", "error")
            return None
            
        # For fee type table
        feetype_columns = tables_info.get(feetype_table, [])
        feetype_id_col = find_matching_column(feetype_columns, ['id', 'feetype_id', 'feetypeid', 'ft_id'])
        feetype_name_col = find_matching_column(feetype_columns, ['fee_type_name', 'feetypename', 'name'])
        
        if not feetype_id_col or not feetype_name_col:
            log(f"Could not identify required columns in fee type table {feetype_table}", "error")
            return None
            
        # For fee details table
        feedetails_columns = tables_info.get(fee_table, [])
        fd_id_col = find_matching_column(feedetails_columns, ['id', 'fd_id', 'feedetailsid', 'feedetails_id'])
        client_id_ref_col = find_matching_column(feedetails_columns, ['client_id', 'clientid'])
        lienholder_id_ref_col = find_matching_column(feedetails_columns, ['lienholder_id', 'lienholderid', 'lh_id'])
        feetype_id_ref_col = find_matching_column(feedetails_columns, ['feetype_id', 'feetypeid', 'ft_id'])
        amount_col = find_matching_column(feedetails_columns, ['amount', 'fee_amount', 'feeamount'])
        
        if not all([fd_id_col, client_id_ref_col, lienholder_id_ref_col, feetype_id_ref_col, amount_col]):
            log(f"Could not identify all required columns in fee details table {fee_table}", "error")
            missing_cols = []
            if not fd_id_col: missing_cols.append("fee details ID")
            if not client_id_ref_col: missing_cols.append("client ID reference")
            if not lienholder_id_ref_col: missing_cols.append("lienholder ID reference")
            if not feetype_id_ref_col: missing_cols.append("fee type ID reference")
            if not amount_col: missing_cols.append("amount")
            log(f"Missing columns: {', '.join(missing_cols)}", "error")
            return None
        
        # Step 1: Get foreign keys from names (exactly as in SQL_Query.sql)
        log("Getting foreign keys from names...")
        cursor.execute(f"SELECT TOP 1 {client_id_col} FROM dbo.{client_table} WHERE {client_name_col} = ?", client_name)
        client_row = cursor.fetchone()
        if not client_row:
            log(f"Client '{client_name}' not found in database", "warning")
            return None
        client_id = client_row[0]
        
        cursor.execute(f"SELECT TOP 1 {lienholder_id_col} FROM dbo.{lienholder_table} WHERE {lienholder_name_col} = ?", lienholder_name)
        lienholder_row = cursor.fetchone()
        if not lienholder_row:
            log(f"Lienholder '{lienholder_name}' not found in database", "warning")
            lienholder_id = None  # We'll handle this in the fallback logic
        else:
            lienholder_id = lienholder_row[0]
        
        cursor.execute(f"SELECT TOP 1 {feetype_id_col} FROM dbo.{feetype_table} WHERE {feetype_name_col} = ?", fee_type_name)
        fee_type_row = cursor.fetchone()
        if not fee_type_row:
            log(f"Fee type '{fee_type_name}' not found in database", "warning")
            return None
        fee_type_id = fee_type_row[0]
        
        # Step 2: Check if a matching record exists and return it if found (primary logic)
        if lienholder_id:
            # Using parameterized query for safety with the detected column names
            query = f"""
                SELECT 
                    fd.{fd_id_col},
                    c.{client_name_col},
                    lh.{lienholder_name_col},
                    ft.{feetype_name_col},
                    fd.{amount_col}
                FROM dbo.{fee_table} fd
                JOIN dbo.{client_table} c ON fd.{client_id_ref_col} = c.{client_id_col}
                JOIN dbo.{lienholder_table} lh ON fd.{lienholder_id_ref_col} = lh.{lienholder_id_col}
                JOIN dbo.{feetype_table} ft ON fd.{feetype_id_ref_col} = ft.{feetype_id_col}
                WHERE fd.{client_id_ref_col} = ? AND fd.{lienholder_id_ref_col} = ? AND fd.{feetype_id_ref_col} = ?
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
        
        # Step 3: If no record found, try with 'Standard' lienholder (fallback logic)
        log(f"No specific record found. Looking up 'Standard' lienholder as fallback...")
        cursor.execute(f"SELECT TOP 1 {lienholder_id_col} FROM dbo.{lienholder_table} WHERE {lienholder_name_col} = 'Standard'")
        standard_row = cursor.fetchone()
        
        if not standard_row:
            log("'Standard' lienholder not found in database", "error")
            return None
        
        standard_lienholder_id = standard_row[0]
        
        # Look up using Standard lienholder with detected column names
        fallback_query = f"""
            SELECT 
                fd.{fd_id_col},
                c.{client_name_col},
                lh.{lienholder_name_col},
                ft.{feetype_name_col},
                fd.{amount_col}
            FROM dbo.{fee_table} fd
            JOIN dbo.{client_table} c ON fd.{client_id_ref_col} = c.{client_id_col}
            JOIN dbo.{lienholder_table} lh ON fd.{lienholder_id_ref_col} = lh.{lienholder_id_col}
            JOIN dbo.{feetype_table} ft ON fd.{feetype_id_ref_col} = ft.{feetype_id_col}
            WHERE fd.{client_id_ref_col} = ? AND fd.{lienholder_id_ref_col} = ? AND fd.{feetype_id_ref_col} = ?
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
        
        log("No fee record found with either specific lienholder or fallback", "warning")
        return None
        
    except Exception as e:
        log(f"Error looking up repo fee: {str(e)}", "error")
        log(traceback.format_exc(), "error")
        return None
    
    finally:
        if conn:
            conn.close()

# Example usage
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