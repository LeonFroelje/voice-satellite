import os
import time
import threading
from storage_client import StorageClient
import logging
import hashlib
from config import settings

logger = logging.getLogger("Satellite.Actions")

# Set up a local cache directory for TTS audio files
CACHE_DIR = settings.cache_dir
os.makedirs(CACHE_DIR, exist_ok=True)


def download_and_cache_audio(url: str, storage_client) -> str:
    """
    Downloads audio from S3 via Boto3, caches it locally using an MD5 hash
    of the URL, and returns the local file path.
    """
    url_hash = hashlib.md5(url.encode()).hexdigest()
    file_path = os.path.join(CACHE_DIR, f"{url_hash}.wav")

    # Return cached file if it already exists
    if os.path.exists(file_path):
        logger.debug(f"Audio found in local cache: {file_path}")
        return file_path

    # Extract the S3 object key from the URL (e.g., "tts_abc123.wav")
    object_key = url.split("/")[-1]

    # Use our authenticated Boto3 client instead of requests
    success = storage_client.download_file(object_key, file_path)

    if success:
        return file_path
    return ""


def handle_satellite_actions(
    actions: list, audio_player, storage_client: StorageClient
):
    """
    Executes local actions requested via MQTT payloads.
    Expects `actions` to be a list of dictionaries parsed from JSON.
    """
    for action in actions:
        # Since we parse MQTT payloads with json.loads(), actions are now dicts
        action_type = action.get("type", "")
        payload = action.get("payload", {})

        if action_type == "set_volume":
            level = payload.get("level", 50)
            logger.info(f"Setting local volume to {level}%")
            os.system(f"amixer set Master {level}%")

        elif action_type == "start_timer":
            duration = payload.get("duration_seconds", 0)
            logger.info(f"Starting timer for {duration} seconds")

            def timer_thread(seconds):
                time.sleep(seconds)
                logger.info("Timer complete!")
                # Ensure you add 'timer_sound' to your config.py settings
                audio_player.play_local_wav(settings.timer_sound)

            threading.Thread(target=timer_thread, args=(duration,), daemon=True).start()

        elif action_type == "play_audio":
            # This handles the TTS service's output
            audio_url = payload.get("audio_url")
            if audio_url:
                local_file = download_and_cache_audio(audio_url, storage_client)
                if local_file:
                    audio_player.play_local_wav(local_file)

        else:
            logger.warning(f"Unknown action type received: {action_type}")
