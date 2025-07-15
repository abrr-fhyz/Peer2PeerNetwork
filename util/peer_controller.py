import json
import socket
import time
from pathlib import Path
from util.dht_node import DHT
from util.peer_node import Peer
from util.file_processor import FileProcessor

class PeerController:
    def __init__(self, peer_host="localhost", peer_port=9000, dht_host="localhost", dht_port=8000):
        self.peer_host = peer_host
        self.peer_port = peer_port
        self.dht_host = dht_host
        self.dht_port = dht_port
        
        self.dht = None
        self.peer = None
        self.file_processor = FileProcessor()
        self.running = False
    
    def _receive_complete_message(self, sock):
        """Receive complete JSON message from socket"""
        data = b''
        while True:
            chunk = sock.recv(8192)
            if not chunk:
                break
            data += chunk
            try:
                return json.loads(data.decode())
            except json.JSONDecodeError:
                continue
        raise Exception("Failed to receive complete message")

    def start_services(self):
        if not self.is_port_in_use(self.dht_host, self.dht_port):
            self.dht = DHT(self.dht_host, self.dht_port)
            self.dht.start()
            time.sleep(1)  
        else:
            print(f"DHT is already running on {self.dht_host}:{self.dht_port}, skipping...")
        
        self.peer = Peer(host=self.peer_host, port=self.peer_port, 
                        dht_host=self.dht_host, dht_port=self.dht_port)
        self.peer.start()
        time.sleep(2)
        
        self.running = True
    
    def stop_services(self):
        if self.peer:
            self.peer.stop()
        if self.dht:
            self.dht.stop()
        self.running = False
    
    def upload_video(self, video_path: str):
        metadata = self.file_processor.process_video(video_path)
        
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.connect((self.dht_host, self.dht_port))
            
            chunk_hashes = [chunk['hash'] for chunk in metadata.chunks]
            
            message = {
                'type': 'add_video',
                'video_id': metadata.video_id,
                'filename': metadata.filename,
                'chunk_hashes': chunk_hashes
            }
            
            sock.send(json.dumps(message).encode())
            response = self._receive_complete_message(sock) 

            if response.get('success'):
                self._distribute_chunks(metadata)
    
    def _distribute_chunks(self, metadata):
        for chunk_info in metadata.chunks:
            chunk_data = self.file_processor.get_chunk_data(metadata.video_id, chunk_info['index'])
            if chunk_data:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                    sock.connect((self.dht_host, self.dht_port))
                    
                    message = {
                        'type': 'get_placement',
                        'chunk_hash': chunk_info['hash']
                    }
                    
                    sock.send(json.dumps(message).encode())
                    response = self._receive_complete_message(sock)
                    
                    success_count = 0
                    for target_peer in response.get('target_peers', []):
                        if self._send_chunk_to_peer(chunk_info['hash'], chunk_data, target_peer):
                            success_count += 1
                    
                    print(f"Chunk {chunk_info['index']} sent to {success_count} peers")
    
    def _send_chunk_to_peer(self, chunk_hash, chunk_data, target_peer):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.connect((target_peer['host'], target_peer['port']))
                
                message = {
                    'type': 'store_chunk',
                    'chunk_hash': chunk_hash,
                    'chunk_data': chunk_data.hex()
                }
                
                sock.send(json.dumps(message).encode())
                # Wait for response to confirm chunk was stored
                response = json.loads(sock.recv(4096).decode())
                return response.get('success', False)
        except Exception as e:
            #print(f"Failed to send chunk to {target_peer}: {e}")
            return False
    
    def list_videos(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.connect((self.dht_host, self.dht_port))
            
            message = {'type': 'get_videos'}
            sock.send(json.dumps(message).encode())
            response = self._receive_complete_message(sock)  
            videos = response.get('videos', [])
            if videos:
                for i, video in enumerate(videos, 1):
                    print(f"{i}. {video['filename']} - {video['chunks']} chunks - ID: {video['video_id']}")
            else:
                print("No videos available")
    
    def download_video(self, video_id: str, output_path: str):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.connect((self.dht_host, self.dht_port))
            message = {
                'type': 'get_video_chunks',
                'video_id': video_id
            }
            sock.send(json.dumps(message).encode())
            response = self._receive_complete_message(sock)
            chunk_hashes = response.get('chunk_hashes', [])
            if not chunk_hashes:
                print("Video not found")
                return
            chunks_data = []
            for i, chunk_hash in enumerate(chunk_hashes):
                print(f"Downloading chunk {i+1}/{len(chunk_hashes)}")
                chunk_data = self.peer.get_chunk(chunk_hash)
                if chunk_data:
                    chunks_data.append(chunk_data)
                else:
                    print(f"Failed to get chunk: {chunk_hash}")
                    return
            with open(output_path, 'wb') as f:
                for chunk_data in chunks_data:
                    f.write(chunk_data)
    
    def is_port_in_use(self, host, port):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.settimeout(1)  
                s.connect((host, port))
                return True 
            except (socket.timeout, ConnectionRefusedError):
                return False 
