#!/bin/bash

set -e

PORT=${PORT:-3000}

echo "NoteShare - Installing dependencies..."
npm install

echo "Starting NoteShare on port $PORT..."
node server.js
