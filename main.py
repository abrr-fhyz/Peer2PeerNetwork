import os
import time
import threading
import subprocess
from pathlib import Path
import streamlit as st
import socket
import json
import requests  # FIX: Add requests import
from file_processor import FileProcessor
from dht_node import DHT
from peer_node import Peer

# Configuration
VIDEO_FILE = "sample_vid_medium.mp4"
OUTPUT_DIR = "processed_videos"
CHUNK_SIZE = 1024 * 1024  # 1MB chunks
MIN_BUFFER_CHUNKS = 5  # Start playback after this many chunks are buffered

class VideoStreamer:
    def __init__(self):
        self.file_processor = FileProcessor(chunk_size=CHUNK_SIZE)
        Path(OUTPUT_DIR).mkdir(exist_ok=True)
        
    def prepare_video(self):
        """Process video into streamable chunks with proper MP4 metadata"""
        if not os.path.exists(VIDEO_FILE):
            return None

        # First ensure moov atom is at the front
        processed_path = self.file_processor.ensure_mp4_metadata_at_front(VIDEO_FILE)

        # Process into properly formatted chunks
        metadata = self.file_processor.process_video(processed_path)

        # Generate init segment for fragmented streaming
        init_segment = self.file_processor.generate_init_segment(processed_path)
        if init_segment:
            with open(Path(OUTPUT_DIR) / f"{metadata.video_id}_init.mp4", "wb") as f:
                f.write(init_segment)

        return metadata

    def distribute_chunks(self, metadata):
        """Register and distribute chunks to peers"""
        try:
            print(f"Registering video {metadata.video_id} with DHT...")

            # STEP 1: Register video with DHT (FIXED)
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.connect(("localhost", 8000))
                message = {
                    'type': 'add_video',
                    'video_id': metadata.video_id,
                    'filename': metadata.filename,
                    'chunk_hashes': [chunk['hash'] for chunk in metadata.chunks]
                }
                sock.send(json.dumps(message).encode())

                # FIX: Wait for and read the response properly
                data = b''
                while True:
                    chunk = sock.recv(4096)
                    if not chunk:
                        break
                    data += chunk
                    try:
                        response = json.loads(data.decode())
                        print(f"DHT registration response: {response}")
                        break
                    except json.JSONDecodeError:
                        continue

            print("✅ Video registered with DHT!")

            # STEP 2: Distribute chunks to peers
            print(f"Distributing {len(metadata.chunks)} chunks to peers...")
            distributed_count = 0

            for i, chunk_info in enumerate(metadata.chunks):
                print(f"Processing chunk {i+1}/{len(metadata.chunks)}: {chunk_info['hash'][:8]}...")

                # Get chunk data
                chunk_data = self.file_processor.get_chunk_data(metadata.video_id, chunk_info['index'])
                if not chunk_data:
                    print(f"❌ Could not get chunk data for chunk {i}")
                    continue

                # FIX: Get placement in separate socket connection
                try:
                    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                        sock.connect(("localhost", 8000))
                        message = {
                            'type': 'get_placement',
                            'chunk_hash': chunk_info['hash']
                        }
                        sock.send(json.dumps(message).encode())

                        # FIX: Properly read the placement response
                        data = b''
                        while True:
                            chunk = sock.recv(4096)
                            if not chunk:
                                break
                            data += chunk
                            try:
                                placement_response = json.loads(data.decode())
                                break
                            except json.JSONDecodeError:
                                continue

                    target_peers = placement_response.get('target_peers', [])
                    print(f"  Placement response: {len(target_peers)} target peers")

                    # FIX: Send chunk to each target peer
                    chunk_distributed = False
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

                                # FIX: Wait for peer response
                                try:
                                    peer_response = peer_sock.recv(1024)
                                    response_data = json.loads(peer_response.decode())
                                    if response_data.get('success'):
                                        print(f"  ✅ Chunk stored on peer {target_peer['peer_id']}")
                                        chunk_distributed = True
                                    else:
                                        print(f"  ❌ Peer {target_peer['peer_id']} rejected chunk")
                                except:
                                    print(f"  ⚠️ No response from peer {target_peer['peer_id']}")
                                    chunk_distributed = True  # Assume success

                        except Exception as e:
                            print(f"  ❌ Failed to send chunk to peer {target_peer.get('peer_id', 'unknown')}: {e}")

                    if chunk_distributed:
                        distributed_count += 1

                except Exception as e:
                    print(f"❌ Failed to get placement for chunk {i}: {e}")
                    continue

            print(f"✅ Distribution complete! {distributed_count}/{len(metadata.chunks)} chunks distributed")
            return distributed_count

        except Exception as e:
            print(f"❌ Error in distribute_chunks: {e}")
            import traceback
            traceback.print_exc()
            return 0

