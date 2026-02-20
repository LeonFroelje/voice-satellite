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
          url = "https://github.com/snakers4/silero-vad/raw/master/src/silero_vad/data/silero_vad.onnx";
          hash = "sha256-GhU6IvRQnikqlOZ9b5uF6N6yW0mIaCt+F0xlJ52HiOM";
        };
      };
      # OpenWakeWord is not in nixpkgs, so we package it here.
      # Note: We stripped tflite-runtime as discussed.
      openwakeword = python.pkgs.buildPythonPackage rec {
        pname = "openwakeword";
        version = "0.6.0";
        # format = "pyproject";
        pyproject = true;

        src = python.pkgs.fetchPypi {
          inherit pname version;
          # 🔴 IMPORTANT: Run 'nix build', grab the hash from the error, and paste it here:
          hash = "sha256-NoWNkPEYPjB0hVl6kSpOPDOEsU6pkj+D/q/658FWVWU=";
        };
        postPatch = ''
          sed -i '/tflite-runtime/d' setup.py
          if [ -f requirements.txt ]; then
            sed -i '/tflite-runtime/d' requirements.txt
          fi
        '';

        postInstall = ''
          # Define the destination directory
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
        av # (PyAV) - Builds against ffmpeg automatically
        pyaudio # Builds against portaudio automatically
        pydub # Wrapper for ffmpeg

        # AI / Logic
        openwakeword # Our custom package above
        onnxruntime
        numpy
        scipy
        requests

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
          nativeBuildInputs = [ pkgs.makeWrapper ];

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
            enable = lib.mkEnableOption "Voice Assistant Satellite";
            package = lib.mkOption {
              type = types.package;
              default = defaultPkg;
              description = "The satellite package to use.";
            };
            environmentFile = mkOption {
              type = types.nullOr types.path;
              default = null;
              description = "Path to an environment file for secrets (e.g., SAT_API_TOKEN).";
            };

            orchestratorUrl = mkOption {
              type = types.str;
              default = "http://localhost:8000/process"; # Matched default in settings.py
              description = "The URL of the Voice Assistant Orchestrator.";
            };

            # Split Whisper URL into Host and Port to match Pydantic fields
            whisperHost = mkOption {
              type = types.str;
              default = "localhost";
              description = "Hostname of the whisper-live server.";
            };
            whisperPort = mkOption {
              type = types.int;
              default = 9090;
              description = "Port of the whisper-live server.";
            };

            micDeviceIndex = mkOption {
              type = types.nullOr types.int;
              default = null;
              description = "Optional specific PortAudio device index for the microphone.";
            };

            wakewordModels = mkOption {
              type = types.str;
              default = "alexa";
              description = "Comma-separated list of wakeword models to load.";
            };

            wakewordThreshold = mkOption {
              type = types.float;
              default = 0.6;
              description = "Sensitivity (0.0-1.0).";
            };

            room = mkOption {
              type = types.nullOr types.str;
              default = null;
              description = "Name of the room the satellite is placed in.";
            };

            wakeSound = mkOption {
              type = types.nullOr types.path;
              default = null;
              description = "Path to the WAV file for wakeword detection.";
            };

            doneSound = mkOption {
              type = types.nullOr types.path;
              default = null;
              description = "Path to the WAV file for transcription finished.";
            };
          };

          config = lib.mkIf cfg.enable {
            systemd.services.voice-satellite = {
              # ... (Keep your existing description, after, and wantedBy)

              serviceConfig = {
                ExecStart = "${cfg.package}/bin/voice-satellite";
                EnvironmentFile = lib.mkIf (cfg.environmentFile != null) cfg.environmentFile;

                # Audio permissions
                SupplementaryGroups = [ "audio" ];
                DeviceAllow = [ "/dev/snd" ];
                DevicePolicy = "closed";
                DynamicUser = true;
                # ... (Rest of your hardening)
              };

              # Map Nix options to SAT_ prefixed environment variables
              environment = lib.filterAttrs (n: v: v != null) {
                SAT_ORCHESTRATOR_URL = cfg.orchestratorUrl;
                SAT_ROOM = cfg.room;
                SAT_WHISPER_HOST = cfg.whisperHost;
                SAT_WHISPER_PORT = toString cfg.whisperPort;
                SAT_WAKEWORD_MODELS = cfg.wakewordModels;
                SAT_WAKEWORD_THRESHOLD = toString cfg.wakewordThreshold;
                SAT_MIC_INDEX = if (cfg.micDeviceIndex != null) then toString cfg.micDeviceIndex else null;
                SAT_WAKE_SOUND = if (cfg.wakeSound != null) then toString cfg.wakeSound else null;
                SAT_DONE_SOUND = if (cfg.doneSound != null) then toString cfg.doneSound else null;

                PYTHONUNBUFFERED = "1";
              };
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
