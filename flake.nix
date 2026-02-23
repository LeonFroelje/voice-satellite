{
  description = "Python devShells";

  inputs = {
    nixpkgs.url = "github:nixos/nixpkgs?ref=nixos-unstable";
    nixvim = {
      url = "github:nix-community/nixvim";
      inputs.nixpkgs.follows = "nixpkgs";
    };

    nixvimModules = {
      url = "github:LeonFroelje/nixvim-modules";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  outputs =
    {
      self,
      nixpkgs,
      nixvim,
      nixvimModules,
    }:
    let
      system = "x86_64-linux";
      pkgs = nixpkgs.legacyPackages.${system};
      # python = pkgs.python311;  <-- Change this
      python = pkgs.python3; # <-- To this (usually 3.12)
      # --- Custom Packages ---

      models = {
        alexa = pkgs.fetchurl {
          url = "https://github.com/dscripka/openWakeWord/releases/download/v0.5.1/alexa_v0.1.onnx";
          hash = "sha256-b/VmoB0SZw6NnjxZ2jJlHbFXXRcnKmAbf4o5KD37rj4=";
        };
        embedding = pkgs.fetchurl {
          url = "https://github.com/dscripka/openWakeWord/releases/download/v0.5.1/embedding_model.onnx";
          hash = "sha256-cNFkKQwdCV0dTuFJvF4AVDJQpzFrWfMdBWz/e9MHXB8=";
        };
        melspectrogram = pkgs.fetchurl {
          url = "https://github.com/dscripka/openWakeWord/releases/download/v0.5.1/melspectrogram.onnx";
          hash = "sha256-uisOD4t7h1NposicsTNg/1O6xDbyiVzO2fR5+mXrF28=";
        };
        silero_vad = pkgs.fetchurl {
          url = "https://github.com/snakers4/silero-vad/raw/v5.1.2/src/silero_vad/data/silero_vad.onnx";
          hash = "sha256-JiOilT9v89LB5hdAxs23FoEzR5smff7xFKSjzFvdeI8";
        };
      };
      # OpenWakeWord is not in nixpkgs, so we package it here.
      openwakeword = python.pkgs.buildPythonPackage rec {
        pname = "openwakeword";
        version = "0.6.0";
        pyproject = true;

        src = python.pkgs.fetchPypi {
          inherit pname version;
          hash = "sha256-NoWNkPEYPjB0hVl6kSpOPDOEsU6pkj+D/q/658FWVWU=";
        };
        postPatch = ''
          sed -i '/tflite-runtime/d' setup.py
          if [ -f requirements.txt ]; then
            sed -i '/tflite-runtime/d' requirements.txt
          fi
        '';

        postInstall = ''
          TARGET_DIR="$out/${python.sitePackages}/openwakeword/resources/models"

          echo "Installing models to: $TARGET_DIR"
          mkdir -p "$TARGET_DIR"

          # Copy models
          cp ${models.embedding} "$TARGET_DIR/embedding_model.onnx"
          cp ${models.melspectrogram} "$TARGET_DIR/melspectrogram.onnx"
          cp ${models.alexa} "$TARGET_DIR/alexa_v0.1.onnx"


          # List files to verify in build logs
          ls -R "$out/${python.sitePackages}/openwakeword"
          # Copy assets
        '';
        propagatedBuildInputs = with python.pkgs; [
          onnxruntime
          scipy
          scikit-learn
          numpy
          setuptools
          tqdm
          requests
        ];
      };

      # --- Dependency List ---
      satelliteDependencies = with python.pkgs; [
        # Core Audio/Video
        av
        pyaudio
        pydub

        # AI / Logic
        openwakeword
        onnxruntime
        numpy
        scipy

        # Network & Storage
        boto3
        aiomqtt

        # Utilities
        pydantic
        pydantic-settings
        python-dotenv
        certifi
        tqdm
      ];

    in
    {
      # --- PACKAGE BUILD ---
      packages.${system} = {
        default = python.pkgs.buildPythonApplication {
          pname = "voice-satellite";
          version = "0.1.0";
          pyproject = true;
          src = ./.;

          propagatedBuildInputs = satelliteDependencies;

          # Runtime Dependencies (Binaries)
          # We need to ensure 'ffmpeg' is in the PATH for pydub to find it
          nativeBuildInputs = [
            pkgs.makeWrapper
          ];

          postInstall = ''
            mkdir -p $out/${python.sitePackages}/assets
            mkdir $out/${python.sitePackages}/assets/models
            cp ${models.silero_vad} $out/${python.sitePackages}/assets/models/silero_vad.onnx
            if [ -d "./assets/" ]; then
              cp -r ./assets/* $out/${python.sitePackages}/assets/
            fi
            wrapProgram $out/bin/voice-satellite \
              --prefix PATH : ${pkgs.lib.makeBinPath [ pkgs.ffmpeg_7-headless ]}
          '';
        };
      };
      nixosModules.default =
        {
          config,
          lib,
          pkgs,
          ...
        }:
        let
          cfg = config.services.voice-satellite;
          defaultPkg = self.packages.${pkgs.system}.default;
        in
        {
          options.services.voice-satellite = with lib; {
            enable = mkEnableOption "Voice Assistant Satellite";

            package = mkOption {
              type = types.package;
              default = defaultPkg;
              description = "The satellite package to use.";
            };

            environmentFile = mkOption {
              type = types.nullOr types.path;
              default = null;
              description = ''
                Path to an environment file for secrets.
                To prevent leaks, this file should contain:
                - SAT_S3_SECRET_KEY
                - SAT_MQTT_PASSWORD (if your broker requires auth)
              '';
            };

            # --- MQTT Connection ---
            mqttHost = mkOption {
              type = types.str;
              default = "localhost";
              description = "Mosquitto broker IP/Hostname";
            };
            mqttPort = mkOption {
              type = types.int;
              default = 1883;
              description = "Mosquitto broker port";
            };
            mqttUser = mkOption {
              type = types.nullOr types.str;
              default = null;
              description = "Username used to authenticate with MQTT broker";
            };

            # --- Object Storage (S3 Compatible) ---
            s3Endpoint = mkOption {
              type = types.str;
              default = "http://localhost:3900";
              description = "URL to Garage/SeaweedFS";
            };
            s3AccessKey = mkOption {
              type = types.str;
              default = "your-access-key";
              description = "S3 Access Key";
            };
            s3Bucket = mkOption {
              type = types.str;
              default = "voice-commands";
              description = "S3 Bucket Name";
            };

            dataDir = mkOption {
              type = types.str;
              default = "/var/lib/voice-satellite";
            };
            cacheDir = mkOption {
              type = types.str;
              default = "${cfg.dataDir}/cache";
              description = "Path to cache directory";
            };

            # --- Audio Settings ---
            micIndex = mkOption {
              type = types.nullOr types.int;
              default = null;
              description = "The index of the microphone device.";
            };
            speakerIndex = mkOption {
              type = types.nullOr types.int;
              default = null;
              description = "The index of the output device.";
            };
            wakewordThreshold = mkOption {
              type = types.float;
              default = 0.6;
              description = "Sensitivity (0.0-1.0). Higher = fewer false positives.";
            };
            wakewordModels = mkOption {
              type = types.str;
              default = "alexa";
              description = "Comma-separated list of wakeword models to load.";
            };
            outputDelay = mkOption {
              type = types.int;
              default = 1000;
              description = "The delay for TTS audio output stream in milliseconds.";
            };
            useVad = mkOption {
              type = types.bool;
              default = true;
              description = "Whether to use Voice Activity Detection (VAD).";
            };
            outputChannels = mkOption {
              type = types.int;
              default = 1;
              description = "The number of output channels.";
            };
            silenceTimeout = mkOption {
              type = types.int;
              default = 2;
              description = "Silence duration in seconds before stopping recording.";
            };

            # --- Context & Language ---
            room = mkOption {
              type = types.nullOr types.str;
              default = null;
              description = "Physical location of this satellite.";
            };
            language = mkOption {
              type = types.str;
              default = "de";
              description = "Language code for STT (e.g., 'en', 'de').";
            };

            # --- System & Sounds ---
            logLevel = mkOption {
              type = types.enum [
                "DEBUG"
                "INFO"
                "WARNING"
                "ERROR"
              ];
              default = "INFO";
              description = "Logging level.";
            };
            wakeSound = mkOption {
              type = types.nullOr types.path;
              default = null;
              description = "Path to WAV file for wakeword detection.";
            };
            doneSound = mkOption {
              type = types.nullOr types.path;
              default = null;
              description = "Path to WAV file for processing finished.";
            };

            # --- Squeezelite Music Assistant ---
            configureSqueezelite = mkOption {
              type = types.bool;
              default = true;
              description = "Whether to install and configure squeezelite for music assistant";
            };

            musicAssistantIp = mkOption {
              type = types.str;
              default = "127.0.0.1";
              description = "IP address of the Music Assistant server";
            };
          };

          config = lib.mkIf cfg.enable {
            users.users.satellite = {
              isNormalUser = true;
              description = "Headless Voice Satellite User";
              extraGroups = [
                "audio"
                "video"
              ];
              # Crucial: Boots a background user session (and PipeWire) on startup
              linger = true;
            };

            systemd.user.services.squeezelite = lib.mkIf cfg.configureSqueezelite {
              description = "Squeezelite Service (PulseAudio)";
              wantedBy = [ "default.target" ];
              unitConfig.ConditionUser = "satellite";

              serviceConfig = {
                ExecStart = "${pkgs.squeezelite}/bin/squeezelite -n ${
                  if cfg.room != null then cfg.room else "Satellite"
                } -s ${cfg.musicAssistantIp}";

                Restart = "always";
                RestartSec = "3s";
              };
            };

            services.pipewire = {
              enable = true;
              alsa.enable = true;
              alsa.support32Bit = true;
              pulse.enable = true;
              wireplumber.enable = true;
            };

            security.rtkit.enable = true;

            systemd.user.services.voice-satellite = {
              description = "Voice Assistant Satellite Service";
              wantedBy = [ "default.target" ];
              after = [
                "network.target"
                "sound.target"
              ];
              unitConfig.ConditionUser = "satellite";

              serviceConfig = {
                ExecStart = "${cfg.package}/bin/voice-satellite";
                EnvironmentFile = lib.optional (cfg.environmentFile != null) cfg.environmentFile;

                Restart = "always";
                RestartSec = "3s";

                # Sandbox Settings
                DynamicUser = false; # Must be false to use the static 'satellite' user
                ProtectSystem = "strict";
                ProtectHome = "read-only";
                PrivateTmp = true;

                # If using /var/lib/voice-satellite, ensure it's readable/writable by the service
                StateDirectory = cfg.dataDir;
              };

              environment =
                let
                  env = {
                    PYTHONUNBUFFERED = "1";

                    # Connection & S3
                    SAT_MQTT_HOST = cfg.mqttHost;
                    SAT_MQTT_PORT = toString cfg.mqttPort;
                    SAT_MQTT_USER = cfg.mqttUser;

                    SAT_S3_ENDPOINT = cfg.s3Endpoint;
                    SAT_S3_ACCESS_KEY = cfg.s3AccessKey;
                    SAT_S3_BUCKET = cfg.s3Bucket;

                    SAT_CACHE_DIR = cfg.cacheDir;

                    # Audio Settings
                    SAT_MIC_INDEX = if cfg.micIndex != null then toString cfg.micIndex else null;
                    SAT_SPEAKER_INDEX = if cfg.speakerIndex != null then toString cfg.speakerIndex else null;
                    SAT_WAKEWORD_THRESHOLD = toString cfg.wakewordThreshold;
                    SAT_WAKEWORD_MODELS = cfg.wakewordModels;
                    SAT_OUTPUT_DELAY = toString cfg.outputDelay;
                    SAT_OUTPUT_CHANNELS = toString cfg.outputChannels;
                    SAT_SILENCE_TIMEOUT = toString cfg.silenceTimeout;
                    SAT_USE_VAD = if cfg.useVad then "true" else "false";

                    # Context, Language, System
                    SAT_ROOM = cfg.room;
                    SAT_LANGUAGE = cfg.language;
                    SAT_LOG_LEVEL = cfg.logLevel;
                    SAT_WAKE_SOUND = if cfg.wakeSound != null then toString cfg.wakeSound else null;
                    SAT_DONE_SOUND = if cfg.doneSound != null then toString cfg.doneSound else null;
                  };
                in
                lib.filterAttrs (n: v: v != null) env;
            };
          };
        };

      devShells.${system} = {
        default =
          (pkgs.buildFHSEnv {
            name = "Python dev shell";
            targetPkgs =
              p: with p; [
                fd
                ripgrep
                (nixvimModules.lib.mkNvim [ nixvimModules.nixosModules.python ])
                # CHANGED: python314 -> python311 (or python312)
                python311
                python311Packages.pip
                python311Packages.virtualenv # Recommended to create a venv inside the FHS
                portaudio
                pkg-config
                zlib
                glib
                # We keep libraries here for runtime, but pip won't need to compile against them
                # if it finds a wheel.
                ffmpeg_7-headless
                cargo
                rustc
                libgcc
                # gccgo15 might be overkill/conflict, standard gcc is usually included in FHS
              ];
            runScript = ''
              zsh
              source .venv/bin/activate
              set -o allexport
              source .env 
              set +o allexport
            '';
          }).env;
        uv =
          (pkgs.buildFHSEnv {
            name = "uv-shell";
            targetPkgs =
              p: with p; [
                uv
                zlib
                glib
                openssl
                stdenv.cc.cc.lib
                (nixvimModules.lib.mkNvim [ nixvimModules.nixosModules.python ])
              ];
            runScript = "zsh";

            multiPkgs = p: [
              p.zlib
              p.openssl
            ];
          }).env;
      };
    };
}
