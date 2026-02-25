import os
from storage_client import StorageClient
import logging
import hashlib
from config import settings
import pulsectl

logger = logging.getLogger("Satellite.Actions")

# Set up a local cache directory for TTS audio files
CACHE_DIR = settings.cache_dir
os.makedirs(CACHE_DIR, exist_ok=True)


logger = logging.getLogger(__name__)


def set_system_volume_pulsectl(level: int):
    """Sets the system volume using the native pulsectl Python library."""
    level = max(0, min(100, int(level)))
    volume_float = level / 100.0  # PulseAudio API expects a float between 0.0 and 1.0

    try:
        # Connect to the PulseAudio socket
        with pulsectl.Pulse("voice-satellite-volume") as pulse:
            # Find the name of the default output device
            default_sink_name = pulse.server_info().default_sink_name

            # Find the actual sink object that matches the default name
            default_sink = next(
                (sink for sink in pulse.sink_list() if sink.name == default_sink_name),
                None,
            )

            if default_sink:
                pulse.volume_set_all_chans(default_sink, volume_float)
                logger.info(f"System volume set to {level}% via pulsectl.")
            else:
                logger.error("Could not find the default audio sink.")

    except Exception as e:
        logger.error(f"PulseAudio connection failed: {e}")


def download_and_cache_audio(filename: str, storage_client) -> str:
    """
    Downloads audio from S3 via Boto3, caches it locally using an MD5 hash
    of the URL, and returns the local file path.
    """
    file_path = os.path.join(CACHE_DIR, filename)

    # Return cached file if it already exists
    if os.path.exists(file_path):
        logger.debug(f"Audio found in local cache: {file_path}")
        return file_path

    success = storage_client.download_file(filename, file_path)

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
            set_system_volume_pulsectl(level)

        elif action_type == "play_audio":
            filename = payload.get("filename")

            loop_duration = payload.get("loop_duration", 0)
            logger.info(f"Playing sound {filename} for {loop_duration} seconds")
            if filename:
                local_file = download_and_cache_audio(filename, storage_client)
                if local_file:
                    # Pass the loop_duration to our updated method
                    audio_player.play_local_wav(local_file, loop_duration=loop_duration)
        elif action_type == "stop_audio":
            logger.info("Received MQTT command to stop audio.")
            audio_player.stop()
        else:
            logger.warning(f"Unknown action type received: {action_type}")
