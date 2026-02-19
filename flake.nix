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
        websocket-client
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
              type = lib.types.package;
              default = defaultPkg;
              description = "The satellite package to use.";
            };
            environmentFile = mkOption {
              type = types.nullOr types.path;
              default = null;
              description = "Path to an environment file for secrets (e.g., API keys if required).";
            };

            orchestratorUrl = mkOption {
              type = types.str;
              default = "http://localhost:8000";
              description = "The URL of the Voice Assistant Orchestrator.";
            };

            micDeviceIndex = mkOption {
              type = types.nullOr types.int;
              default = null;
              description = "Optional specific PortAudio device index for the microphone.";
            };

            wakewordModel = mkOption {
              type = types.str;
              default = "alexa";
              description = "The wakeword model to use (alexa, etc).";
            };

            vadThreshold = mkOption {
              type = types.float;
              default = 0.5;
              description = "Voice Activity Detection sensitivity.";
            };
          };

          # Ensure the logic uses 'cfg.package' in ExecStart
          config = lib.mkIf cfg.enable {
            systemd.services.voice-satellite = {
              description = "Voice Assistant Satellite Service";
              wantedBy = [ "multi-user.target" ];
              after = [
                "network.target"
                "sound.target"
              ];

              serviceConfig = {
                ExecStart = "${cfg.package}/bin/voice-satellite";

                EnvironmentFile = lib.mkIf (cfg.environmentFile != null) cfg.environmentFile;

                # --- Audio & Performance ---
                # User needs to be in 'audio' group to access the mic
                SupplementaryGroups = [ "audio" ];

                # Realtime priority to prevent audio glitches (optional)
                CPUSchedulingPolicy = "fifo";
                CPUSchedulingPriority = 50;

                # --- Hardening ---
                DynamicUser = true;
                ProtectSystem = "strict";
                ProtectHome = true;
                PrivateTmp = true;
                # Required for PortAudio/ALSA to see hardware
                DeviceAllow = [ "/dev/snd" ];
                DevicePolicy = "closed";
              };

              environment = {
                ORCHESTRATOR_URL = cfg.settings.orchestratorUrl;
                WAKEWORD_MODEL = cfg.settings.wakewordModel;
                VAD_THRESHOLD = toString cfg.settings.vadThreshold;
                MIC_INDEX = lib.mkIf (cfg.settings.micDeviceIndex != null) (toString cfg.settings.micDeviceIndex);

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
