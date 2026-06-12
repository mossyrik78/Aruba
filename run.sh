#!/bin/bash
# Quick start script for the Aruba Central Device Manager Web UI

set -e

echo "🚀 Starting Aruba Central Device Manager Web UI..."
echo ""

# Check if dependencies are installed
if ! python3 -c "import flask" 2>/dev/null; then
    echo "📦 Installing dependencies..."
    python3 -m pip install -q -r requirements.txt
    echo "✓ Dependencies installed"
    echo ""
fi

# Check if migration_plan.yaml exists
if [ ! -f "migration_plan.yaml" ]; then
    echo "⚠️  migration_plan.yaml not found"
    echo "📋 Creating from example..."
    cp migration_plan.example.yaml migration_plan.yaml
    echo "✓ Created migration_plan.yaml"
    echo ""
    echo "⚠️  Please edit migration_plan.yaml with your Aruba Central credentials:"
    echo "   - central.base_url"
    echo "   - central.client_id"
    echo "   - central.client_secret"
    echo ""
fi

echo "🌐 Web UI starting on http://localhost:5000"
echo "📱 Open your browser and navigate to http://localhost:5000"
echo "⌨️  Press Ctrl+C to stop the server"
echo ""

python3 app.py
