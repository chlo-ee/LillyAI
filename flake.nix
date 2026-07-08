{
  description = "LillyAI — modular, event-driven AI assistant framework";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
  };

  outputs = { self, nixpkgs }:
    let
      forAllSystems = nixpkgs.lib.genAttrs [
        "x86_64-linux"
        "aarch64-linux"
        "aarch64-darwin"
      ];

      pythonEnvFor = pkgs: pkgs.python3.withPackages (ps: with ps; [
        imapclient
        beautifulsoup4
        requests
        matrix-nio
        paho-mqtt
        caldav
        markdown
      ]);
    in
    {
      packages = forAllSystems (system:
        let
          pkgs = nixpkgs.legacyPackages.${system};
          pythonEnv = pythonEnvFor pkgs;
        in
        {
          default = pkgs.stdenv.mkDerivation {
            pname = "lillyai";
            version = "0.2.0";
            src = ./.;

            nativeBuildInputs = [ pkgs.makeWrapper ];

            dontBuild = true;
            installPhase = ''
              runHook preInstall
              mkdir -p $out/share/lillyai
              cp -r LillyAI.py Router.py Scheduler.py PromptTools.py Logging.py Modules \
                $out/share/lillyai/
              makeWrapper ${pythonEnv}/bin/python $out/bin/lillyai \
                --add-flags "-m LillyAI" \
                --set PYTHONPATH $out/share/lillyai \
                --set PYTHONUNBUFFERED 1
              runHook postInstall
            '';
          };
        });

      nixosModules.default = { config, lib, pkgs, ... }:
        let
          cfg = config.services.lillyai;
        in
        {
          options.services.lillyai = {
            enable = lib.mkEnableOption "LillyAI assistant";

            package = lib.mkOption {
              type = lib.types.package;
              default = self.packages.${pkgs.stdenv.hostPlatform.system}.default;
              defaultText = lib.literalExpression "lillyai from its flake";
              description = "The LillyAI package to run.";
            };

            configFile = lib.mkOption {
              # A string on purpose: a path literal would be copied into the
              # world-readable nix store, and the config carries credentials.
              # Point this at a sops-nix secret path instead.
              type = lib.types.str;
              example = "/run/secrets/lilly/config.json";
              description = ''
                Path to Lilly's config.json (see CONFIG.md). Read at service
                start via systemd LoadCredential, so it may be root-owned.
                Relative paths inside it (context databases, …) resolve to
                /var/lib/lillyai.
              '';
            };
          };

          config = lib.mkIf cfg.enable {
            systemd.services.lillyai = {
              description = "LillyAI Core Service";
              wantedBy = [ "multi-user.target" ];
              after = [ "network-online.target" ];
              wants = [ "network-online.target" ];
              serviceConfig = {
                # %d = the per-service credentials directory
                ExecStart = "${cfg.package}/bin/lillyai %d/config.json";
                LoadCredential = "config.json:${cfg.configFile}";
                Restart = "on-failure";
                RestartSec = "10s";
                DynamicUser = true;
                StateDirectory = "lillyai";
                WorkingDirectory = "/var/lib/lillyai";
                NoNewPrivileges = true;
                ProtectSystem = "strict";
                ProtectHome = true;
                PrivateTmp = true;
              };
            };
          };
        };
    };
}
