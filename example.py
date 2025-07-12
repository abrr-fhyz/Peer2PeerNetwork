#!/usr/bin/env python3

from peer_controller import PeerController
import time
import threading

def start_multiple_peers():
    """Example of starting multiple peers for testing"""
    
    # Start first peer (with both DHT and peer)
    print("Starting Peer 1...")
    peer1 = PeerController(peer_host="localhost", peer_port=9001, 
                          dht_host="localhost", dht_port=8000)
    
    # Start second peer (connects to existing DHT)
    print("Starting Peer 2...")
    peer2 = PeerController(peer_host="localhost", peer_port=9002,
                          dht_host="localhost", dht_port=8000)
    
    # Start services for peer1 in a thread
    def run_peer1():
        peer1.console_gui()
    
    # Start services for peer2 in a thread  
    def run_peer2():
        peer2.console_gui()
    
    # Start both peers
    thread1 = threading.Thread(target=run_peer1, daemon=True)
    thread2 = threading.Thread(target=run_peer2, daemon=True)
    
    thread1.start()
    time.sleep(2)  # Give first peer time to start DHT
    thread2.start()
    
    # Keep main thread alive
    try:
        thread1.join()
        thread2.join()
    except KeyboardInterrupt:
        print("Shutting down all peers...")

def simple_example():
    """Simple single peer example"""
    controller = PeerController()
    controller.console_gui()

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "--multi":
        start_multiple_peers()
    else:
        simple_example()