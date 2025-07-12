import hashlib
import json
import socket
import threading
import time
import os
from pathlib import Path
from typing import Dict, List

class Peer:
    def __init__(self, host="localhost", port=9000, dht_host="localhost", dht_port=8000):
        self.peer_id = hashlib.sha1(f"{time.time()}".encode()).hexdigest()[:16]
        self.host = host
        self.port = port
        self.dht_host = dht_host
        self.dht_port = dht_port

        storage_name = f"peer#{host}+{port}"
        self.storage_dir = Path(f"./storage/{storage_name}")
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        
        self.chunks: Dict[str, str] = {}
        self.videos: List[dict] = []
        
        self.socket = None
        self.running = False
    
    def start(self):
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.socket.bind((self.host, self.port))
        self.socket.listen(10)
        self.running = True
        
        threading.Thread(target=self._server_loop, daemon=True).start()
        self._register_with_dht()
        self._load_existing_chunks()
        threading.Thread(target=self._sync_videos_loop, daemon=True).start()
    
    def stop(self):
        self.running = False
        if self.socket:
            self.socket.close()
    
    def _server_loop(self):
        while self.running:
            try:
                client, addr = self.socket.accept()
                threading.Thread(target=self._handle_client, args=(client,), daemon=True).start()
            except:
                break
    
    def _handle_client(self, client):
        try:
            data = b''
            while True:
                chunk = client.recv(4096)
                if not chunk:
                    break
                data += chunk
                try:
                    json.loads(data.decode())
                    break  
                except:
                    continue 
            message = json.loads(data.decode())
            response = self._process_message(message)
            client.send(json.dumps(response).encode())
        except Exception as e:
            print(f"Client handling error: {e}")
        finally:
            client.close()
    
    def _process_message(self, message):
        msg_type = message['type']
        
        if msg_type == 'get_chunk':
            return self._handle_get_chunk(message)
        elif msg_type == 'store_chunk':
            return self._handle_store_chunk(message)
        elif msg_type == 'delete_chunk':
            return self._handle_delete_chunk(message)
        
        return {'error': 'unknown_type'}
    
    def _handle_get_chunk(self, message):
        chunk_hash = message['chunk_hash']
        
        if chunk_hash in self.chunks:
            with open(self.chunks[chunk_hash], 'rb') as f:
                chunk_data = f.read().hex()
            return {'success': True, 'chunk_data': chunk_data}
        
        return {'success': False}
    
    def _handle_store_chunk(self, message):
        chunk_hash = message['chunk_hash']
        chunk_data = bytes.fromhex(message['chunk_data'])
        
        file_path = self.storage_dir / f"{chunk_hash}.chunk"
        
        with open(file_path, 'wb') as f:
            f.write(chunk_data)
        
        self.chunks[chunk_hash] = str(file_path)
        self._update_dht_chunk_location(chunk_hash)
        
        return {'success': True}
    
    def _handle_delete_chunk(self, message):
        chunk_hash = message['chunk_hash']
        
        if chunk_hash in self.chunks:
            os.remove(self.chunks[chunk_hash])
            del self.chunks[chunk_hash]
            return {'success': True}
        
        return {'success': False}
    
    def _register_with_dht(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.connect((self.dht_host, self.dht_port))
            
            message = {
                'type': 'register_peer',
                'peer_id': self.peer_id,
                'host': self.host,
                'port': self.port,
                'load': len(self.chunks)
            }
            
            sock.send(json.dumps(message).encode())
    
    def _load_existing_chunks(self):
        for chunk_file in self.storage_dir.glob("*.chunk"):
            chunk_hash = chunk_file.stem
            self.chunks[chunk_hash] = str(chunk_file)
            self._update_dht_chunk_location(chunk_hash)
    
    def _update_dht_chunk_location(self, chunk_hash):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.connect((self.dht_host, self.dht_port))
            
            message = {
                'type': 'store_chunk',
                'chunk_hash': chunk_hash,
                'peer_id': self.peer_id,
                'host': self.host,
                'port': self.port
            }
            
            sock.send(json.dumps(message).encode())
    
    def _sync_videos_loop(self):
        while self.running:
            time.sleep(10)
            self._update_video_list()
    
    def _update_video_list(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.connect((self.dht_host, self.dht_port))
            
            message = {'type': 'get_videos'}
            sock.send(json.dumps(message).encode())
            response = self._receive_complete_message(sock)
            
            self.videos = response.get('videos', [])
    
    def get_chunk(self, chunk_hash: str) -> bytes:
        if chunk_hash in self.chunks:
            with open(self.chunks[chunk_hash], 'rb') as f:
                return f.read()
        
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.connect((self.dht_host, self.dht_port))
            
            message = {
                'type': 'find_chunk',
                'chunk_hash': chunk_hash
            }
            
            sock.send(json.dumps(message).encode())
            response = self._receive_complete_message(sock)
            
            for location in response.get('locations', []):
                if location['peer_id'] != self.peer_id:
                    chunk_data = self._request_chunk_from_peer(
                        chunk_hash, location['host'], location['port']
                    )
                    if chunk_data:
                        return chunk_data
        
        return None
    
    def _request_chunk_from_peer(self, chunk_hash, peer_host, peer_port):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.connect((peer_host, peer_port))
            
            message = {
                'type': 'get_chunk',
                'chunk_hash': chunk_hash
            }
            
            sock.send(json.dumps(message).encode())
            response = self._receive_complete_message(sock)
            
            if response.get('success'):
                return bytes.fromhex(response['chunk_data'])
        
        return None

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

    def get_stats(self):
        return {
            'peer_id': self.peer_id,
            'chunks': len(self.chunks),
            'videos': len(self.videos),
            'storage_dir': str(self.storage_dir)
        }