import pyaudio
import numpy as np
import base64
import io
import os
import requests
import logging
import time
import wave
import urllib.request
import onnxruntime as ort

from pydub import AudioSegment
from openwakeword.model import Model
from config import settings

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
CHUNK = 1280  # openwakeword prefers 1280
OUTPUT_RATE = 44100
audio_manager = pyaudio.PyAudio()
speaker_stream = None


def _play_normalized_audio(audio_segment: AudioSegment):
    """Internal helper to normalize and play any audio segment."""
    global speaker_stream

    # 1. Force the audio to match our Master Output Format
    normalized_audio = audio_segment.set_frame_rate(OUTPUT_RATE).set_channels(
        settings.output_channels
    )
    if (
        hasattr(settings, "output_delay")
        and settings.output_delay
        and settings.output_delay > 0
    ):
        delay_ms = int(settings.output_delay)
        # Generate pure silence
        silence = AudioSegment.silent(duration=delay_ms, frame_rate=OUTPUT_RATE)
        # Ensure the silence strictly matches our channels to prevent concatenation errors
        silence = silence.set_channels(settings.output_channels)

        # Prepend the silence to the actual audio
        normalized_audio = silence + normalized_audio
    try:
        # 2. Open the stream if it doesn't exist, locked to the Master Format
        if speaker_stream is None:
            speaker_stream = audio_manager.open(
                format=audio_manager.get_format_from_width(
                    normalized_audio.sample_width
                ),
                channels=settings.output_channels,
                rate=OUTPUT_RATE,
                output=True,
                output_device_index=settings.speaker_index,
            )

        logger.debug(
            f"Playing audio ({normalized_audio.duration_seconds:.2f}s) at {OUTPUT_RATE}Hz..."
        )
        speaker_stream.write(normalized_audio.raw_data)
        speaker_stream.stop_stream()
        speaker_stream.close()
        speaker_stream = None

    except Exception as e:
        logger.error(f"Audio playback failed: {e}")
        # Clean up the broken stream so it can recover on the next attempt
        if speaker_stream is not None:
            try:
                speaker_stream.close()
            except Exception:
                pass
        speaker_stream = None


def play_local_wav(file_path):
    """Plays a local WAV file, dynamically resampling it if necessary."""
    if not file_path or not os.path.exists(file_path):
        logger.warning(f"File {file_path} not found. Not playing sound.")
        return

    try:
        audio_segment = AudioSegment.from_wav(file_path)
        _play_normalized_audio(audio_segment)
    except Exception as e:
        logger.error(f"Failed to load local sound {file_path}: {e}")


# --- Silero VAD ONNX Wrapper ---
def ensure_silero_vad_model():
    """Downloads the lightweight Silero VAD ONNX model if it's not present locally."""
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    model_path = os.path.join(BASE_DIR, "assets", "models", "silero_vad.onnx")
    if not os.path.exists(model_path):
        logger.info("Downloading Silero VAD ONNX model (~1.8MB)...")
        url = "https://github.com/snakers4/silero-vad/raw/master/src/silero_vad/data/silero_vad.onnx"
        urllib.request.urlretrieve(url, model_path)
        logger.info("Downloaded silero_vad.onnx")
    return model_path


class SileroVAD:
    def __init__(self, model_path):
        # We limit threads to 1 since VAD is extremely lightweight and we want to save CPU
        options = ort.SessionOptions()
        options.inter_op_num_threads = 1
        options.intra_op_num_threads = 1
        self.session = ort.InferenceSession(model_path, sess_options=options)
        self.reset_states()

    def reset_states(self):
        # Silero VAD ONNX requires a state tensor of shape (2, 1, 128)
        self.state = np.zeros((2, 1, 128), dtype=np.float32)

    def process(self, audio_chunk_int16, sr=16000):
        # Convert raw int16 PCM to float32 normalized between -1.0 and 1.0
        audio_float32 = (
            np.frombuffer(audio_chunk_int16, dtype=np.int16).astype(np.float32)
            / 32768.0
        )

        ort_inputs = {
            "input": np.expand_dims(audio_float32, axis=0),
            "state": self.state,
            "sr": np.array([sr], dtype=np.int64),
        }
        ort_outs = self.session.run(None, ort_inputs)
        out, self.state = ort_outs
        return out[0][0]  # Returns speech probability (0.0 to 1.0)


# --- Core Functions ---
def play_audio_from_b64(b64_string):
    """Plays base64 encoded audio, dynamically resampling it if necessary."""
    try:
        audio_data = base64.b64decode(b64_string)
        # Explicitly tell Pydub we are reading a WAV from memory
        audio_segment = AudioSegment.from_file(io.BytesIO(audio_data), format="wav")
        _play_normalized_audio(audio_segment)
    except Exception as e:
        logger.error(f"Failed to load base64 audio: {e}")