def run_dht_node():
    dht = DHT(host="localhost", port=8000)
    dht.start()
    return dht

def run_peer_node(port):
    peer = Peer(host="localhost", port=port, dht_host="localhost", dht_port=8000)
    peer.start()
    return peer

# FIX 1: Add function to check if streaming server is running
def check_streaming_server():
    """Check if streaming server is available"""
    try:
        response = requests.get("http://localhost:8080/api/videos", timeout=2)
        return response.status_code == 200
    except:
        return False

# FIX 2: Add function to get video list from streaming server
def get_videos_from_server():
    """Get videos from streaming server"""
    try:
        response = requests.get("http://localhost:8080/api/videos", timeout=5)
        if response.status_code == 200:
            return response.json()
    except:
        pass
    return []

# FIX 3: Add function to get streaming status
def get_streaming_status(video_id):
    """Get streaming status for a video"""
    try:
        response = requests.get(f"http://localhost:8080/api/stream-status/{video_id}", timeout=2)
        if response.status_code == 200:
            return response.json()
    except:
        pass
    return {"ready": False, "progress": 0, "downloaded": 0, "total": 0}

# NEW: Add function to trigger stream
def trigger_stream(video_id):
    """Trigger stream initialization by sending HEAD request"""
    try:
        response = requests.head(f"http://localhost:8080/stream/{video_id}", timeout=10)
        return response.status_code in [200, 206]  # Accept both OK and Partial Content
    except Exception as e:
        print(f"Failed to trigger stream: {e}")
        return False

