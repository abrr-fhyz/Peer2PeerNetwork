import logging
from fastapi import FastAPI, Response, Request, UploadFile, File
from fastapi.responses import StreamingResponse, HTMLResponse
from pathlib import Path
import tempfile
import asyncio
import os
import json
import socket
from typing import Dict
from util.file_processor import FileProcessor
import threading
import time

# -----------------------------
# Setup logging
# -----------------------------
logger = logging.getLogger("streaming_server")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
)

app = FastAPI()
file_processor = FileProcessor()

# Global storage for active streams
active_streams: Dict[str, dict] = {}

@app.get("/", response_class=HTMLResponse)
async def home():
    return load_html()

@app.get("/api/videos")
async def list_videos():
    logger.info("[API] Listing videos from DHT...")
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.connect((HOST_IP, 8000))
            message = {'type': 'get_videos'}
            sock.send(json.dumps(message).encode())
            
            data = b''
            while True:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                data += chunk
                try:
                    response = json.loads(data.decode())
                    break
                except json.JSONDecodeError:
                    continue

        return response.get('videos', [])
    except Exception as e:
        logger.error(f"[API] Error getting videos: {e}")
        return []

@app.get("/api/stream-status/{video_id}")
async def get_stream_status(video_id: str):
    """Get current streaming status for a video"""
    if video_id not in active_streams:
        return {"ready": False, "progress": 0, "downloaded": 0, "total": 0}
    
    stream_info = active_streams[video_id]
    downloaded_count = len(stream_info.get('downloaded_chunks', []))
    total_count = len(stream_info.get('chunk_hashes', []))
    progress = (downloaded_count / total_count) * 100 if total_count > 0 else 0
    
    # Ready when we have minimum buffer
    min_buffer = 3
    ready = downloaded_count >= min_buffer
    
    return {
        "ready": ready,
        "progress": progress,
        "downloaded": downloaded_count,
        "total": total_count,
        "file_size": stream_info.get('final_size', stream_info.get('assembled_size', 0)),
        "current_size": stream_info.get('assembled_size', 0)
    }

@app.head("/stream/{video_id}")
async def stream_video_head(video_id: str):
    """Initialize stream and start background download"""
    logger.info(f"[Stream] HEAD request - initializing {video_id}")
    
    if video_id not in active_streams:
        await initialize_stream(video_id)
        
        # Start download in background thread
        stream_info = active_streams[video_id]
        if not stream_info.get('download_started', False):
            stream_info['download_started'] = True
            
            download_thread = threading.Thread(
                target=start_background_download, 
                args=(video_id,), 
                daemon=True
            )
            download_thread.start()
            logger.info(f"[Stream] Background download thread started for {video_id}")
    
    # Return proper headers for video
    stream_info = active_streams[video_id]
    final_size = stream_info.get('final_size', 0)
    
    return Response(
        status_code=200, 
        headers={
            "Accept-Ranges": "bytes",
            "Content-Type": "video/mp4",
            "Content-Length": str(final_size) if final_size > 0 else "0"
        }
    )

def start_background_download(video_id: str):
    """Start download in separate thread to avoid blocking"""
    logger.info(f"[Background] Download thread starting for {video_id}")
    
    stream_info = active_streams[video_id]
    chunk_hashes = stream_info['chunk_hashes']
    
    # Calculate expected final size
    expected_size = len(chunk_hashes) * 1024 * 1024  # Estimate: 1MB per chunk
    stream_info['final_size'] = expected_size
    
    for i, chunk_hash in enumerate(chunk_hashes):
        try:
            logger.info(f"[Background] Downloading chunk {i+1}/{len(chunk_hashes)}")
            chunk_data = download_chunk_sync(chunk_hash)
            
            if chunk_data:
                # Write chunk immediately to specific position
                stream_info['temp_file'].write(chunk_data)
                stream_info['temp_file'].flush()
                
                # Update tracking
                stream_info['downloaded_chunks'].append(i)
                stream_info['assembled_size'] += len(chunk_data)
                
                # Update final size with actual data
                if i == len(chunk_hashes) - 1:  # Last chunk
                    stream_info['final_size'] = stream_info['assembled_size']
                    logger.info(f"[Background] Final size set to {stream_info['final_size']} bytes")
                
                logger.info(f"[Background] ✅ Chunk {i+1} written | Current size: {stream_info['assembled_size']} bytes")
                
                # Log when ready for playback
                if len(stream_info['downloaded_chunks']) == 3:
                    logger.info(f"[Background] 🎬 PLAYBACK READY! Stream can start now!")
                    
        except Exception as e:
            logger.error(f"[Background] Error downloading chunk {i}: {e}")
    
    logger.info(f"[Background] Download complete for {video_id}")

