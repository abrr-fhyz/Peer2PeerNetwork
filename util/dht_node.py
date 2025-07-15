import hashlib
import json
import socket
import threading
import time
import logging
from typing import Dict, List
from dataclasses import dataclass

# -----------------------------
# Setup logging
# -----------------------------
logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
)

@dataclass
class ChunkLocation:
    peer_id: str
    host: str
    port: int

@dataclass
class VideoInfo:
    video_id: str
    filename: str
    chunk_hashes: List[str]
    total_size: int

class Redistributor:
    def __init__(self, replication_factor=2):
        self.replication_factor = replication_factor
    
    def determine_chunk_placement(self, chunk_hash: str, available_peers: List[dict]) -> List[str]:
        if not available_peers:
            logger.warning("[Redistributor] No available peers for chunk placement.")
            return []
        
        chunk_int = int(hashlib.md5(chunk_hash.encode()).hexdigest(), 16)
        peers_with_distance = []
        for peer in available_peers:
            peer_int = int(hashlib.md5(peer['peer_id'].encode()).hexdigest(), 16)
            distance = abs(chunk_int - peer_int)
            peers_with_distance.append((distance, peer['peer_id']))
        
        peers_with_distance.sort()
        selected = [peer_id for _, peer_id in peers_with_distance[:self.replication_factor]]

        logger.info(f"[Redistributor] Chunk {chunk_hash[:8]} placement decided: {selected}")
        return selected

