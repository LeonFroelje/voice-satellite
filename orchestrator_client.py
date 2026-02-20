import io
import wave
import requests
import pyaudio
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, SecretStr
from config import settings
import logging

logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("Satellite")


class Action(BaseModel):
    type: str
    payload: Dict[str, Any]


class OrchestratorResponse(BaseModel):
    status: str
    transcription: Optional[str] = None
    response_text: Optional[str] = None
    audio_b64: Optional[str] = None
    actions: List[Action] = []


class OrchestratorClient:
    def __init__(
        self, host: str, port: int, api_token: SecretStr, audio_manager, protocol: str
    ):
        self.host = host
        self.port = port
        self.api_token = api_token
        self.protocol = protocol
        self.audio_manager = audio_manager

    def send_audio_to_process(
        self, audio_bytes: bytes
    ) -> Optional[OrchestratorResponse]:
        logger.info("Sending audio to Orchestrator for processing...")

        # Prepare WAV buffer
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(self.audio_manager.get_sample_size(pyaudio.paInt16))
            wf.setframerate(16000)
            wf.writeframes(audio_bytes)
        buffer.seek(0)

        try:
            url = f"{self.protocol}://{self.host}:{self.port}/process"
            files = {"file": ("audio.wav", buffer, "audio/wav")}
            # Added room context so orchestrator knows which volume to lower
            data = {"room": settings.room}

            headers = {}
            if self.api_token:
                headers["Authorization"] = f"Bearer {self.api_token.get_secret_value()}"

            response = requests.post(
                url, files=files, data=data, headers=headers, timeout=30
            )

            if response.ok:
                # Validate and parse the response into our Pydantic model
                return OrchestratorResponse.model_validate(response.json())
            else:
                logger.error(
                    f"Orchestrator Error: {response.status_code} - {response.text}"
                )
        except Exception as e:
            logger.error(f"Failed to connect to Orchestrator: {e}")

        return None