def download_chunk_sync(chunk_hash: str):
    """Synchronous chunk download for background thread"""
    try:
        # Get chunk location from DHT
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.connect((HOST_IP, 8000))
            message = {'type': 'find_chunk', 'chunk_hash': chunk_hash}
            sock.send(json.dumps(message).encode())
            
            data = b''
            while True:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                data += chunk
                try:
                    response = json.loads(data.decode())
                    break
                except json.JSONDecodeError:
                    continue
        
        locations = response.get('locations', [])
        
        # Try to get chunk from each location
        for location in locations:
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as peer_sock:
                    peer_sock.connect((location['host'], location['port']))
                    message = {'type': 'get_chunk', 'chunk_hash': chunk_hash}
                    peer_sock.send(json.dumps(message).encode())
                    
                    data = b''
                    while True:
                        chunk = peer_sock.recv(4096)
                        if not chunk:
                            break
                        data += chunk
                        try:
                            response = json.loads(data.decode())
                            if response.get('success'):
                                return bytes.fromhex(response['chunk_data'])
                            break
                        except json.JSONDecodeError:
                            continue
                            
            except Exception as e:
                continue
        
        return None
        
    except Exception as e:
        logger.error(f"[Background] Error getting chunk {chunk_hash[:8]}: {e}")
        return None

@app.get("/stream/{video_id}")
async def stream_video(video_id: str, request: Request):
    logger.info(f"[Stream] GET request for {video_id}")
    
    if video_id not in active_streams:
        logger.error(f"[Stream] Video {video_id} not initialized")
        return Response(status_code=404)
    
    stream_info = active_streams[video_id]
    
    # Handle range requests FIRST (this is critical for seeking)
    range_header = request.headers.get('range')
    if range_header:
        logger.info(f"[Stream] Range request: {range_header}")
        return await handle_range_request_fixed(video_id, range_header)
    
    # For non-range requests, wait for minimal buffer
    max_wait = 30  # 30 seconds max
    wait_count = 0
    
    while len(stream_info['downloaded_chunks']) < 3 and wait_count < max_wait * 10:
        await asyncio.sleep(0.1)
        wait_count += 1
    
    if len(stream_info['downloaded_chunks']) < 3:
        logger.error(f"[Stream] Timeout waiting for buffer")
        return Response(status_code=408)
    
    logger.info(f"[Stream] Starting full progressive stream for {video_id}")
    
    # Return full progressive stream
    return StreamingResponse(
        generate_progressive_stream_fixed(video_id),
        media_type="video/mp4",
        headers={
            "Accept-Ranges": "bytes",
            "Cache-Control": "no-cache",
            "Content-Length": str(stream_info.get('final_size', 0))
        }
    )

