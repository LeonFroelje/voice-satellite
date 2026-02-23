import time
import os
import logging
import io
import base64
import collections
import threading
from pydub import AudioSegment

logger = logging.getLogger("Satellite.AudioIO")


class AudioPlayer:
    def __init__(self, audio_manager, output_rate, settings):
        self.audio_manager = audio_manager
        self.OUTPUT_RATE = output_rate
        self.settings = settings

        # State tracking for interruption
        self._play_thread = None
        self._stop_event = threading.Event()
        self._stream_lock = threading.Lock()

    def stop(self):
        """Immediately stops any currently playing audio."""
        if self._play_thread and self._play_thread.is_alive():
            logger.info("Interrupting current audio playback...")
            self._stop_event.set()  # Signal the thread to stop
            self._play_thread.join(timeout=2.0)  # Wait for thread to clean up

    def play_local_wav(self, file_path, loop_duration=0):
        if not file_path or not os.path.exists(file_path):
            return
        try:
            self._play_normalized_audio(AudioSegment.from_wav(file_path), loop_duration)
        except Exception as e:
            logger.error(f"Failed to load local sound {file_path}: {e}")

    def _play_normalized_audio(
        self, audio_segment: AudioSegment, loop_duration: float = 0
    ):
        """Prepares audio and spawns a background thread for non-blocking playback."""
        self.stop()
        self._stop_event.clear()

        normalized_audio = audio_segment.set_frame_rate(self.OUTPUT_RATE).set_channels(
            self.settings.output_channels
        )

        if (
            hasattr(self.settings, "output_delay")
            and self.settings.output_delay
            and self.settings.output_delay > 0
        ):
            delay_ms = int(self.settings.output_delay)
            silence = AudioSegment.silent(
                duration=delay_ms, frame_rate=self.OUTPUT_RATE
            ).set_channels(self.settings.output_channels)
            normalized_audio = silence + normalized_audio

        self._play_thread = threading.Thread(
            target=self._playback_worker,
            args=(normalized_audio, loop_duration),
            daemon=True,
        )
        self._play_thread.start()

    def _playback_worker(self, audio_segment: AudioSegment, loop_duration: float):
        """Runs in a background thread, pushing chunks and handling loops."""
        speaker_stream = None
        try:
            with self._stream_lock:
                speaker_stream = self.audio_manager.open(
                    format=self.audio_manager.get_format_from_width(
                        audio_segment.sample_width
                    ),
                    channels=self.settings.output_channels,
                    rate=self.OUTPUT_RATE,
                    output=True,
                    output_device_index=self.settings.speaker_index,
                )

            raw_data = audio_segment.raw_data
            data_length = len(raw_data)
            chunk_size = 4096
            pointer = 0

            start_time = time.time()

            # Loop until stopped by wake word OR we exceed the max duration (if looping)
            while not self._stop_event.is_set():
                end_pointer = min(pointer + chunk_size, data_length)
                chunk = raw_data[pointer:end_pointer]

                speaker_stream.write(chunk)
                pointer = end_pointer

                # Check if we hit the end of the file
                if pointer >= data_length:
                    if loop_duration > 0 and (time.time() - start_time) < loop_duration:
                        # Reset pointer to start of audio to loop it
                        pointer = 0
                    else:
                        # Reached the end and no looping required (or loop time expired)
                        break

        except Exception as e:
            logger.error(f"Background audio playback failed: {e}")

        finally:
            if speaker_stream:
                try:
                    with self._stream_lock:
                        speaker_stream.stop_stream()
                        speaker_stream.close()
                except Exception as cleanup_error:
                    logger.debug(f"Stream cleanup error: {cleanup_error}")

    def play_audio_from_b64(self, b64_string):
        try:
            audio_data = base64.b64decode(b64_string)
            self._play_normalized_audio(
                AudioSegment.from_file(io.BytesIO(audio_data), format="wav")
            )
        except Exception as e:
            logger.error(f"Failed to load base64 audio: {e}")


def record_until_silence(
    mic_stream, vad_model, rate=16000, max_seconds=15, silence_timeout=3.0
):
    logger.info("Listening for command...")
    vad_model.reset_states()

    SILERO_CHUNK = 512
    start_time = time.time()
    last_speech_time = time.time()
    has_spoken = False

    processed_frames = []
    ring_buffer = collections.deque(maxlen=20)
    hangover_time = 0.8

    try:
        available_frames = mic_stream.get_read_available()
        if available_frames > 0:
            recovered_data = mic_stream.read(
                available_frames, exception_on_overflow=False
            )
            processed_frames.append(recovered_data)
    except Exception as e:
        logger.debug(f"Buffer recovery exception: {e}")

    while (time.time() - start_time) < max_seconds:
        data = mic_stream.read(SILERO_CHUNK, exception_on_overflow=False)
        speech_prob = vad_model.process(data, rate)
        current_time = time.time()

        if speech_prob > 0.3:
            last_speech_time = current_time
            has_spoken = True

        if has_spoken and (current_time - last_speech_time) < hangover_time:
            while ring_buffer:
                processed_frames.append(ring_buffer.popleft())
            processed_frames.append(data)
        else:
            ring_buffer.append(data)

        if has_spoken and (current_time - last_speech_time) > silence_timeout:
            break
        elif not has_spoken and (current_time - start_time) > 3.0:
            break

    return b"".join(processed_frames)
