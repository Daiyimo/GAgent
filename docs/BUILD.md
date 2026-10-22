# Android build

The CI workflow is the authoritative build recipe: Android API 34, NDK
25.1.8937393, Gradle 8.2, Liberica Java 17.0.21, Kotlin 1.9.22, Chaquopy 17.1.0,
Python 3.10.22, OpenSSL 3.5.9, Go 1.27.3 and the pinned gomobile revision in `tsbridge/go.mod`.
Install Android SDK components and expose `ANDROID_HOME` and `ANDROID_NDK_HOME`.

```sh
python3.10 -m pip install -r requirements-test.txt
python3.10 -m playwright install chromium
python3.10 tools/audit_source.py
python3.10 -m pytest -q
bash tools/build_tsbridge.sh
python3.10 tools/build_pure_wheels.py
gradle :app:testDebugUnitTest :app:assembleDebug :app:assembleRelease
```

Go 1.27.3 is required because the mesh library statically includes Go's TLS trust
verification. Updating a build host alone does not update an older APK.

For local release signing set `GAGENT_KEYSTORE_PATH` to a private PKCS12 keystore,
`GAGENT_STORE_PASSWORD` through your secret manager, and use alias `gagent`.
Without these variables release builds are unsigned; debug builds use a local
debug identity. Never commit the keystore or password.

Maintainer CI accepts `GAGENT_RELEASE_KEYSTORE` (base64 PKCS12) and
`GAGENT_STORE_PASSWORD` as Actions secrets. Pull requests from forks do not need
them. Build artifacts include debug/release APKs, SHA256SUMS and SOURCE_COMMIT.
Check the commit and signature before installing. Private Actions artifacts need
repository access. No workflow changes repository visibility or publishes a release.

Android runtime Python wheels come from Chaquopy's Android index. They differ from
desktop test dependencies. Compatibility pins are not a promise of security
currency; security review must include native wheels and packaged CA stores.
CI checks the actual packaged OpenSSL and Go libraries. Chaquopy's `_chaquopy`
OpenSSL names are compatibility stubs forwarding to the current `_python` libraries.
An old build-time version string in an extension is not its dynamically loaded TLS library.
