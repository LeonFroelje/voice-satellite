import pyaudio
import numpy as np
import base64
import io
import requests
import logging
import time

from pydub import AudioSegment
from openwakeword.model import Model
from openwakeword.utils import download_models
from stt_client import TranscriptionClient

# Import configuration
from config import settings

print(settings)
# --- Logging Setup ---
logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("Satellite")

# --- Audio Constants ---
FORMAT = pyaudio.paInt16
CHANNELS = 1
RATE = 16000
CHUNK = 1280
speaker_stream = None
audio_manager = pyaudio.PyAudio()


def play_audio_from_b64(b64_string):
    global speaker_stream
    try:
        audio_data = base64.b64decode(b64_string)
        audio_segment = AudioSegment.from_file(io.BytesIO(audio_data))

        # Check if we need to (re)open the stream (if format changed or first run)
        # Note: In a production satellite, your TTS usually sends a consistent format.
        if speaker_stream is None:
            speaker_stream = audio_manager.open(
                format=audio_manager.get_format_from_width(audio_segment.sample_width),
                channels=audio_segment.channels,
                rate=audio_segment.frame_rate,
                output=True,
                output_device_index=settings.speaker_index,
            )

        logger.debug(f"Playing audio ({audio_segment.duration_seconds}s)...")

        # Wake up silence
        silence_len = int(audio_segment.frame_rate * audio_segment.channels * 1)  # 0.2s
        silence = b"\x00" * silence_len

        speaker_stream.write(silence)
        speaker_stream.write(audio_segment.raw_data)

    except Exception as e:
        logger.error(f"Audio playback failed: {e}")
        # If the stream crashed, reset it so the next call tries to recreate it
        speaker_stream = None


def send_to_orchestrator(text: str):
    """
    Sends the transcribed text + room context to the Brain.
    """
    logger.debug(f"Sending to Orchestrator ({settings.orchestrator_url})...")

    # Send room where satellite is placed in as well as transcribed text
    # to enable turning lights off in specific rooms without having to specify the room
    payload = {"text": text, "room": settings.room}

    headers = {}
    if settings.api_token:
        headers["Authorization"] = f"Bearer {settings.api_token.get_secret_value()}"

    try:
        response = requests.post(
            settings.orchestrator_url, json=payload, headers=headers
        )
        if response.ok:
            data = response.json()
            text_resp = data.get("response_text", "")
            logger.debug(f"Response: {text_resp}")

            audio_b64 = data.get("audio_b64")
            if audio_b64:
                play_audio_from_b64(audio_b64)
            else:
                logger.warning("No audio received from Orchestrator")
        else:
            logger.error(
                f"Orchestrator returned {response.status_code}: {response.text}"
            )

    except Exception as e:
        logger.error(f"Failed to connect to Orchestrator: {e}")


def main():
    download_models()
    owwModel = Model(wakeword_models=[settings.wakeword_models])

    global audio_manager
    mic_stream = None

    # --- ROBUST OPEN FUNCTION ---
    def safe_open_stream(retries=3, delay=1.0):
        """Attempts to open the stream, retrying if the device is busy."""
        for attempt in range(retries):
            try:
                stream = audio_manager.open(
                    format=FORMAT,
                    channels=CHANNELS,
                    rate=RATE,
                    input=True,
                    frames_per_buffer=CHUNK,
                    input_device_index=settings.mic_index,
                )
                return stream
            except OSError as e:
                if attempt < retries - 1:
                    logger.warning(
                        f"Microphone busy, retrying in {delay}s... ({attempt + 1}/{retries})"
                    )
                    time.sleep(delay)
                else:
                    logger.error("Failed to open microphone after multiple attempts.")
                    raise e

    # Initial open
    mic_stream = safe_open_stream()

    logger.info(f"Satellite started in room: '{settings.room}'")
    logger.info(f"Listening for wakeword (Threshold: {settings.wakeword_threshold})...")

    try:
        while True:
            # 1. Listen for Wake Word
            # We wrap read in try/except because USB mics can glitch
            try:
                audio_data = mic_stream.read(CHUNK, exception_on_overflow=False)
            except OSError:
                # If read fails, try to reset the stream
                mic_stream = safe_open_stream()
                continue

            audio_np = np.frombuffer(audio_data, dtype=np.int16)
            prediction = owwModel.predict(audio_np)

            if prediction[settings.wakeword_models] >= settings.wakeword_threshold:
                logger.info("Wake Word Detected!")

                # 2. CLOSE MIC IMMEDIATELY
                if mic_stream:
                    mic_stream.stop_stream()
                    mic_stream.close()
                    mic_stream = None  # Mark as closed so 'finally' block doesn't panic

                # 3. TRANSCRIPTION
                full_text = ""

                def callback(text, _):
                    nonlocal full_text
                    logger.debug(text)
                    full_text = text

                client = TranscriptionClient(
                    settings.whisper_host,
                    settings.whisper_port,
                    lang=settings.language,
                    model=settings.whisper_model,
                    use_vad=True,
                    transcription_callback=callback,
                )

                # Run Transcription
                client.record_seconds = 10
                try:
                    client()
                except Exception as e:
                    logger.error(f"Transcription failed: {e}")

                # 4. Handle Result
                if full_text.strip():
                    client.client.close_websocket()
                    client.finalize_recording(0)
                    client.client.audio_bytes
                    logger.info(f"Transcribed: {full_text}")
                    send_to_orchestrator(full_text)
                else:
                    logger.info("No speech detected.")

                # client.client.close_websocket()
                # client.finalize_recording(0)
                # client.client.audio_bytes
                # 5. RE-OPEN MIC WITH DELAY
                # Give the transcription client 1 second to fully release the hardware
                time.sleep(1.0)

                logger.debug("Restarting microphone stream...")
                owwModel.reset()
                mic_stream = safe_open_stream()

                # Flush the buffer
                try:
                    for _ in range(5):
                        mic_stream.read(CHUNK, exception_on_overflow=False)
                except Exception:
                    pass

                logger.info("Listening again...")

    except KeyboardInterrupt:
        logger.info("Stopping...")
    except Exception as e:
        logger.error(f"Critical Error: {e}")
    finally:
        # Safe cleanup
        if mic_stream is not None:
            try:
                if mic_stream.is_active():
                    mic_stream.stop_stream()
                mic_stream.close()
            except Exception:
                pass
        audio_manager.terminate()


if __name__ == "__main__":
    main()
