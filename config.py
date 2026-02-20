import argparse
from typing import Optional
from pydantic import SecretStr, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class SatelliteSettings(BaseSettings):
    # --- Orchestrator Connection ---
    orchestrator_url: str = Field(
        default="http://localhost:8000/process",
        description="Full URL to the Orchestrator's processing endpoint",
    )
    api_token: Optional[SecretStr] = Field(
        default=None,
        description="Bearer token for authenticating with the Orchestrator",
    )

    # --- Audio Settings ---
    mic_index: Optional[int] = Field(
        default=None,
        description="The index of the microphone device (use verify_audio.py to find this)",
    )
    speaker_index: Optional[int] = Field(
        default=None,
        description="The index of the output device (use verify_audio.py to find this)",
    )
    wakeword_threshold: float = Field(
        default=0.6,
        description="Sensitivity (0.0-1.0). Higher = fewer false positives, harder to trigger.",
    )
    wakeword_models: str = Field(
        default="alexa", description="Comma-separated list of wakeword models to load"
    )
    output_delay: Optional[int] = Field(
        default=1, description="The delay for TTS audio output stream in seconds"
    )
    silence_timeout: int = Field(
        default=2,
        description="The silence duration in seconds after which command recording should stop",
    )

    # --- Context ---
    room: Optional[str] = Field(
        default=None,
        description="The physical location of this satellite (sent to Orchestrator for context)",
    )
    whisper_host: str = Field(
        default="localhost", description="Hostname or IP of the Whisper-Live server"
    )
    whisper_port: int = Field(
        default=9090, description="Port of the Whisper-Live server"
    )
    whisper_model: str = Field(
        default="small",
        description="Whisper model size (tiny, base, small, medium, large-v2, etc.)",
    )
    language: str = Field(
        default="de", description="Language code for STT (e.g., 'en', 'de', 'es')"
    )
    # --- System ---
    log_level: str = "INFO"
    # --- Sound Effects ---
    wake_sound: Optional[str] = Field(
        default="./assets/sounds/meow.wav",
        description="Path to WAV file to play when wakeword is detected",
    )
    done_sound: Optional[str] = Field(
        default="./assets/sounds/meow.wav",
        description="Path to WAV file to play when processing is finished",
    )
    # Pydantic Config: Tells it to read from .env files automatically
    model_config = SettingsConfigDict(env_prefix="SAT_")


def get_settings() -> SatelliteSettings:
    """
    Parses CLI arguments first, then initializes Settings.
    Precedence: CLI Args > Environment Vars > .env file > Defaults
    """
    parser = argparse.ArgumentParser(description="Voice Assistant Satellite")

    # Add arguments for every field you want controllable via CLI
    parser.add_argument("--orchestrator-url", help="URL of the Orchestrator API")
    parser.add_argument("--api-token", help="API Token for Orchestrator")

    parser.add_argument("--mic-index", type=int, help="Microphone Device Index")
    parser.add_argument("--speaker-index", help="Index of output device")
    parser.add_argument(
        "--wakeword-threshold", type=float, help="Wakeword sensitivity (0.0-1.0)"
    )
    parser.add_argument("--silence-timeout", help="VAD silence timeout")
    parser.add_argument("--whisper-host", help="Whisper server host")
    parser.add_argument("--whisper-port", type=int, help="Whisper server port")
    parser.add_argument("--whisper-model", help="Whisper model size")
    parser.add_argument("--language", help="Language code (en, de, etc.)")
    parser.add_argument("--room", help="Room name (e.g., kitchen, bedroom)")
    parser.add_argument("--log-level", help="Logging Level (DEBUG, INFO)")
    parser.add_argument("--output-delay", help="Output delay in seconds")
    # Inside get_settings() function, add these to the parser:
    parser.add_argument("--wake-sound", help="Path to wake sound WAV")
    parser.add_argument("--done-sound", help="Path to done sound WAV")
    args, unknown = parser.parse_known_args()
    print(args)

    # Create a dictionary of only the arguments that were actually provided via CLI
    # We replace hyphens with underscores to match the Pydantic field names
    cli_args = {k.replace("-", "_"): v for k, v in vars(args).items() if v is not None}
    print(cli_args)

    # Initialize Settings
    return SatelliteSettings(**cli_args)


# Create a global instance
settings = get_settings()
