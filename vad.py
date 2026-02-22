import os
import urllib.request
import logging
import numpy as np
import onnxruntime as ort

logger = logging.getLogger("Satellite.VAD")

def ensure_silero_vad_model():
    """Downloads the lightweight Silero VAD ONNX model if it's not present locally."""
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    model_path = os.path.join(BASE_DIR, "assets", "models", "silero_vad.onnx")
    
    # Ensure directories exist
    os.makedirs(os.path.dirname(model_path), exist_ok=True)
    
    if not os.path.exists(model_path):
        logger.info("Downloading Silero VAD ONNX model (~1.8MB)...")
        url = "https://github.com/snakers4/silero-vad/raw/v5.1.2/src/silero_vad/data/silero_vad.onnx"
        urllib.request.urlretrieve(url, model_path)
        logger.info("Downloaded silero_vad.onnx")
    return model_path

class SileroVAD:
    def __init__(self, model_path):
        options = ort.SessionOptions()
        options.inter_op_num_threads = 1
        options.intra_op_num_threads = 1
        self.session = ort.InferenceSession(model_path, sess_options=options)
        self.reset_states()

    def reset_states(self):
        self.state = np.zeros((2, 1, 128), dtype=np.float32)

    def process(self, audio_chunk_int16, sr=16000):
        audio_float32 = (
            np.frombuffer(audio_chunk_int16, dtype=np.int16).astype(np.float32) / 32768.0
        )
        ort_inputs = {
            "input": np.expand_dims(audio_float32, axis=0),
            "state": self.state,
            "sr": np.array(sr, dtype=np.int64),
        }
        ort_outs = self.session.run(None, ort_inputs)
        out, self.state = ort_outs
        return out[0][0]
