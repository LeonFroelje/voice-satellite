import os
import time
import requests
import threading
import logging
from config import settings

logger = logging.getLogger("Satellite.Comms")

def handle_satellite_actions(actions, audio_player):
    """Executes local actions requested by the Orchestrator."""
    for action in actions:
        if action.type == "set_volume":
            level = action.payload.get("level", 50)
            logger.info(f"Setting local volume to {level}%")
            os.system(f"amixer set Master {level}%")
            
        elif action.type == "start_timer":
            duration = action.payload.get("duration_seconds", 0)
            logger.info(f"Starting timer for {duration} seconds")

            def timer_thread(seconds):
                time.sleep(seconds)
                logger.info("Timer done!")
                audio_player.play_local_wav(settings.timer_sound)

            threading.Thread(target=timer_thread, args=(duration,), daemon=True).start()

def notify_orchestrator_wakeword():
    url = f"{settings.orchestrator_protocol}://{settings.orchestrator_host}:{settings.orchestrator_port}/event/wakeword"
    try:
        requests.post(url, data={"room": settings.room}, timeout=3)
        logger.debug(f"Triggered volume ducking for {settings.room}")
    except Exception as e:
        logger.error(f"Failed to trigger volume ducking: {e}")

def notify_orchestrator_finished():
    url = f"{settings.orchestrator_protocol}://{settings.orchestrator_host}:{settings.orchestrator_port}/event/finished"
    try:
        requests.post(url, data={"room": settings.room}, timeout=3)
        logger.debug(f"Triggered volume restore for {settings.room}")
    except Exception as e:
        logger.error(f"Failed to trigger volume restore: {e}")