def main():
    st.title("NetFlacks P2P Video Streaming")

    # Initialize components
    if 'components_started' not in st.session_state:
        with st.spinner("Starting P2P services..."):
            st.session_state.dht = run_dht_node()
            time.sleep(1)
            st.session_state.peer1 = run_peer_node(9001)
            st.session_state.peer2 = run_peer_node(9002)
            st.session_state.streamer = VideoStreamer()
            st.session_state.components_started = True
            time.sleep(2)
            st.success("✅ P2P services started!")

    # FIX 4: Check streaming server status
    server_running = check_streaming_server()
    if server_running:
        st.success("🌐 Streaming server is running")
    else:
        st.warning("⚠️ Streaming server not detected. Start it with: `python streaming_server.py`")

    # Video processing
    if st.button("Prepare Video for Streaming"):
        with st.spinner("Preparing video chunks..."):
            metadata = st.session_state.streamer.prepare_video()
            if metadata:
                st.session_state.video_metadata = metadata
                st.success(f"Video ready! ID: {metadata.video_id}")

                # Distribute chunks
                with st.spinner("Distributing chunks to peers..."):
                    st.session_state.streamer.distribute_chunks(metadata)
                    st.success("Chunks distributed to peers!")

    # FIX 5: Enhanced video library section
    st.header("🎥 Video Library")

    # Get videos from server if available, otherwise from DHT
    if server_running:
        videos = get_videos_from_server()
    else:
        # Fallback to DHT query
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.connect(("localhost", 8000))
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
                        videos = response.get('videos', [])
                        break
                    except json.JSONDecodeError:
                        continue
        except:
            videos = []

    if not videos:
        st.info("📂 No videos available. Upload or prepare a video first!")
    else:
        for video in videos:
            video_id = video['video_id']

            with st.container():
                col1, col2, col3 = st.columns([3, 1, 1])

                with col1:
                    st.write(f"**{video['filename']}**")
                    st.write(f"Chunks: {video['chunks']} | ID: {video_id[:12]}...")

                with col2:
                    # FIX 6: Show streaming status
                    if server_running:
                        status = get_streaming_status(video_id)
                        if status["ready"]:
                            st.success("🟢 Ready")
                        elif status["downloaded"] > 0:
                            progress = status.get("progress", 0)
                            st.info(f"🔄 {progress:.0f}%")
                        else:
                            st.info("⚪ Not streaming")
                    else:
                        st.info("⚪ Server offline")

                with col3:
                    # MAJOR FIX: Enhanced play button with stream triggering
                    if st.button("▶️ Play", key=f"play_{video_id}"):
                        if server_running:
                            st.session_state[f"streaming_{video_id}"] = True
                            
                            # CRITICAL: Trigger the stream immediately
                            with st.spinner("Initializing stream..."):
                                if trigger_stream(video_id):
                                    st.success("✅ Stream started!")
                                else:
                                    st.error("❌ Failed to start stream")
                                    st.session_state[f"streaming_{video_id}"] = False
                        else:
                            st.error("Streaming server not available")

                # MAJOR FIX: Progressive streaming player with proper monitoring
                if st.session_state.get(f"streaming_{video_id}", False) and server_running:
                    st.write("**🎬 Progressive Streaming Player**")

                    # Create containers for status updates
                    status_container = st.container()
                    video_container = st.container()
                    
                    with status_container:
                        status_placeholder = st.empty()
                        progress_placeholder = st.empty()

                    # Monitor buffering with improved logic
                    max_checks = 30  # Check for up to 30 seconds
                    checks_done = 0
                    stream_ready = False
                    
                    # Get initial status
                    status = get_streaming_status(video_id)
                    
                    if status["ready"]:
                        # Stream is already ready
                        stream_ready = True
                    else:
                        # Monitor until ready or timeout
                        for check in range(max_checks):
                            status = get_streaming_status(video_id)
                            
                            if status["ready"]:
                                stream_ready = True
                                break
                            else:
                                # Show buffering progress
                                progress = status.get("progress", 0)
                                downloaded = status.get("downloaded", 0)
                                total = status.get("total", 0)
                                
                                if total > 0:
                                    status_placeholder.info(f"📡 Buffering: {downloaded}/{total} chunks ({progress:.1f}%)")
                                    progress_placeholder.progress(progress / 100)
                                else:
                                    status_placeholder.warning("🔄 Initializing stream...")
                                
                                time.sleep(1)
                        
                        if not stream_ready:
                            status_placeholder.error("❌ Stream timeout - try again")
                            st.session_state[f"streaming_{video_id}"] = False
                    
                    # Show video player if stream is ready
                    if stream_ready:
                        status_placeholder.success("✅ Stream ready! Starting playback...")
                        progress_placeholder.empty()
                        
                        with video_container:
                            streaming_url = f"http://localhost:8080/stream/{video_id}"
                            st.video(streaming_url)

                            # Add control buttons
                            col_stop, col_download = st.columns([1, 1])
                            
                            with col_stop:
                                if st.button("⏹️ Stop", key=f"stop_{video_id}"):
                                    st.session_state[f"streaming_{video_id}"] = False
                                    st.rerun()
                            
                            with col_download:
                                if st.button("📥 Download", key=f"download_{video_id}"):
                                    st.info("Download feature - check server logs")

                st.divider()

    # Debug section (add this for testing)
    with st.expander("🔧 Debug Tools"):
        if st.button("Test Stream Connection"):
            if server_running:
                test_video_id = st.text_input("Video ID to test:", value="326abb8c59790979" if videos else "")
                if test_video_id and st.button("Send Test Request"):
                    try:
                        response = requests.head(f"http://localhost:8080/stream/{test_video_id}", timeout=5)
                        st.write(f"Response: {response.status_code}")
                        
                        # Check status after triggering
                        time.sleep(2)
                        status = get_streaming_status(test_video_id)
                        st.write(f"Status: {status}")
                    except Exception as e:
                        st.error(f"Test failed: {e}")
            else:
                st.error("Streaming server not running")

    # FIX 9: Manual streaming section (fallback)
    if 'video_metadata' in st.session_state and not server_running:
        st.header("🔧 Manual Streaming (Server Offline)")
        video_id = st.session_state.video_metadata.video_id

        if st.button("🔄 Assemble & Play Video"):
            with st.spinner("Assembling video from chunks..."):
                try:
                    # Get chunk list from DHT
                    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                        sock.connect(("localhost", 8000))
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

                    if chunk_hashes:
                        # Create temporary peer for downloading
                        peer = Peer(host="localhost", port=9999, dht_host="localhost", dht_port=8000)
                        peer.start()

                        try:
                            # Download and assemble chunks
                            assembled_file = Path(OUTPUT_DIR) / f"{video_id}_assembled.mp4"
                            progress_bar = st.progress(0)
                            status_text = st.empty()

                            with open(assembled_file, "wb") as f:
                                for i, chunk_hash in enumerate(chunk_hashes):
                                    status_text.text(f"Downloading chunk {i+1}/{len(chunk_hashes)}")

                                    chunk_data = peer.get_chunk(chunk_hash)
                                    if chunk_data:
                                        f.write(chunk_data)
                                        progress_bar.progress((i + 1) / len(chunk_hashes))
                                    else:
                                        st.error(f"Failed to get chunk {i+1}")
                                        break

                            status_text.success("✅ Video assembled!")

                            # Play assembled video
                            with open(assembled_file, "rb") as f:
                                video_bytes = f.read()
                            st.video(video_bytes)

                        finally:
                            peer.stop()
                    else:
                        st.error("No chunks found for this video")

                except Exception as e:
                    st.error(f"Failed to assemble video: {e}")

if __name__ == "__main__":
    main()