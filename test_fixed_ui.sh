#!/bin/bash

echo "Testing Fixed UI Version of RDN Fee Scraper..."
echo ""
echo "Checking for Python installation..."
if ! command -v python3 &> /dev/null
then
    echo "Python 3 is not installed or not in PATH. Please install Python 3.8 or higher."
    exit 1
fi

echo "Checking for required packages..."
if ! python3 -c "import selenium" &> /dev/null
then
    echo "Installing required packages..."
    pip3 install -r requirements.txt
fi

echo "Starting server with UI fixes..."
python3 server-upgradedv2.py