import io
import wave
import uuid
import boto3
import pyaudio
import logging
from config import settings

logger = logging.getLogger("Satellite.Storage")


class StorageClient:
    def __init__(self, audio_manager):
        self.audio_manager = audio_manager
        # Initialize S3 client using the standard boto3 library
        self.s3 = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint,
            aws_access_key_id=settings.s3_access_key,
            aws_secret_access_key=settings.s3_secret_key.get_secret_value(),
        )
        self.bucket = settings.s3_bucket

    def upload_audio(self, audio_bytes: bytes) -> str | None:
        logger.info("Uploading audio to Object Storage...")

        # Prepare WAV buffer
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(self.audio_manager.get_sample_size(pyaudio.paInt16))
            wf.setframerate(16000)
            wf.writeframes(audio_bytes)
        buffer.seek(0)

        # Generate a unique filename
        filename = f"{uuid.uuid4().hex}.wav"

        try:
            # Upload to S3 compatible storage
            self.s3.upload_fileobj(
                buffer, self.bucket, filename, ExtraArgs={"ContentType": "audio/wav"}
            )
            # Construct and return the URL
            return f"{settings.s3_endpoint}/{self.bucket}/{filename}"
        except Exception as e:
            logger.error(f"Failed to upload audio: {e}")
            return None

    def download_file(self, object_key: str, destination_path: str) -> bool:
        """Downloads a file from S3 to a local path."""
        logger.info(f"Downloading {object_key} from Object Storage...")
        try:
            self.s3.download_file(self.bucket, object_key, destination_path)
            return True
        except Exception as e:
            logger.error(f"Failed to download file: {e}")
            return False
