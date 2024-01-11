'''
Wrapper for Google Cloud Storage
'''
import logging
from typing import Optional
from google.cloud import storage

from .settings import BUCKET_NAME

class DuckStorage:
    '''Wrapper for Google Cloud Storage'''
    def __init__(self, bucket_name: str = BUCKET_NAME):
        self.client = storage.Client()
        self.bucket = self.client.get_bucket(bucket_name)

    def get(self, path: str) -> Optional[bytes]:
        '''Download byte data from storage'''
        blob = self.bucket.blob(path)
        if not blob.exists():
            logging.info("No audio for %s", f"{path}")
            return None

        return blob.download_as_bytes()

    def upload(self, path: str, data: bytes, content_type: str = "audio/wav"):
        '''Upload byte data to storage'''
        blob = self.bucket.blob(path)
        blob.upload_from_string(
            data=data,
            content_type=content_type,
        )