class DHT:
    def __init__(self, host="localhost", port=8000):
        self.host = host
        self.port = port
        self.chunk_locations: Dict[str, List[ChunkLocation]] = {}
        self.peers: Dict[str, dict] = {}
        self.videos: Dict[str, VideoInfo] = {}
        self.redistributor = Redistributor()
        self.socket = None
        self.running = False

        logger.info(f"[DHT] Initialized on {self.host}:{self.port}")

    def start(self):
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.socket.bind((self.host, self.port))
        self.socket.listen(10)
        self.running = True
        threading.Thread(target=self._server_loop, daemon=True).start()

        logger.info(f"[DHT] Listening for connections on {self.host}:{self.port}")

    def stop(self):
        self.running = False
        if self.socket:
            self.socket.close()
        logger.info(f"[DHT] Stopped.")

    def _server_loop(self):
        while self.running:
            try:
                client, addr = self.socket.accept()
                logger.info(f"[DHT] Accepted connection from {addr}")
                threading.Thread(target=self._handle_client, args=(client,), daemon=True).start()
            except Exception as e:
                logger.error(f"[DHT] Server loop error: {e}")
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
            logger.info(f"[DHT] Received message: {message['type']}")
            response = self._process_message(message)
            client.send(json.dumps(response).encode())
        except Exception as e:
            logger.error(f"[DHT] Client handling error: {e}")
        finally:
            client.close()

    def _process_message(self, message):
        msg_type = message['type']
        
        if msg_type == 'register_peer':
            return self._register_peer(message)
        elif msg_type == 'add_video':
            return self._add_video(message)
        elif msg_type == 'get_videos':
            return self._get_videos()
        elif msg_type == 'get_video_chunks':
            return self._get_video_chunks(message)
        elif msg_type == 'store_chunk':
            return self._store_chunk_location(message)
        elif msg_type == 'find_chunk':
            return self._find_chunk_location(message)
        elif msg_type == 'get_placement':
            return self._get_chunk_placement(message)
        
        logger.warning(f"[DHT] Unknown message type: {msg_type}")
        return {'error': 'unknown_type'}

    def _register_peer(self, message):
        peer_id = message['peer_id']
        self.peers[peer_id] = {
            'host': message['host'],
            'port': message['port'],
            'load': message.get('load', 0)
        }
        logger.info(f"[DHT] Registered peer: {peer_id} at {message['host']}:{message['port']}")
        return {'success': True}

    def _add_video(self, message):
        video_id = message['video_id']
        filename = message.get('filename', 'unknown')
        chunk_hashes = message.get('chunk_hashes', [])

        video_info = VideoInfo(video_id, filename, chunk_hashes, len(chunk_hashes))
        self.videos[video_id] = video_info

        logger.info(f"[DHT] Added video: {filename} | ID: {video_id} | Chunks: {len(chunk_hashes)}")

        available_peers = []
        for peer_id, peer_data in self.peers.items():
            peer_copy = peer_data.copy()
            peer_copy['peer_id'] = peer_id
            available_peers.append(peer_copy)

        for chunk_hash in chunk_hashes:
            target_peers = self.redistributor.determine_chunk_placement(chunk_hash, available_peers)

            for peer_id in target_peers:
                if peer_id in self.peers:
                    peer = self.peers[peer_id]
                    location = ChunkLocation(peer_id, peer['host'], peer['port'])

                    if chunk_hash not in self.chunk_locations:
                        self.chunk_locations[chunk_hash] = []
                    self.chunk_locations[chunk_hash].append(location)

                    logger.info(f"[DHT] Mapped chunk {chunk_hash[:8]} to peer {peer_id}")

        return {'success': True}

    def _get_videos(self):
        logger.info(f"[DHT] Returning list of {len(self.videos)} videos.")
        return {
            'videos': [
                {
                    'video_id': v.video_id,
                    'filename': v.filename,
                    'chunks': len(v.chunk_hashes),
                    'total_size': v.total_size
                }
                for v in self.videos.values()
            ]
        }

    def _get_video_chunks(self, message):
        video_id = message['video_id']
        logger.info(f"[DHT] Get chunks for video_id: {video_id}")

        if video_id in self.videos:
            return {'chunk_hashes': self.videos[video_id].chunk_hashes}
        logger.warning(f"[DHT] Video ID {video_id} not found.")
        return {'chunk_hashes': []}

    def _store_chunk_location(self, message):
        chunk_hash = message['chunk_hash']
        location = ChunkLocation(
            peer_id=message['peer_id'],
            host=message['host'],
            port=message['port']
        )

        if chunk_hash not in self.chunk_locations:
            self.chunk_locations[chunk_hash] = []

        self.chunk_locations[chunk_hash] = [
            loc for loc in self.chunk_locations[chunk_hash]
            if loc.peer_id != message['peer_id']
        ]
        self.chunk_locations[chunk_hash].append(location)

        logger.info(f"[DHT] Stored/Updated location for chunk {chunk_hash[:8]} from peer {message['peer_id']}")
        return {'success': True}

    def _find_chunk_location(self, message):
        chunk_hash = message['chunk_hash']
        locations = self.chunk_locations.get(chunk_hash, [])

        logger.info(f"[DHT] Found {len(locations)} locations for chunk {chunk_hash[:8]}")
        return {
            'locations': [
                {'peer_id': loc.peer_id, 'host': loc.host, 'port': loc.port}
                for loc in locations
            ]
        }

    def _get_chunk_placement(self, message):
        chunk_hash = message['chunk_hash']

        available_peers = []
        for peer_id, peer_data in self.peers.items():
            peer_copy = peer_data.copy()
            peer_copy['peer_id'] = peer_id
            available_peers.append(peer_copy)

        target_peers = self.redistributor.determine_chunk_placement(chunk_hash, available_peers)

        logger.info(f"[DHT] Placement for chunk {chunk_hash[:8]} => {target_peers}")

        return {
            'target_peers': [
                {'peer_id': pid, 'host': self.peers[pid]['host'], 'port': self.peers[pid]['port']}
                for pid in target_peers if pid in self.peers
            ]
        }

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description='Run DHT node')
    parser.add_argument('--host', default='localhost', help='Host to bind to')
    parser.add_argument('--port', type=int, default=8000, help='Port to bind to')
    args = parser.parse_args()

    logger.info(f"Starting DHT node on {args.host}:{args.port}")
    dht = DHT(host=args.host, port=args.port)
    dht.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Shutting down DHT node...")
        dht.stop()
