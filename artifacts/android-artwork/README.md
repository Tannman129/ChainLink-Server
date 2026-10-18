# Android artwork update

This bundle contains 28 source/resource changes prepared against the inspected DiscGolf repository. The Codex session can read that repository but cannot write outside the server workspace and `/tmp`, so these changes have been built and tested in `/tmp/chainlink-artwork-android` instead of being installed into the original source tree.

The update includes:

- Full, uncropped official artwork as a local 720 × 881 WebP for the Android home screen.
- A Compose `Image` replacing the decorative canvas, with all buttons, creator credit, unfinished rounds, and scoring callbacks preserved.
- Five density-specific 108dp adaptive foreground/monochrome layers (108, 162, 216, 324, 432 pixels). The full artwork rectangle fits within the central 66dp circular safe zone.
- Matching black adaptive backgrounds and separate luminance-derived monochrome artwork for themed icons.
- Standard 48dp legacy icons at 48, 72, 96, 144, and 192 pixels, including round variants.
- Instrumentation regressions for home actions, artwork dimensions, and adaptive drawable resources.

The original source PNG is unchanged. The bundle includes no application-ID, database, authentication, synchronization, Gradle, manifest, or signing changes. A separate validation-only application ID was used in the temporary build to avoid replacing the existing emulator application or its rounds.

Inspect the bundle or run a no-write check:

```bash
python artifacts/android-artwork/apply.py ~/AndroidStudioProjects/DiscGolf
```

Apply it from the ChainLink Server directory:

```bash
python artifacts/android-artwork/apply.py ~/AndroidStudioProjects/DiscGolf --apply
```

Every existing destination is checked against its inspected SHA-256 before any write. Files already updated are skipped; unexpected edits stop the operation. Replaced files are backed up under `.chainlink-artwork-backup-<timestamp>` in the Android project. Keep that backup local and do not commit it.

Then run normal Android validation in your desktop terminal:

```bash
cd ~/AndroidStudioProjects/DiscGolf
./gradlew testDebugUnitTest assembleDebug assembleDebugAndroidTest
# Run instrumentation on a disposable emulator, not a device containing important rounds:
./gradlew connectedDebugAndroidTest
```

Preview assets and test reports generated during this session reside under `/tmp`; the portable update itself is `android-artwork-update.zip` with its checksummed `manifest.json`.