async def initialize_stream(video_id: str):
    """Initialize streaming for a video"""
    logger.info(f"[Stream] Initializing {video_id}")
    
    try:
        # Get chunk information from DHT
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.connect((HOST_IP, 8000))
            message = {'type': 'get_video_chunks', 'video_id': video_id}
            sock.send(json.dumps(message).encode())
            
            data = b''
            while True:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                data += chunk
                try:
                    response = json.loads(data.decode())
                    break
                except json.JSONDecodeError:
                    continue
        
        chunk_hashes = response.get('chunk_hashes', [])
        if not chunk_hashes:
            raise Exception("No chunks found")
        
        # Create temporary file
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.mp4')
        
        # Initialize stream info
        active_streams[video_id] = {
            'temp_file': temp_file,
            'chunk_hashes': chunk_hashes,
            'downloaded_chunks': [],
            'assembled_size': 0,
            'final_size': 0,  # Will be set when download completes
            'download_started': False
        }
        
        logger.info(f"[Stream] Initialized {video_id} with {len(chunk_hashes)} chunks")
        
    except Exception as e:
        logger.error(f"[Stream] Failed to initialize {video_id}: {e}")
        raise

async def handle_range_request_fixed(video_id: str, range_header: str):
    """FIXED: Handle range requests properly for seeking"""
    stream_info = active_streams[video_id]
    temp_path = stream_info['temp_file'].name
    
    # Parse range header
    try:
        ranges = range_header.replace('bytes=', '')
        start_end = ranges.split('-')
        start = int(start_end[0]) if start_end[0] else 0
        
        # Wait for file to have content at the requested position
        max_wait_time = 10  # 10 seconds max wait
        wait_start = time.time()
        
        while time.time() - wait_start < max_wait_time:
            current_size = stream_info['assembled_size']
            if current_size > start:
                break
            await asyncio.sleep(0.1)
        
        # Get current file size
        current_size = stream_info['assembled_size']
        final_size = stream_info.get('final_size', current_size)
        
        # If requesting beyond available data, return what we have
        if start >= current_size:
            logger.warning(f"[Stream] Range request beyond available data: {start} >= {current_size}")
            return Response(status_code=416)  # Range not satisfiable
        
        # Calculate end position
        if len(start_end) > 1 and start_end[1]:
            end = min(int(start_end[1]), current_size - 1)
        else:
            end = current_size - 1
        
        logger.info(f"[Stream] Serving range {start}-{end}/{final_size} (available: {current_size})")
        
        async def generate_range_fixed():
            with open(temp_path, 'rb') as f:
                f.seek(start)
                remaining = end - start + 1
                
                while remaining > 0:
                    chunk_size = min(8192, remaining)
                    data = f.read(chunk_size)
                    if not data:
                        # If we run out of data, wait a bit for more chunks
                        await asyncio.sleep(0.1)
                        continue
                    remaining -= len(data)
                    yield data
        
        return StreamingResponse(
            generate_range_fixed(),
            status_code=206,
            media_type="video/mp4",
            headers={
                "Content-Range": f"bytes {start}-{end}/{final_size}",
                "Accept-Ranges": "bytes",
                "Content-Length": str(end - start + 1)
            }
        )
        
    except Exception as e:
        logger.error(f"[Stream] Range request error: {e}")
        return Response(status_code=416)

async def generate_progressive_stream_fixed(video_id: str):
    """FIXED: Generate progressive stream with proper size handling"""
    logger.info(f"[Stream] Starting progressive generation for {video_id}")
    
    stream_info = active_streams[video_id]
    temp_path = stream_info['temp_file'].name
    
    bytes_sent = 0
    
    with open(temp_path, 'rb') as f:
        while True:
            # Read available data
            data = f.read(8192)
            if data:
                yield data
                bytes_sent += len(data)
                
                if bytes_sent % (1024 * 1024) == 0:  # Log every MB
                    logger.info(f"[Stream] Streamed {bytes_sent // 1024 // 1024}MB")
            else:
                # Check if download is complete
                if len(stream_info['downloaded_chunks']) >= len(stream_info['chunk_hashes']):
                    logger.info(f"[Stream] Progressive stream complete for {video_id} | Total: {bytes_sent} bytes")
                    break
                
                # Wait for more data
                await asyncio.sleep(0.1)

