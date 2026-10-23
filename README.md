# GAgent

[简体中文](README.zh-CN.md) · [Architecture](docs/ARCHITECTURE.md) · [Build](docs/BUILD.md)

GAgent runs a Python agent on an Android phone. The agent can plan tasks, call tools,
read the screen, interact with apps, browse, manage files and retain local memory.
You choose the model provider and supply your own credentials.

This distribution combines the latest Android beta (2.33.0 / 133) with the newer
PC Link fixes from the former main branch. Version 2.33.1 / 134 starts a clean
repository history. The owner controls when this repository becomes public.

## What is included

- Kotlin Android shell, embedded CPython through Chaquopy, Python agent runtime and bilingual WebUI.
- Accessibility actions, screenshots, guarded app navigation, optional wireless ADB and browser tools.
- Multiple model providers, explicit provider selection, conversation isolation, streaming output and local memory.
- Local PaddleOCR models. The old AGPL-derived YOLO weights are not distributed; OCR and accessibility remain available.
- PC Link, mesh pairing, streaming ASR and APK build clients with explicit optional-service configuration.

Subscriptions, payments, points, mandatory hosted accounts, hosted telemetry,
prompt collection, embedded service credentials and source encryption are removed.
The related commercial servers and production operations are not part of this repository.

See the [feature scope](docs/FEATURE_SCOPE.md) for retained capabilities, removed
flows, excluded server implementations and items awaiting acceptance.

## Get started

1. Build an APK or download one from this repository's Releases when available.
2. Install on **Android 7.0 / API 24 or newer, arm64-v8a**. Screenshot capabilities vary by Android version and permissions.
3. Open **Settings → Providers & Models**, enter your provider URL, API key and model.
4. Grant only the permissions needed for the tools you want to use.
5. Configure optional services under **Settings → Optional modules**. These clients require compatible services; the app does not deploy them for you.

The release application ID is `io.github.shenhaostu.gagent`; debug builds add
`.debug`. This is a separate installation from the former application. It does
not silently migrate keys, accounts or conversations. Debug and release also use
separate data directories. Export only data you intend to transfer.

Keys are stored in app-private storage and sent to the service you configure for
authentication. Model requests can include task text, screenshots and tool results.
There is no automatic telemetry or prompt upload. Agent-generated code and device
actions run with the permissions you grant; this is not an isolation sandbox.

## Build and contribute

See [BUILD.md](docs/BUILD.md) for the pinned toolchain, local commands and CI.
The `main` branch builds both Android variants. No model, commercial-service or
source-encryption secret is needed to compile. Release signing is optional for
contributors; the maintainer's signing key is kept outside Git.

```bash
python -m pip install -r requirements-test.txt
python -m playwright install chromium
python tools/audit_source.py
python -m pytest -q
bash tools/build_tsbridge.sh
python tools/build_pure_wheels.py
gradle :app:testDebugUnitTest :app:assembleDebug :app:assembleRelease
```

Read [CONTRIBUTING.md](CONTRIBUTING.md), [the review record](docs/REVIEW.md) and
[SECURITY.md](SECURITY.md) before proposing changes. Functional behavior and
side-effect boundaries are documented in [ARCHITECTURE.md](docs/ARCHITECTURE.md).

## License and credits

The project code is licensed under [Apache-2.0](LICENSE). Derived from the
GenericAgent / GAndroid work by Liang Jiaqing and contributors; original notices
are retained. Third-party libraries, model files and fonts retain their own
licenses. See [NOTICE](NOTICE) and [THIRD_PARTY.md](THIRD_PARTY.md).

iOS and ESP32 development remains in its existing workspace and is not included
in this Android distribution.

[Official modules and credential boundaries](docs/OFFICIAL_MODULES.md)

[Dependency review before public release](docs/DEPENDENCY_SECURITY.md)
