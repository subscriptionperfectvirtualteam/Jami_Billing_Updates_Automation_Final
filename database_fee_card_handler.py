#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Database Fee Card Handler for RDN Fee Scraper

This module provides server-side functions for handling and sending 
database fee information to the client via Socket.IO.
"""

import os
import sys
import json
import datetime
import importlib.util
from flask import Flask, request, redirect, url_for, jsonify, render_template
from flask_socketio import SocketIO, emit, join_room, leave_room
import logging

# Path to the main server module
server_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "server-upgraded.py")
spec = importlib.util.spec_from_file_location("server_module", server_path)
server_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server_module)

# Log message function
def log(message, level="info"):
    """Log messages at the specified level"""
    print(f"[{level.upper()}] {message}")
    
    if hasattr(logging, level.lower()):
        getattr(logging, level.lower())(message)

def install_event_handlers():
    """Install Socket.IO event handlers for database fee handling"""
    try:
        # Get the Socket.IO instance from the server module
        socketio = getattr(server_module, 'socketio', None)
        if not socketio:
            log("Socket.IO instance not found in server module", "error")
            return False
            
        # Get the original event handler for process completion
        original_on_process_complete = None
        
        # Find the original handler by searching through registered event handlers
        for event_name, handlers in getattr(socketio, '_handlers', {}).items():
            if event_name == 'process-complete':
                original_on_process_complete = handlers[0]
                break
                
        if not original_on_process_complete:
            log("Original process-complete handler not found", "error")
            return False
            
        # Define a new handler that includes database fee information
        def on_process_complete_with_db_fee(case_id, message=None):
            """Enhanced handler for process-complete event that includes database fee"""
            # Get the original result
            result = original_on_process_complete(case_id, message)
            
            # Add database fee information
            if hasattr(server_module, 'config'):
                # Check multiple possible locations for database fee information
                database_fee = None
                
                # Try different possible locations for the database fee
                if hasattr(server_module.config, 'database_fee_amount'):
                    database_fee = f"${server_module.config.database_fee_amount:.2f}"
                    
                elif 'database_fee_amount' in server_module.config:
                    fee_amount = server_module.config['database_fee_amount']
                    database_fee = f"${float(fee_amount):.2f}"
                    
                elif 'database_fees' in server_module.config and server_module.config['database_fees']:
                    try:
                        fee_entry = server_module.config['database_fees'][0]
                        fee_amount = fee_entry.get('amount', '').replace('$', '')
                        database_fee = f"${float(fee_amount):.2f}"
                    except (ValueError, KeyError, IndexError, AttributeError) as e:
                        log(f"Error extracting database fee from config: {str(e)}", "error")
                        database_fee = None
                        
                # Add database fee to the data sent to the client
                if database_fee and isinstance(result, dict):
                    result['databaseFee'] = database_fee
                    log(f"Added database fee {database_fee} to process-complete event", "info")
                        
            return result
            
        # Replace the original handler with our enhanced version
        socketio._handlers['process-complete'][0] = on_process_complete_with_db_fee
        log("Successfully replaced process-complete handler with database fee version", "info")
        return True
        
    except Exception as e:
        log(f"Error installing event handlers: {str(e)}", "error")
        import traceback
        log(traceback.format_exc(), "error")
        return False

# Install the event handlers when this module is imported
success = install_event_handlers()
if success:
    log("Database fee card handlers installed successfully")
else:
    log("Failed to install database fee card handlers", "error")