import os
import time
from pathlib import Path
import streamlit as st
import socket
import json
import requests
from util.file_processor import FileProcessor
from util.dht_node import DHT
from util.peer_node import Peer
from util.peer_controller import PeerController

# Configuration
HOST_IP = "localhost" 
OUTPUT_DIR = "processed_videos"
CHUNK_SIZE = 1024 * 1024  # 1MB chunks
MIN_BUFFER_CHUNKS = 5 

def load_css():
    """Load CSS from external file"""
    try:
        with open("layout/styles.css", "r") as f:
            return f"<style>{f.read()}</style>"
    except FileNotFoundError:
        return "<style>/* CSS file not found */</style>"

def load_upload_section_html():
    """Load upload section HTML from external file"""
    try:
        with open("layout/upload_section.html", "r") as f:
            return f.read()
    except FileNotFoundError:
        return "<div>Upload section HTML not found</div>"

# Streamlit page config
st.set_page_config(
    page_title="NetFlacks P2P Video Streaming",
    page_icon="🎬",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Load and apply external CSS
st.markdown(load_css(), unsafe_allow_html=True)

class VideoStreamer:
    def __init__(self):
        self.file_processor = FileProcessor(chunk_size=CHUNK_SIZE)
        Path(OUTPUT_DIR).mkdir(exist_ok=True)

def check_streaming_server():
    """Check if streaming server is available"""
    try:
        response = requests.get(f"http://{HOST_IP}:8080/api/videos", timeout=2)
        return response.status_code == 200
    except:
        return False

def get_videos_from_server():
    """Get videos from streaming server"""
    try:
        response = requests.get(f"http://{HOST_IP}:8080/api/videos", timeout=5)
        if response.status_code == 200:
            return response.json()
    except:
        pass
    return []

def get_streaming_status(video_id):
    """Get streaming status for a video"""
    try:
        response = requests.get(f"http://{HOST_IP}:8080/api/stream-status/{video_id}", timeout=2)
        if response.status_code == 200:
            return response.json()
    except:
        pass
    return {"ready": False, "progress": 0, "downloaded": 0, "total": 0}

def trigger_stream(video_id):
    """Trigger stream initialization by sending HEAD request"""
    try:
        response = requests.head(f"http://{HOST_IP}:8080/stream/{video_id}", timeout=10)
        return response.status_code in [200, 206]
    except Exception as e:
        print(f"Failed to trigger stream: {e}")
        return False

def upload_video_to_server(uploaded_file):
    """Upload video file to streaming server"""
    try:
        files = {"file": (uploaded_file.name, uploaded_file.getvalue(), uploaded_file.type)}
        response = requests.post(f"http://{HOST_IP}:8080/upload", files=files, timeout=300)  # 5 min timeout
        
        if response.status_code == 200:
            return response.json()
        else:
            return {"status": "error", "message": f"Server returned {response.status_code}"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

def main():
    st.title("🎬 NetFlacks P2P Video Streaming Platform")
    
    # Sidebar for system status
    with st.sidebar:
        st.header("🔧 System Status")
        
        # Initialize components using PeerController
        if 'peer_controller' not in st.session_state:
            with st.spinner("Starting P2P services..."):
                try:
                    # Use PeerController to manage single peer
                    st.session_state.peer_controller = PeerController(
                        peer_host=HOST_IP, 
                        peer_port=9001,  # Single peer on port 9001
                        dht_host=HOST_IP, 
                        dht_port=8000
                    )
                    st.session_state.peer_controller.start_services()
                    st.session_state.streamer = VideoStreamer()
                    st.session_state.components_started = True
                    time.sleep(2)
                    st.success("✅ P2P services started!")
                except Exception as e:
                    st.error(f"❌ Failed to start services: {e}")
                    st.session_state.components_started = False

        # Check streaming server status
        server_running = check_streaming_server()
        if server_running:
            st.success("🌐 Streaming server is running")
        else:
            st.error("❌ Streaming server offline")
            st.write("Start with: `python streaming_server.py`")
        
        # System info
        if st.session_state.get('components_started', False):
            st.info("📡 DHT Node: Active")
            st.info("🔗 Peer Node: 1 active (discovering others)")
        
        if st.button("🔄 Refresh Status"):
            st.rerun()

    # Main content tabs
    tab1, tab2, tab3 = st.tabs(["🎥 Video Library", "📤 Upload Video", "🔧 Debug Tools"])
    
    # Tab 1: Video Library
    with tab1:
        st.header("🎥 Video Library")
        
        # Get videos from server or DHT
        if server_running:
            videos = get_videos_from_server()
        else:
            videos = []
            if st.session_state.get('peer_controller'):
                try:
                    # Use peer_controller's list_videos method
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
                                videos = response.get('videos', [])
                                break
                            except json.JSONDecodeError:
                                continue
                except Exception as e:
                    st.error(f"Failed to get videos from DHT: {e}")
        
        if not videos:
            st.info("📂 No videos available. Upload a video to get started!")
        else:
            for video in videos:
                video_id = video['video_id']
                
                with st.container():
                    col1, col2, col3 = st.columns([3, 1, 1])
                    
                    with col1:
                        st.write(f"**{video['filename']}**")
                        st.write(f"Chunks: {video['chunks']} | ID: {video_id[:12]}...")
                    
                    with col2:
                        # Show streaming status
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
                            st.warning("⚪ Server offline")
                    
                    with col3:
                        # Play button
                        if st.button("▶️ Play", key=f"play_{video_id}"):
                            if server_running:
                                st.session_state[f"streaming_{video_id}"] = True
                                
                                # Trigger the stream
                                with st.spinner("Initializing stream..."):
                                    if trigger_stream(video_id):
                                        st.success("✅ Stream started!")
                                    else:
                                        st.error("❌ Failed to start stream")
                                        st.session_state[f"streaming_{video_id}"] = False
                            else:
                                st.error("Streaming server not available")
                    
                    # Progressive streaming player
                    if st.session_state.get(f"streaming_{video_id}", False) and server_running:
                        st.write("**🎬 Progressive Streaming Player**")
                        
                        # Status monitoring
                        status_placeholder = st.empty()
                        progress_placeholder = st.empty()
                        
                        # Check if stream is ready
                        status = get_streaming_status(video_id)
                        
                        if status["ready"]:
                            status_placeholder.success("✅ Stream ready! Starting playback...")
                            
                            # Show video player
                            streaming_url = f"http://{HOST_IP}:8080/stream/{video_id}"
                            st.video(streaming_url)
                            
                            # Control buttons
                            col_stop, col_download = st.columns([1, 1])
                            
                            with col_stop:
                                if st.button("⏹️ Stop", key=f"stop_{video_id}"):
                                    st.session_state[f"streaming_{video_id}"] = False
                                    st.rerun()
                            
                            with col_download:
                                if st.button("📥 Download", key=f"download_{video_id}"):
                                    st.info("Download feature available")
                        else:
                            # Show buffering status
                            progress = status.get("progress", 0)
                            downloaded = status.get("downloaded", 0)
                            total = status.get("total", 1)
                            
                            status_placeholder.info(f"📡 Buffering: {downloaded}/{total} chunks ({progress:.1f}%)")
                            progress_placeholder.progress(progress / 100)
                            
                            # Auto-refresh
                            time.sleep(1)
                            st.rerun()
                    
                    st.divider()
    
    # Tab 2: Upload Video
    with tab2:
        st.header("📤 Upload Video")
        
        if not server_running:
            st.error("❌ Streaming server must be running to upload videos")
            st.write("Start the server with: `python streaming_server.py`")
        else:
            # Load upload section HTML from external file
            st.markdown(load_upload_section_html(), unsafe_allow_html=True)
            
            # File uploader
            uploaded_file = st.file_uploader(
                "Choose a video file",
                type=['mp4', 'avi', 'mov', 'mkv', 'webm'],
                help="Select a video file to upload and process for P2P streaming"
            )
            
            if uploaded_file is not None:
                # Show file info
                file_size_mb = uploaded_file.size / (1024 * 1024)
                st.info(f"📹 **{uploaded_file.name}** ({file_size_mb:.1f} MB)")
                
                col1, col2, col3 = st.columns([1, 1, 2])
                
                with col1:
                    if st.button("🚀 Upload & Process", type="primary"):
                        # Start upload process
                        with st.spinner("Uploading and processing video..."):
                            progress_bar = st.progress(0)
                            status_text = st.empty()
                            
                            status_text.text("📤 Uploading video to server...")
                            progress_bar.progress(25)
                            
                            # Upload to server
                            result = upload_video_to_server(uploaded_file)
                            
                            if result["status"] == "success":
                                status_text.text("✅ Processing into chunks...")
                                progress_bar.progress(50)
                                time.sleep(2)  # Processing time
                                
                                status_text.text("🌐 Distributing to P2P network...")
                                progress_bar.progress(75)
                                time.sleep(2)  # Distribution time
                                
                                progress_bar.progress(100)
                                status_text.text("🎉 Upload complete!")
                                
                                st.success(f"✅ Video '{result['filename']}' uploaded successfully!")
                                st.info(f"Video ID: {result['video_id']}")
                                
                                # Auto-refresh video library
                                time.sleep(2)
                                st.rerun()
                                
                            else:
                                st.error(f"❌ Upload failed: {result.get('message', 'Unknown error')}")
                
                with col2:
                    estimated_chunks = max(1, int(file_size_mb))
                    st.write(f"**Estimated chunks:** ~{estimated_chunks}")
                    st.write(f"**Processing time:** ~{estimated_chunks * 2} seconds")
                
                with col3:
                    st.write("**What happens during upload:**")
                    st.write("1. 📤 File uploaded to server")
                    st.write("2. 🔧 Video processed into 1MB chunks")
                    st.write("3. 🌐 Chunks distributed to peer nodes")
                    st.write("4. ✅ Available for progressive streaming")
    
    # Tab 3: Debug Tools
    with tab3:
        st.header("🔧 Debug Tools")
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.subheader("🔍 Test Stream Connection")
            
            if server_running:
                videos = get_videos_from_server()
                if videos:
                    video_options = {f"{v['filename']} ({v['video_id'][:8]}...)": v['video_id'] for v in videos}
                    selected_video = st.selectbox("Select video to test:", options=list(video_options.keys()))
                    
                    if st.button("🧪 Test Stream"):
                        test_video_id = video_options[selected_video]
                        try:
                            response = requests.head(f"http://{HOST_IP}:8081/stream/{test_video_id}", timeout=5)
                            st.success(f"✅ Stream test successful: {response.status_code}")
                            
                            # Check status
                            time.sleep(2)
                            status = get_streaming_status(test_video_id)
                            st.json(status)
                            
                        except Exception as e:
                            st.error(f"❌ Stream test failed: {e}")
                else:
                    st.info("No videos available for testing")
            else:
                st.error("Streaming server not running")
        
        with col2:
            st.subheader("📊 System Information")
            
            if st.button("📈 Get System Stats"):
                try:
                    # DHT stats
                    videos = get_videos_from_server()
                    st.write(f"**Videos in system:** {len(videos)}")
                    
                    # Server stats
                    if server_running:
                        st.write("**Streaming server:** 🟢 Online")
                    else:
                        st.write("**Streaming server:** 🔴 Offline")
                    
                    # Component stats
                    if st.session_state.get('components_started', False):
                        st.write("**DHT node:** 🟢 Running")
                        st.write("**Peer node:** 🟢 1 active")
                    else:
                        st.write("**P2P services:** 🔴 Offline")
                        
                except Exception as e:
                    st.error(f"Failed to get stats: {e}")
        
        # Raw API testing
        st.subheader("🔧 Raw API Testing")
        
        api_endpoint = st.selectbox(
            "API Endpoint:",
            ["/api/videos", "/api/stream-status/{video_id}"]
        )
        
        if api_endpoint == "/api/stream-status/{video_id}":
            video_id_input = st.text_input("Video ID:")
            api_endpoint = api_endpoint.replace("{video_id}", video_id_input)
        
        if st.button("📡 Call API"):
            if server_running:
                try:
                    response = requests.get(f"http://{HOST_IP}:8080{api_endpoint}")
                    st.write(f"**Status:** {response.status_code}")
                    st.json(response.json())
                except Exception as e:
                    st.error(f"API call failed: {e}")
            else:
                st.error("Server not running")

if __name__ == "__main__":
    main()