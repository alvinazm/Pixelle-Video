#!/bin/bash
# Start  Web UI

echo "🚀 Starting Ai-Video Web UI..."
echo ""

PORT=8501
if lsof -i :$PORT > /dev/null 2>&1; then
    echo "Port $PORT is in use. Killing existing process..."
    lsof -t -i :$PORT | xargs kill -9 2>/dev/null
    sleep 1
fi

uv run streamlit run web/app.py --server.headless true > web.log 2>&1 &