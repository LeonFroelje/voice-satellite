import time
import logging
import pyaudio
import numpy as np
import asyncio
import threading
import json
import aiomqtt

from config import settings
from openwakeword.model import Model
from storage_client import StorageClient

from vad import ensure_silero_vad_model, SileroVAD
from actions import handle_satellite_actions
from audio_io import AudioPlayer, record_until_silence

logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("Satellite.Main")

# --- Audio Constants ---
FORMAT = pyaudio.paInt16
CHANNELS = 1
RATE = 16000
CHUNK = 512  # Changed to 512 for continuous VAD
OUTPUT_RATE = 44100
WAKEWORD_VAD_GATE_TIMEOUT = 0.8


def audio_listening_loop(loop, mqtt_queue, audio_manager, audio_player):
    """Runs in a background thread to prevent PyAudio from blocking the async network loop."""
    storage_client = StorageClient(audio_manager)
    owwModel = Model(wakeword_models=[settings.wakeword_models])
    silero_vad = SileroVAD(ensure_silero_vad_model())

    mic_stream = audio_manager.open(
        format=FORMAT,
        channels=CHANNELS,
        rate=RATE,
        input=True,
        frames_per_buffer=CHUNK,
        input_device_index=settings.mic_index,
    )

    logger.info(f"Microphone listening started. Room: {settings.room}")
    recent_speech_time = 0.0
    oww_buffer = bytearray()

    while True:
        try:
            audio_data = mic_stream.read(CHUNK, exception_on_overflow=False)

            # 1. VAD Check
            if silero_vad.process(audio_data, RATE) > 0.5:
                recent_speech_time = time.time()

            oww_buffer.extend(audio_data)

            # 2. Accumulate OpenWakeWord Chunks
            if len(oww_buffer) < 2560:
                continue

            oww_chunk = oww_buffer[:2560]
            oww_buffer = oww_buffer[2560:]

            # 3. Predict Wakeword
            audio_np = np.frombuffer(oww_chunk, dtype=np.int16)
            prediction = owwModel.predict(audio_np)
            confidence = prediction[settings.wakeword_models]

            if confidence < settings.wakeword_threshold:
                continue

            if (
                time.time() - recent_speech_time
            ) > WAKEWORD_VAD_GATE_TIMEOUT and settings.use_vad:
                owwModel.reset()
                logger.debug(
                    f"VAD Blocked False Positive (Confidence: {confidence:.2f})"
                )
                continue

            # ==========================================
            # --- WAKE WORD CONFIRMED! ---
            # ==========================================
            audio_player.stop()
            logger.info(f"Wake Word Detected! (Confidence: {confidence:.2f})")
            audio_player.play_local_wav(settings.wake_sound, blocking=True)

            # Send async event to duck volume / notify other services
            loop.call_soon_threadsafe(
                mqtt_queue.put_nowait,
                {
                    "topic": f"voice/wakeword/{settings.room}",
                    "payload": {"room": settings.room, "status": "detected"},
                },
            )

            # 4. Record Command
            audio_recorded = record_until_silence(
                mic_stream,
                silero_vad,
                rate=RATE,
                silence_timeout=settings.silence_timeout,
            )

            if audio_recorded:
                audio_player.play_local_wav(settings.done_sound)
                audio_url = storage_client.upload_audio(audio_recorded)

                if audio_url:
                    # Send async event to trigger transcription service
                    loop.call_soon_threadsafe(
                        mqtt_queue.put_nowait,
                        {
                            "topic": "voice/audio/recorded",
                            "payload": {"room": settings.room, "audio_url": audio_url},
                        },
                    )

            # Reset state
            loop.call_soon_threadsafe(
                mqtt_queue.put_nowait,
                {
                    "topic": f"voice/finished/{settings.room}",
                    "payload": {"room": settings.room, "status": "done"},
                },
            )
            owwModel.reset()
            recent_speech_time = 0.0

        except Exception as e:
            logger.error(f"Error in audio thread: {e}")


async def main_async():
    audio_manager = pyaudio.PyAudio()
    audio_player = AudioPlayer(audio_manager, OUTPUT_RATE, settings)

    loop = asyncio.get_running_loop()
    mqtt_queue = asyncio.Queue()

    storage_client = StorageClient(audio_manager)
    # Spin up the blocking PyAudio listener in a background thread
    threading.Thread(
        target=audio_listening_loop,
        args=(loop, mqtt_queue, audio_manager, audio_player),
        daemon=True,
    ).start()

    logger.info("Connecting to MQTT broker...")

    # Setup aiomqtt connection
    async with aiomqtt.Client(settings.mqtt_host, port=settings.mqtt_port) as client:
        logger.info("Connected to MQTT broker.")

        # Subscribe to actions meant specifically for this voice's room
        await client.subscribe(f"satellite/{settings.room}/action")

        # Task 1: Listen for incoming MQTT messages (like executing actions)
        async def listen_mqtt():
            async for message in client.messages:
                topic = message.topic.value
                payload = json.loads(message.payload.decode())

                logger.debug(topic, payload)
                # Inside the async def listen_mqtt() loop:
                if topic == f"satellite/{settings.room}/action":
                    actions = payload.get("actions", [])
                    # Pass storage_client here!
                    logger.debug(actions)
                    handle_satellite_actions(actions, audio_player, storage_client)

        asyncio.create_task(listen_mqtt())

        # Task 2: Publish outgoing MQTT messages queued by the audio thread
        while True:
            msg = await mqtt_queue.get()
            await client.publish(msg["topic"], payload=json.dumps(msg["payload"]))


def main():
    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        logger.info("Satellite stopping...")


if __name__ == "__main__":
    main()
