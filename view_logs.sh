#!/bin/bash
# Real-time log viewer for Market Intelligence Bot
echo "Watching logs... (Press Ctrl+C to exit)"
tail -f logs/service.log logs/service_error.log