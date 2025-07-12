#!/usr/bin/env python3
import subprocess
import time
import sys
import threading
import signal
import os
from pathlib import Path

class P2PStreamingLauncher:
    def __init__(self):
        self.processes = []
        self.running = True
        
    def start_dht(self):
        """Start DHT node"""
        print("Starting DHT node...")
        from dht_node import DHT
        
        dht = DHT("localhost", 8000)
        dht.start()
        
        # Keep DHT running
        while self.running:
            time.sleep(1)
        
        dht.stop()
    
    def start_seed_peer(self):
        """Start a seed peer for initial content"""
        print("Starting seed peer...")
        time.sleep(2)  # Wait for DHT to be ready
        
        from peer_node import Peer
        
        seed_peer = Peer(
            host="localhost", 
            port=9000, 
            dht_host="localhost", 
            dht_port=8000
        )
        seed_peer.start()
        
        # Keep seed peer running
        while self.running:
            time.sleep(1)
        
        seed_peer.stop()
    
    def start_web_backend(self):
        """Start FastAPI web backend"""
        print("Starting web backend...")
        time.sleep(3)  # Wait for DHT and seed peer
        
        import uvicorn
        from streaming_server import app
        
        # Run FastAPI app
        uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
    
    def signal_handler(self, signum, frame):
        """Handle shutdown signals"""
        print("\nShutting down...")
        self.running = False
        
        for process in self.processes:
            if process.is_alive():
                process.terminate()
                process.join(timeout=5)
        
        sys.exit(0)
    
    def run(self):
        """Run the complete P2P streaming system"""
        # Register signal handlers
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)
        
        print("🚀 Starting P2P Video Streaming System...")
        print("=" * 50)
        
        # Start DHT in background thread
        dht_thread = threading.Thread(target=self.start_dht, daemon=True)
        dht_thread.start()
        
        # Start seed peer in background thread
        seed_thread = threading.Thread(target=self.start_seed_peer, daemon=True)
        seed_thread.start()
        
        # Start web backend (this will block)
        print("🌐 Web interface will be available at: http://localhost:8000")
        print("📺 Open your browser and navigate to the URL above")
        print("=" * 50)
        
        try:
            self.start_web_backend()
        except KeyboardInterrupt:
            self.signal_handler(signal.SIGINT, None)

def check_dependencies():
    """Check if required dependencies are installed"""
    try:
        import fastapi
        import uvicorn
        print("✅ FastAPI dependencies found")
    except ImportError:
        print("❌ FastAPI dependencies not found")
        print("Please install: pip install fastapi uvicorn python-multipart aiofiles")
        return False
    
    # Check if required files exist
    required_files = ['dht_node.py', 'peer_node.py', 'streaming_backend.py']
    missing_files = []
    
    for file in required_files:
        if not Path(file).exists():
            missing_files.append(file)
    
    if missing_files:
        print(f"❌ Missing required files: {', '.join(missing_files)}")
        return False
    
    print("✅ All required files found")
    return True

if __name__ == "__main__":
    print("🎬 P2P Video Streaming System Launcher")
    print("=" * 50)
    
    if not check_dependencies():
        sys.exit(1)
    
    launcher = P2PStreamingLauncher()
    launcher.run()