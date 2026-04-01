#!/bin/bash
# Real-time log viewer for Market Pulse v2.0 (Institutional Mode)
echo "========================================================="
echo "   MARKET PULSE LIVE LOGS (Systemd + App Logs)"
echo "========================================================="
echo "Press Ctrl+C to exit."
echo ""

# Tails both the systemd journal and the local app.log file
sudo journalctl -u nsebot -f -n 50 &
tail -f nse_monitor/logs/app.log
