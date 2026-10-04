#!/bin/bash

# NoteShare startup script
# Usage: ./start.sh or PORT=8080 ./start.sh

set -e

# Set default port
PORT=${PORT:-3000}

echo "🚀 Starting NoteShare..."
echo "📦 Installing dependencies..."

# Install npm dependencies
npm install

echo "✅ Dependencies installed"
echo "🌐 Starting server on port $PORT..."

# Start the server
PORT=$PORT node server.js
