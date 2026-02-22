import time
import collections
import base64
import io
import os
import logging
import pyaudio
from pydub import AudioSegment

logger = logging.getLogger("Satellite.AudioIO")

class AudioPlayer:
    def __init__(self, audio_manager, output_rate, settings):
        self.audio_manager = audio_manager
        self.OUTPUT_RATE = output_rate
        self.settings = settings
        self.speaker_stream = None

    def _play_normalized_audio(self, audio_segment: AudioSegment):
        normalized_audio = audio_segment.set_frame_rate(self.OUTPUT_RATE).set_channels(
            self.settings.output_channels
        )
        
        if hasattr(self.settings, "output_delay") and self.settings.output_delay and self.settings.output_delay > 0:
            delay_ms = int(self.settings.output_delay)
            silence = AudioSegment.silent(duration=delay_ms, frame_rate=self.OUTPUT_RATE).set_channels(self.settings.output_channels)
            normalized_audio = silence + normalized_audio
            
        try:
            if self.speaker_stream is None:
                self.speaker_stream = self.audio_manager.open(
                    format=self.audio_manager.get_format_from_width(normalized_audio.sample_width),
                    channels=self.settings.output_channels,
                    rate=self.OUTPUT_RATE,
                    output=True,
                    output_device_index=self.settings.speaker_index,
                )

            logger.debug(f"Playing audio ({normalized_audio.duration_seconds:.2f}s)...")
            self.speaker_stream.write(normalized_audio.raw_data)
            self.speaker_stream.stop_stream()
            self.speaker_stream.close()
            self.speaker_stream = None

        except Exception as e:
            logger.error(f"Audio playback failed: {e}")
            if self.speaker_stream is not None:
                try: self.speaker_stream.close()
                except: pass
            self.speaker_stream = None

    def play_local_wav(self, file_path):
        if not file_path or not os.path.exists(file_path):
            return
        try:
            self._play_normalized_audio(AudioSegment.from_wav(file_path))
        except Exception as e:
            logger.error(f"Failed to load local sound {file_path}: {e}")

    def play_audio_from_b64(self, b64_string):
        try:
            audio_data = base64.b64decode(b64_string)
            self._play_normalized_audio(AudioSegment.from_file(io.BytesIO(audio_data), format="wav"))
        except Exception as e:
            logger.error(f"Failed to load base64 audio: {e}")

def record_until_silence(mic_stream, vad_model, rate=16000, max_seconds=15, silence_timeout=3.0):
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
            recovered_data = mic_stream.read(available_frames, exception_on_overflow=False)
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
