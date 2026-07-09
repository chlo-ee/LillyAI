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

      # LillyVoice's E2EE support (matrix-nio[e2e]) builds against libolm,
      # which nixpkgs marks insecure. Same reasoning as the matrix host's
      # bridges: room keys never leave the home network and the homeserver
      # doesn't federate. Version-pinned — if an update moves olm, the eval
      # error names the new version to re-permit.
      pkgsFor = system: import nixpkgs {
        inherit system;
        config.permittedInsecurePackages = [ "olm-3.2.16" ];
      };

      corePythonEnv = pkgs: pkgs.python3.withPackages (ps: with ps; [
        imapclient
        beautifulsoup4
        requests
        matrix-nio
        paho-mqtt
        caldav
        markdown
      ]);

      voicePythonEnv = pkgs: pkgs.python3.withPackages (ps: with ps;
        [ matrix-nio aiohttp ]
        ++ (ps.matrix-nio.optional-dependencies.e2e or [ ]));
    in
    {
      packages = forAllSystems (system:
        let
          pkgs = pkgsFor system;

          mkApp = { name, entryModule, pythonEnv, extraWrapperArgs ? "" }:
            pkgs.stdenv.mkDerivation {
              pname = name;
              version = "0.2.0";
              src = ./.;

              nativeBuildInputs = [ pkgs.makeWrapper ];

              dontBuild = true;
              installPhase = ''
                runHook preInstall
                mkdir -p $out/share/lillyai
                cp -r LillyAI.py LillyVoice.py Router.py Scheduler.py \
                  PromptTools.py Logging.py ImapTimeoutFix.py Modules \
                  $out/share/lillyai/
                makeWrapper ${pythonEnv}/bin/python $out/bin/${name} \
                  --add-flags "-m ${entryModule}" \
                  --set PYTHONPATH $out/share/lillyai \
                  --set PYTHONUNBUFFERED 1 ${extraWrapperArgs}
                runHook postInstall
              '';
            };
        in
        {
          default = mkApp {
            name = "lillyai";
            entryModule = "LillyAI";
            pythonEnv = corePythonEnv pkgs;
          };

          voice = mkApp {
            name = "lillyai-voice";
            entryModule = "LillyVoice";
            pythonEnv = voicePythonEnv pkgs;
            extraWrapperArgs = "--set-default FFMPEG ${pkgs.ffmpeg}/bin/ffmpeg";
          };
        });

      nixosModules = {
        default = { config, lib, pkgs, ... }:
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
                  # The scheduler pings WATCHDOG=1 every tick; a silent hang
                  # (the loop is synchronous) gets SIGABRTed - faulthandler
                  # dumps the hang site to the journal - and restarted.
                  # 630s > the LLM processors' 600s request ceiling, so a
                  # slow-but-alive generation is never killed mid-reply.
                  Type = "notify";
                  NotifyAccess = "main";
                  WatchdogSec = 630;
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

        voice = { config, lib, pkgs, ... }:
          let
            cfg = config.services.lillyai-voice;
          in
          {
            options.services.lillyai-voice = {
              enable = lib.mkEnableOption "LillyVoice — Matrix voice-memo bot";

              package = lib.mkOption {
                type = lib.types.package;
                default = self.packages.${pkgs.stdenv.hostPlatform.system}.voice;
                defaultText = lib.literalExpression "lillyai-voice from its flake";
                description = "The LillyVoice package to run.";
              };

              environmentFile = lib.mkOption {
                # String, not path — this is a secrets file (sops-nix).
                type = lib.types.str;
                example = "/run/secrets/lilly/voice-env";
                description = ''
                  EnvironmentFile with the Matrix credentials and LLM endpoint:
                  MATRIX_HOMESERVER, MATRIX_USER_ID, MATRIX_TOKEN, LLAMA_URL,
                  and optionally MATRIX_DRAFTS_ROOM, MATRIX_LILLY_USER_ID,
                  MATRIX_LILLY_TOKEN, DRAFT_IDLE_SECONDS (see LillyVoice.py).
                '';
              };

              llamaModel = lib.mkOption {
                type = lib.types.str;
                default = "gemma-4-12b";
                description = "Model name passed to the llama.cpp server.";
              };

              localServer = lib.mkOption {
                type = lib.types.str;
                default = "chlo.ee";
                description = "Only rooms hosted on this Matrix server are handled.";
              };
            };

            config = lib.mkIf cfg.enable {
              systemd.services.lillyai-voice = {
                description = "LillyVoice — Matrix voice-memo bot";
                wantedBy = [ "multi-user.target" ];
                after = [ "network-online.target" ];
                wants = [ "network-online.target" ];
                environment = {
                  LLAMA_MODEL = cfg.llamaModel;
                  LOCAL_SERVER = cfg.localServer;
                  STATE_DIR = "/var/lib/lillyai-voice";
                };
                serviceConfig = {
                  ExecStart = "${cfg.package}/bin/lillyai-voice";
                  EnvironmentFile = cfg.environmentFile;
                  Restart = "on-failure";
                  RestartSec = "10s";
                  DynamicUser = true;
                  StateDirectory = "lillyai-voice";
                  NoNewPrivileges = true;
                  ProtectSystem = "strict";
                  ProtectHome = true;
                  PrivateTmp = true;
                };
              };
            };
          };
      };
    };
}