def transcribe_audio_api(audio_bytes: bytes):
    """Sends raw audio bytes to an OpenAI-compatible transcription endpoint."""
    logger.info("Sending audio to Transcription API...")

    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wf:
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(audio_manager.get_sample_size(FORMAT))
        wf.setframerate(RATE)
        wf.writeframes(audio_bytes)
    buffer.seek(0)

    try:
        url = f"{settings.whisper_host}:{settings.whisper_port}/v1/audio/transcriptions"
        files = {"file": ("audio.wav", buffer, "audio/wav")}
        data = {"model": settings.whisper_model}
        headers = {}
        if settings.api_token:
            headers["Authorization"] = f"Bearer {settings.api_token.get_secret_value()}"

        response = requests.post(
            url, files=files, data=data, headers=headers, timeout=15
        )

        if response.ok:
            return response.json().get("text", "")
        else:
            logger.error(f"STT API Error: {response.status_code} - {response.text}")
    except Exception as e:
        logger.error(f"Failed to connect to STT API: {e}")
    return ""


def send_to_orchestrator(text: str):
    logger.debug(f"Sending to Orchestrator...")
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
            audio_b64 = data.get("audio_b64")
            if audio_b64:
                play_audio_from_b64(audio_b64)
        else:
            logger.error(f"Orchestrator Error: {response.status_code}")
    except Exception as e:
        logger.error(f"Orchestrator Connection Failed: {e}")


def record_until_silence(
    mic_stream, vad_model: SileroVAD, max_seconds=10, silence_timeout=1.5
):
    """
    Records audio using Silero VAD.
    Stops if silence is detected, max_seconds is reached, or no initial speech is heard.
    """
    logger.info("Listening for command...")
    vad_model.reset_states()

    frames = []
    SILERO_CHUNK = 512  # Silero strictly prefers 512 samples for 16kHz (32ms chunk)

    start_time = time.time()
    last_speech_time = time.time()
    has_spoken = False

    while (time.time() - start_time) < max_seconds:
        data = mic_stream.read(SILERO_CHUNK, exception_on_overflow=False)
        frames.append(data)

        speech_prob = vad_model.process(data, RATE)
        current_time = time.time()

        if speech_prob > 0.5:  # 50% threshold is ideal for Silero
            last_speech_time = current_time
            has_spoken = True

        # Stopping conditions
        if has_spoken and (current_time - last_speech_time) > silence_timeout:
            logger.debug("Silence detected, finalizing recording.")
            break
        elif not has_spoken and (current_time - start_time) > 3.0:
            logger.debug("No initial speech detected within 3 seconds, aborting.")
            break

    return b"".join(frames)


def main():
    # 1. Initialize Models
    owwModel = Model(wakeword_models=[settings.wakeword_models])

    model_path = ensure_silero_vad_model()
    silero_vad = SileroVAD(model_path)

    # 2. Open Mic
    def safe_open_stream():
        return audio_manager.open(
            format=FORMAT,
            channels=CHANNELS,
            rate=RATE,
            input=True,
            frames_per_buffer=CHUNK,
            input_device_index=settings.mic_index,
        )

    mic_stream = safe_open_stream()
    logger.info(f"Satellite started. Room: {settings.room}")

    try:
        while True:
            # --- WAKEWORD DETECTION LOOP ---
            try:
                # OpenWakeWord prefers chunks of 1280
                audio_data = mic_stream.read(CHUNK, exception_on_overflow=False)
            except OSError:
                mic_stream = safe_open_stream()
                continue

            audio_np = np.frombuffer(audio_data, dtype=np.int16)
            prediction = owwModel.predict(audio_np)

            if prediction[settings.wakeword_models] >= settings.wakeword_threshold:
                logger.info(
                    f"Wake Word Detected! (Confidence: {prediction[settings.wakeword_models]:.2f})"
                )
                play_local_wav(settings.wake_sound)

                # --- COMMAND RECORDING LOOP ---
                audio_recorded = record_until_silence(
                    mic_stream, silero_vad, silence_timeout=settings.silence_timeout
                )

                # --- PROCESSING ---
                if len(audio_recorded) > 0:
                    transcribed_text = transcribe_audio_api(audio_recorded)

                    if transcribed_text.strip():
                        logger.info(f"Transcribed: {transcribed_text}")
                        play_local_wav(settings.done_sound)
                        send_to_orchestrator(transcribed_text)
                    else:
                        logger.info("No text transcribed.")

                # Reset models for the next interaction
                owwModel.reset()
                logger.info("Listening for wakeword...")

    except KeyboardInterrupt:
        logger.info("Stopping...")
    finally:
        if mic_stream:
            mic_stream.stop_stream()
            mic_stream.close()
        audio_manager.terminate()


if __name__ == "__main__":
    main()
