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


def play_audio_from_b64(b64_string):
    try:
        # 1. Decode Base64 string to binary bytes
        audio_data = base64.b64decode(b64_string)

        # 2. Load into Pydub (handles wav/mp3/ogg automatically)
        #    This is crucial because it parses the header to get sample rate/channels
        audio_segment = AudioSegment.from_file(io.BytesIO(audio_data))

        # 3. Initialize PyAudio
        p = pyaudio.PyAudio()

        # 4. Open an Output Stream using the format from the audio segment
        stream = p.open(
            format=p.get_format_from_width(audio_segment.sample_width),
            channels=audio_segment.channels,
            rate=audio_segment.frame_rate,
            output=True,
            output_device_index=settings.speaker_index,
        )

        logger.debug(f"Playing audio ({audio_segment.duration_seconds}s)...")

        silence = b"\x00" * (
            audio_segment.frame_rate
            * audio_segment.channels
            * audio_segment.sample_width
            // 2
        )
        # Generate 0.5 seconds of silence matching the audio format
        # This forces the DAC/Amp to wake up before the real speech starts
        stream.write(silence)
        # 5. Write the raw audio data to the stream
        stream.write(audio_segment.raw_data)

        # 6. Cleanup
        stream.stop_stream()
        stream.close()
        p.terminate()

    except Exception as e:
        logger.error(f"Audio playback failed: {e}")


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

    audio = pyaudio.PyAudio()
    mic_stream = None  # Initialize to None for safety

    # --- ROBUST OPEN FUNCTION ---
    def safe_open_stream(retries=3, delay=1.0):
        """Attempts to open the stream, retrying if the device is busy."""
        for attempt in range(retries):
            try:
                stream = audio.open(
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
                    logger.info(f"Transcribed: {full_text}")
                    send_to_orchestrator(full_text)
                else:
                    logger.info("No speech detected.")

                client.client.close_websocket()
                client.finalize_recording(0)
                client.client.audio_bytes
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
        audio.terminate()


if __name__ == "__main__":
    main()
