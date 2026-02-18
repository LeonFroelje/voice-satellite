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
    in
    {
      packages.${system}.dockerEnv = pkgs.buildEnv {
        name = "Satellite docker dependencies";
        paths = [
          # Runtime dependencies
          pkgs.python311
          pkgs.python311Packages.pip
          pkgs.python311Packages.setuptools
          pkgs.ffmpeg_7-headless
          pkgs.portaudio

          # Build-time dependencies (needed for pip install to work)
          pkgs.pkg-config
          pkgs.stdenv.cc # Includes GCC and standard C libraries
          pkgs.gnumake
        ];
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
