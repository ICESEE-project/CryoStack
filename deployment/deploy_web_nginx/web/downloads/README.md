# /downloads/

Static file downloads served by nginx at `https://cryostack.eas.gatech.edu/downloads/`.

## CryoStack Connector

Connector distributables live under `connectors/` and are **published at deploy
time**, not committed:

```
downloads/connectors/
  CryoStack-Connector-linux-x86_64.tar.gz
  CryoStack-Connector-macos-arm64.dmg      # built on a Mac
  CryoStack-Connector-macos-x86_64.dmg     # built on a Mac
  CryoStack-Connector-windows-x86_64.exe   # built on Windows
  SHA256SUMS
  manifest.json
```

Build + publish:

```
bash build_connector.sh          # builds THIS host's platform only
bash build_deploy_connector.sh   # build + copy artifacts into the web root
```

`build_connector.sh` is a single-host PyInstaller build and cannot cross-compile.
To ship every platform, run it on a Linux host, a Mac, and a Windows host, then
collect the artifacts into `dist/packages/` and run
`CRYOSTACK_SKIP_BUILD=1 bash build_deploy_connector.sh`.