@app.post("/upload")
async def upload_video(file: UploadFile = File(...)):
    logger.info(f"[Upload] Upload started for {file.filename}")
    temp_path = f"temp_{file.filename}"
    
    try:
        # Save uploaded file
        with open(temp_path, "wb") as f:
            content = await file.read()
            f.write(content)
        
        logger.info(f"[Upload] File saved: {temp_path} ({len(content)} bytes)")

        # Process video into chunks
        metadata = file_processor.process_video(temp_path)
        logger.info(f"[Upload] Processed: {metadata.filename} with {len(metadata.chunks)} chunks")

        # Register with DHT
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.connect((HOST_IP, 8000))
            message = {
                'type': 'add_video',
                'video_id': metadata.video_id,
                'filename': metadata.filename,
                'chunk_hashes': [chunk['hash'] for chunk in metadata.chunks]
            }
            sock.send(json.dumps(message).encode())
            
            # Wait for DHT response
            data = b''
            while True:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                data += chunk
                try:
                    response = json.loads(data.decode())
                    logger.info(f"[Upload] DHT registration: {response}")
                    break
                except json.JSONDecodeError:
                    continue

        # Distribute chunks to peers
        await distribute_chunks_to_peers(metadata)
        
        logger.info(f"[Upload] Upload complete for {metadata.video_id}")
        return {"status": "success", "video_id": metadata.video_id, "filename": metadata.filename}
        
    except Exception as e:
        logger.error(f"[Upload] Upload failed: {e}")
        return {"status": "error", "message": str(e)}
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)

async def distribute_chunks_to_peers(metadata):
    """Distribute chunks to available peers"""
    logger.info(f"[Upload] Distributing {len(metadata.chunks)} chunks to peers")
    
    distributed_count = 0
    for i, chunk_info in enumerate(metadata.chunks):
        chunk_data = file_processor.get_chunk_data(metadata.video_id, chunk_info['index'])
        if not chunk_data:
            continue
            
        try:
            # Get placement from DHT
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.connect((HOST_IP, 8000))
                message = {
                    'type': 'get_placement',
                    'chunk_hash': chunk_info['hash']
                }
                sock.send(json.dumps(message).encode())
                
                data = b''
                while True:
                    chunk = sock.recv(4096)
                    if not chunk:
                        break
                    data += chunk
                    try:
                        response = json.loads(data.decode())
                        break
                    except json.JSONDecodeError:
                        continue
            
            # Send to target peers
            target_peers = response.get('target_peers', [])
            for target_peer in target_peers:
                try:
                    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as peer_sock:
                        peer_sock.connect((target_peer['host'], target_peer['port']))
                        message = {
                            'type': 'store_chunk',
                            'chunk_hash': chunk_info['hash'],
                            'chunk_data': chunk_data.hex()
                        }
                        peer_sock.send(json.dumps(message).encode())
                        
                        # Wait for response
                        response_data = peer_sock.recv(1024)
                        if response_data:
                            distributed_count += 1
                            
                except Exception as e:
                    logger.warning(f"[Upload] Failed to send chunk to {target_peer}: {e}")
                    
        except Exception as e:
            logger.error(f"[Upload] Error distributing chunk {i}: {e}")
    
    logger.info(f"[Upload] Distributed {distributed_count}/{len(metadata.chunks)} chunks")

def load_html():
    try:
        with open("layout/home.html", "r") as f:
            return f.read()
    except FileNotFoundError:
        return "<div>Home HTML not found</div>"

if __name__ == "__main__":
    import uvicorn
    from dotenv import load_dotenv
    import os
    
    load_dotenv()
    
    HOST_IP = os.getenv("HOST_IP", "localhost")
    API_PORT = int(os.getenv("API_PORT", "8080"))
        
    logger.info("[Server] Starting FIXED seeking progressive streaming server...")
    uvicorn.run(app, host=HOST_IP, port=API_PORT)