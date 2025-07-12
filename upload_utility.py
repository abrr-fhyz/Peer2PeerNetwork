#!/usr/bin/env python3
import sys
import time
from pathlib import Path
from peer_controller import PeerController

class VideoUploader:
    def __init__(self):
        self.controller = None
    
    def upload_video(self, video_path: str):
        """Upload a video to the P2P network"""
        video_path = Path(video_path)
        
        if not video_path.exists():
            print(f"❌ Video file not found: {video_path}")
            return False
        
        print(f"📁 Uploading video: {video_path.name}")
        print("🔧 Starting temporary peer for upload...")
        
        # Start controller services
        self.controller = PeerController(
            peer_host="localhost",
            peer_port=9002,  # Use different port to avoid conflicts
            dht_host="localhost",
            dht_port=8000
        )
        
        try:
            self.controller.start_services()
            print("✅ Connected to P2P network")
            
            # Upload the video
            print("📤 Processing and uploading video chunks...")
            self.controller.upload_video(str(video_path))
            print("✅ Video uploaded successfully!")
            
            # List videos to confirm
            print("\n📋 Current video catalog:")
            self.controller.list_videos()
            
        except Exception as e:
            print(f"❌ Upload failed: {e}")
            return False
        finally:
            if self.controller:
                self.controller.stop_services()
                print("🔌 Disconnected from P2P network")
        
        return True
    
    def batch_upload(self, directory: str):
        """Upload all videos in a directory"""
        directory = Path(directory)
        
        if not directory.exists() or not directory.is_dir():
            print(f"❌ Directory not found: {directory}")
            return
        
        # Common video extensions
        video_extensions = {'.mp4', '.avi', '.mkv', '.mov', '.wmv', '.flv', '.webm'}
        
        video_files = []
        for ext in video_extensions:
            video_files.extend(directory.glob(f"*{ext}"))
            video_files.extend(directory.glob(f"*{ext.upper()}"))
        
        if not video_files:
            print(f"❌ No video files found in: {directory}")
            return
        
        print(f"📁 Found {len(video_files)} video files")
        
        # Start controller once for batch upload
        self.controller = PeerController(
            peer_host="localhost",
            peer_port=9002,
            dht_host="localhost",
            dht_port=8000
        )
        
        try:
            self.controller.start_services()
            print("✅ Connected to P2P network")
            
            for i, video_file in enumerate(video_files, 1):
                print(f"\n📤 [{i}/{len(video_files)}] Uploading: {video_file.name}")
                try:
                    self.controller.upload_video(str(video_file))
                    print(f"✅ Uploaded: {video_file.name}")
                except Exception as e:
                    print(f"❌ Failed to upload {video_file.name}: {e}")
            
            print("\n📋 Final video catalog:")
            self.controller.list_videos()
            
        except Exception as e:
            print(f"❌ Batch upload failed: {e}")
        finally:
            if self.controller:
                self.controller.stop_services()
                print("🔌 Disconnected from P2P network")

def main():
    print("🎬 P2P Video Upload Utility")
    print("=" * 40)
    
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python upload_utility.py <video_file>")
        print("  python upload_utility.py <directory>")
        print("\nExamples:")
        print("  python upload_utility.py movie.mp4")
        print("  python upload_utility.py ./videos/")
        sys.exit(1)
    
    target_path = Path(sys.argv[1])
    uploader = VideoUploader()
    
    if target_path.is_file():
        # Single file upload
        uploader.upload_video(str(target_path))
    elif target_path.is_dir():
        # Directory batch upload
        uploader.batch_upload(str(target_path))
    else:
        print(f"❌ Path not found: {target_path}")
        sys.exit(1)

if __name__ == "__main__":
    main()