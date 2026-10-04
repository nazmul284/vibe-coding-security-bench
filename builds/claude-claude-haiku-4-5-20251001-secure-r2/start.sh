#!/bin/bash

# NoteShare startup script
set -e

# Get the directory where this script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

# Set default port if not specified
PORT=${PORT:-3000}

echo "🚀 Starting NoteShare..."
echo "📁 Working directory: $SCRIPT_DIR"

# Check if Node.js is installed
if ! command -v node &> /dev/null; then
    echo "❌ Node.js is not installed. Please install Node.js 16+ first."
    exit 1
fi

echo "✓ Node.js $(node --version) found"

# Install dependencies if needed
if [ ! -d "node_modules" ]; then
    echo "📦 Installing dependencies..."
    npm install
fi

# Create data directory if it doesn't exist
mkdir -p data

# Start the server
echo "🌐 Server starting on http://localhost:$PORT"
echo "📝 Data stored in: $SCRIPT_DIR/data.db"
echo ""
echo "Press Ctrl+C to stop the server"
echo ""

PORT=$PORT node server.js
