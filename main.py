import time
import logging
import pyaudio
import numpy as np

from config import settings
from openwakeword.model import Model
from orchestrator_client import OrchestratorClient

# Import our new modules
from vad import ensure_silero_vad_model, SileroVAD
from communications import notify_orchestrator_wakeword, notify_orchestrator_finished, handle_satellite_actions
from audio_io import AudioPlayer, record_until_silence

# --- Logging Setup ---
logging.basicConfig(level=settings.log_level, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("Satellite.Main")

# --- Audio Constants ---
FORMAT = pyaudio.paInt16
CHANNELS = 1
RATE = 16000
CHUNK = 512  # Changed to 512 for continuous VAD
OUTPUT_RATE = 44100
WAKEWORD_VAD_GATE_TIMEOUT = 0.8

def main():
    audio_manager = pyaudio.PyAudio()
    audio_player = AudioPlayer(audio_manager, OUTPUT_RATE, settings)
    
    orchestrator_client = OrchestratorClient(
        settings.orchestrator_host, settings.orchestrator_port,
        settings.orchestrator_token, audio_manager, settings.orchestrator_protocol
    )

    owwModel = Model(wakeword_models=[settings.wakeword_models])
    silero_vad = SileroVAD(ensure_silero_vad_model())

    def safe_open_stream():
        return audio_manager.open(
            format=FORMAT, channels=CHANNELS, rate=RATE, input=True,
            frames_per_buffer=CHUNK, input_device_index=settings.mic_index,
        )

    mic_stream = safe_open_stream()
    logger.info(f"Satellite started. Room: {settings.room}")

    recent_speech_time = 0.0
    oww_buffer = bytearray()

    try:
        while True:
            # 1. READ AUDIO & PROCESS VAD
            try:
                audio_data = mic_stream.read(CHUNK, exception_on_overflow=False)
            except OSError:
                mic_stream = safe_open_stream()
                continue
                
            if silero_vad.process(audio_data, RATE) > 0.5:
                recent_speech_time = time.time()

            oww_buffer.extend(audio_data)

            # 2. ACCUMULATE CHUNKS FOR OPENWAKEWORD
            if len(oww_buffer) < 2560:
                continue
                
            oww_chunk = oww_buffer[:2560]
            oww_buffer = oww_buffer[2560:]

            # 3. PREDICT WAKEWORD
            audio_np = np.frombuffer(oww_chunk, dtype=np.int16)
            prediction = owwModel.predict(audio_np)
            confidence = prediction[settings.wakeword_models]

            if confidence < settings.wakeword_threshold:
                continue

            # 4. CHECK VAD GATE (Early Exit if False Positive)
            if (time.time() - recent_speech_time) > WAKEWORD_VAD_GATE_TIMEOUT:
                logger.debug(f"VAD Blocked False Positive (Confidence: {confidence:.2f})")
                owwModel.reset()
                continue

            # ==========================================
            # --- WAKE WORD CONFIRMED! ---
            # ==========================================
            logger.info(f"Wake Word Detected! (Confidence: {confidence:.2f})")
            notify_orchestrator_wakeword()
            audio_player.play_local_wav(settings.wake_sound)

            # 5. RECORD COMMAND
            audio_recorded = record_until_silence(
                mic_stream, silero_vad, rate=RATE, silence_timeout=settings.silence_timeout
            )

            if not audio_recorded:
                logger.info("No audio recorded after wakeword.")
                notify_orchestrator_finished()
                owwModel.reset()
                recent_speech_time = 0.0
                continue

            # 6. PROCESS COMMAND
            try:
                audio_player.play_local_wav(settings.done_sound)
                notify_orchestrator_finished()
                
                response = orchestrator_client.send_audio_to_process(audio_recorded)
                
                if not response or response.status == "empty":
                    logger.info("Empty transcript from orchestrator.")
                    continue

                if response.status == "success":
                    if response.actions:
                        notify_orchestrator_wakeword()
                        time.sleep(0.1)
                        handle_satellite_actions(response.actions, audio_player)
                        
                    if response.audio_b64:
                        notify_orchestrator_wakeword()
                        time.sleep(0.1)
                        audio_player.play_audio_from_b64(response.audio_b64)

            except Exception as e:
                logger.error(f"Error during interaction loop: {e}")
            finally:
                notify_orchestrator_finished()
                owwModel.reset()
                recent_speech_time = 0.0
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
