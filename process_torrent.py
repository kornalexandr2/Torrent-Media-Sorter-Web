#!/usr/bin/env python3
import os
import sys
import json
import urllib.request

def send_to_webhook(torrent_id, torrent_name, torrent_dir):
    url = "http://localhost:8080/api/webhook"
    payload = {
        "torrent_id": torrent_id,
        "torrent_name": torrent_name,
        "torrent_dir": torrent_dir
    }
    
    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'})
    
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            if response.status == 200:
                print(f"Successfully sent {torrent_name} to webhook.")
            else:
                print(f"Webhook returned status code: {response.status}")
    except Exception as e:
        print(f"Error sending to webhook: {e}")

if __name__ == "__main__":
    # 1. Try to get from command line arguments (universal way, e.g. for qBittorrent)
    # Usage: process_torrent.py "Name" "Directory" "ID"
    if len(sys.argv) >= 3:
        t_name = sys.argv[1]
        t_dir = sys.argv[2]
        t_id = sys.argv[3] if len(sys.argv) > 3 else None
    else:
        # 2. Try to get from Transmission environment variables
        t_id = os.environ.get('TR_TORRENT_ID')
        t_name = os.environ.get('TR_TORRENT_NAME')
        t_dir = os.environ.get('TR_TORRENT_DIR')
        
    # 3. Fallback for manual call with a single path
    if not t_name and len(sys.argv) == 2:
        path = sys.argv[1]
        t_dir = os.path.dirname(os.path.abspath(path))
        t_name = os.path.basename(path)
        
    if t_name and t_dir:
        send_to_webhook(t_id, t_name, t_dir)
    else:
        print("Usage:")
        print("  Transmission: (automatic via env vars)")
        print("  qBittorrent:  process_torrent.py \"%N\" \"%D\" \"%I\"")
        print("  Manual:       process_torrent.py \"/path/to/media\"")
