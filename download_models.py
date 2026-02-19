from openwakeword.utils import download_models
import logging


def main():
    logging.basicConfig(level=logging.INFO)
    print("Downloading openwakeword models...")
    # This downloads all default models.
    # If you only use specific ones, you can specify them here.
    download_models()
    print("Models downloaded successfully.")


if __name__ == "__main__":
    main()
