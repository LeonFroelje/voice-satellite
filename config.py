import argparse
import os
from typing import Optional
from pydantic import SecretStr, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


class SatelliteSettings(BaseSettings):
    # --- Orchestrator Connection ---
    orchestrator_host: str = Field(
        default="localhost",
        description="The Hostname or ip address of the orchestrator",
    )
    orchestrator_port: int = Field(
        default=8000, description="The port of the orchestrator api"
    )
    orchestrator_protocol: str = Field(default="http", description="http or https")
    orchestrator_token: Optional[SecretStr] = Field(
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
        default=1000,
        description="The delay for TTS audio output stream in milliseconds",
    )
    output_channels: int = Field(default=1, description="The number of output channels")
    silence_timeout: int = Field(
        default=2,
        description="The silence duration in seconds after which command recording should stop",
    )

    # --- Context ---
    room: Optional[str] = Field(
        default=None,
        description="The physical location of this satellite (sent to Orchestrator for context)",
    )
    language: str = Field(
        default="de", description="Language code for STT (e.g., 'en', 'de', 'es')"
    )
    # --- System ---
    log_level: str = "INFO"
    # --- Sound Effects ---
    wake_sound: Optional[str] = Field(
        default=os.path.join(BASE_DIR, "assets", "sounds", "meow.wav"),
        description="Path to WAV file to play when wakeword is detected",
    )
    done_sound: Optional[str] = Field(
        default=os.path.join(BASE_DIR, "assets", "sounds", "meow.wav"),
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
    parser.add_argument("--orchestrator-host")
    parser.add_argument("--orchestrator-protocol")
    parser.add_argument("--orchestrator-port")
    parser.add_argument("--orchestrator-token", help="API Token for Orchestrator")

    parser.add_argument("--mic-index", type=int, help="Microphone Device Index")
    parser.add_argument("--speaker-index", help="Index of output device")
    parser.add_argument(
        "--wakeword-threshold", type=float, help="Wakeword sensitivity (0.0-1.0)"
    )
    parser.add_argument("--silence-timeout", help="VAD silence timeout")
    parser.add_argument("--language", help="Language code (en, de, etc.)")
    parser.add_argument("--room", help="Room name (e.g., kitchen, bedroom)")
    parser.add_argument("--log-level", help="Logging Level (DEBUG, INFO)")
    parser.add_argument("--output-delay", help="Output delay in seconds")
    parser.add_argument("--output-channels", help="The number of output channels")
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
