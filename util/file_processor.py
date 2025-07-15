import hashlib
import json
import os
from pathlib import Path
import subprocess
from typing import Dict, List, Optional
from dataclasses import dataclass, asdict
import logging

# ------------------------------------------------------------
# Setup logging for this module
# ------------------------------------------------------------
logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
)

# ------------------------------------------------------------
# Data classes
# ------------------------------------------------------------
@dataclass
class ChunkInfo:
    index: int
    size: int
    hash: str
    offset: int

@dataclass
class VideoMetadata:
    filename: str
    original_size: int
    chunk_size: int
    total_chunks: int
    chunks: List[Dict]
    video_id: str

# ------------------------------------------------------------
# FileProcessor class
# ------------------------------------------------------------
class FileProcessor:
    def __init__(self, chunk_size=1024*1024, storage_dir="./processed"):
        self.chunk_size = chunk_size
        self.storage_dir = Path(storage_dir)
        self.chunks_dir = self.storage_dir / "chunks"
        self.metadata_dir = self.storage_dir / "metadata"
        
        self.storage_dir.mkdir(exist_ok=True)
        self.chunks_dir.mkdir(exist_ok=True)
        self.metadata_dir.mkdir(exist_ok=True)
        
        logger.info(f"[FileProcessor] Initialized with chunk_size={self.chunk_size} bytes | storage_dir={self.storage_dir}")

    def calculate_hash(self, data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()

    def ensure_mp4_metadata_at_front(self, video_path: str) -> str:
        """Ensure the MP4 has its moov atom at the front for streaming"""
        output_path = str(Path(video_path).with_suffix('.streamable.mp4'))
        
        logger.info(f"[FileProcessor] Starting moov atom remux: {video_path} -> {output_path}")

        cmd = [
            'ffmpeg', '-i', video_path,
            '-c', 'copy',
            '-movflags', 'faststart',
            output_path
        ]
        
        try:
            subprocess.run(cmd, check=True, capture_output=True)
            logger.info(f"[FileProcessor] moov atom fixed successfully: {output_path}")
            return output_path
        except subprocess.CalledProcessError as e:
            logger.error(f"[FileProcessor] Failed to process MP4 metadata: {e.stderr.decode()}")
            return video_path  # Fallback to original    

    def generate_init_segment(self, video_path: str) -> Optional[bytes]:
        """Generate MP4 init segment for fragmented streaming"""
        init_path = Path(video_path).with_suffix('.init.mp4')
        
        logger.info(f"[FileProcessor] Generating init segment: {video_path} -> {init_path}")

        cmd = [
            'ffmpeg',
            '-i', video_path,
            '-c', 'copy',
            '-f', 'mp4',
            '-movflags', 'empty_moov+default_base_moof+frag_keyframe',
            '-frames', '1',
            str(init_path)
        ]
        
        try:
            subprocess.run(cmd, check=True, capture_output=True)
            logger.info(f"[FileProcessor] Init segment generated successfully: {init_path}")
            return init_path.read_bytes()
        except Exception as e:
            logger.error(f"[FileProcessor] Failed to generate init segment: {e}")
            return None

    def process_video(self, video_path: str) -> VideoMetadata:
        video_p = Path(video_path)
        file_size = video_p.stat().st_size
        total_chunks = (file_size + self.chunk_size - 1) // self.chunk_size
        
        logger.info(f"[FileProcessor] Processing video: {video_p.name} | Size: {file_size} bytes | Chunk size: {self.chunk_size} bytes | Total chunks: {total_chunks}")

        video_id = self.calculate_hash(video_p.read_bytes())[:16]
        chunks = []
        
        with open(video_path, 'rb') as f:
            for i in range(total_chunks):
                offset = i * self.chunk_size
                f.seek(offset)
                chunk_data = f.read(self.chunk_size)
                
                if not chunk_data:
                    break
                
                chunk_hash = self.calculate_hash(chunk_data)
                chunk_filename = f"{video_id}_{i}.chunk"
                chunk_path = self.chunks_dir / chunk_filename
                
                with open(chunk_path, 'wb') as chunk_file:
                    chunk_file.write(chunk_data)
                
                logger.info(f"[FileProcessor] Created chunk {i+1}/{total_chunks} | Hash: {chunk_hash[:8]}... | Size: {len(chunk_data)} bytes")

                chunk_info = ChunkInfo(
                    index=i,
                    size=len(chunk_data),
                    hash=chunk_hash,
                    offset=offset
                )
                chunks.append(asdict(chunk_info))
        
        metadata = VideoMetadata(
            filename=video_p.name,
            original_size=file_size,
            chunk_size=self.chunk_size,
            total_chunks=len(chunks),
            chunks=chunks,
            video_id=video_id
        )
        
        metadata_path = self.metadata_dir / f"{video_id}.json"
        with open(metadata_path, 'w') as f:
            json.dump(asdict(metadata), f, indent=2)
        
        logger.info(f"[FileProcessor] Metadata saved: {metadata_path}")
        logger.info(f"[FileProcessor] Video {video_id} processing complete.")

        return metadata

    def get_chunk_data(self, video_id: str, chunk_index: int) -> bytes:
        chunk_filename = f"{video_id}_{chunk_index}.chunk"
        chunk_path = self.chunks_dir / chunk_filename
        
        if chunk_path.exists():
            logger.debug(f"[FileProcessor] Reading chunk: {chunk_filename}")
            with open(chunk_path, 'rb') as f:
                return f.read()
        logger.warning(f"[FileProcessor] Chunk not found: {chunk_filename}")
        return None

    def get_metadata(self, video_id: str) -> VideoMetadata:
        metadata_path = self.metadata_dir / f"{video_id}.json"
        
        if metadata_path.exists():
            logger.info(f"[FileProcessor] Loading metadata: {metadata_path}")
            with open(metadata_path, 'r') as f:
                data = json.load(f)
                return VideoMetadata(**data)
        logger.warning(f"[FileProcessor] Metadata not found for video ID: {video_id}")
        return None

    def list_processed_videos(self) -> List[VideoMetadata]:
        videos = []
        for metadata_file in self.metadata_dir.glob("*.json"):
            try:
                with open(metadata_file, 'r') as f:
                    data = json.load(f)
                    videos.append(VideoMetadata(**data))
                    logger.info(f"[FileProcessor] Found processed video: {metadata_file.name}")
            except Exception as e:
                logger.warning(f"[FileProcessor] Could not read metadata file {metadata_file}: {e}")
                continue
        return videos
