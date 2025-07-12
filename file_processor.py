import hashlib
import json
import os
from pathlib import Path
from typing import Dict, List
from dataclasses import dataclass, asdict

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

class FileProcessor:
    def __init__(self, chunk_size=1024*1024, storage_dir="./processed"):
        self.chunk_size = chunk_size
        self.storage_dir = Path(storage_dir)
        self.chunks_dir = self.storage_dir / "chunks"
        self.metadata_dir = self.storage_dir / "metadata"
        
        self.storage_dir.mkdir(exist_ok=True)
        self.chunks_dir.mkdir(exist_ok=True)
        self.metadata_dir.mkdir(exist_ok=True)
    
    def calculate_hash(self, data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()
    
    def process_video(self, video_path: str) -> VideoMetadata:
        video_p = Path(video_path)
        file_size = video_p.stat().st_size
        total_chunks = (file_size + self.chunk_size - 1) // self.chunk_size
        
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
        
        return metadata
    
    def get_chunk_data(self, video_id: str, chunk_index: int) -> bytes:
        chunk_filename = f"{video_id}_{chunk_index}.chunk"
        chunk_path = self.chunks_dir / chunk_filename
        
        if chunk_path.exists():
            with open(chunk_path, 'rb') as f:
                return f.read()
        return None
    
    def get_metadata(self, video_id: str) -> VideoMetadata:
        metadata_path = self.metadata_dir / f"{video_id}.json"
        
        if metadata_path.exists():
            with open(metadata_path, 'r') as f:
                data = json.load(f)
                return VideoMetadata(**data)
        return None
    
    def list_processed_videos(self) -> List[VideoMetadata]:
        videos = []
        for metadata_file in self.metadata_dir.glob("*.json"):
            try:
                with open(metadata_file, 'r') as f:
                    data = json.load(f)
                    videos.append(VideoMetadata(**data))
            except:
                continue
        return videos