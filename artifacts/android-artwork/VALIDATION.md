# Artwork validation results

Android changes were validated in a copy under `/tmp/chainlink-artwork-android`. The original Android repository was not changed. Instrumentation used the separate application ID `com.fortsprague.discgolf.artworkpreview` on `emulator-5554`, preserving the existing installed application's data. That validation-only application ID is not part of the update bundle.

- Android `testDebugUnitTest`: 42 passed.
- Android `assembleDebug` and `assembleDebugAndroidTest`: successful.
- Full Android instrumentation: 98 tests, 96 passed, 2 failed.
  - `ExampleInstrumentedTest.useAppContext` expects the original package name and fails because validation deliberately uses the separate preview package.
  - `CourseManagementScreenTest.emptyNamesCanBeAddedWithoutLosingPendingBulkSelection` failed on a “Save name” visibility assertion. This course-editor visibility failure remains unresolved; the course editor was not modified.
- Focused instrumentation rerun: all 6 branding tests passed. The combined runner filter selected only the branding class, so it did not establish a separate course-editor rerun result. Branding includes the new artwork/home-action and adaptive-icon checks.
- Launcher validation: all five density dimensions, foreground/monochrome safe-zone bounds, legacy sizes, and adaptive XML references verified. Square, round, and themed icon previews reviewed.
- Android home screenshot reviewed with the full artwork and existing primary actions visible.
- Server default suite: 39 passed; opt-in browser module skipped.
- Server suite with Chromium enabled: all 54 passed. One upstream Starlette/httpx deprecation warning remains.
- Chromium screenshots reviewed at widths 390, 834, and 1440. Artwork loads locally, preserves aspect ratio, remains at most 96px wide, and stays below the information cards.
- Python wheel built successfully and contains both optimized WebP image variants.
- Python lint, JavaScript syntax validation, and Git whitespace checks passed.
- Bundle application was exercised on a disposable source copy, including a subsequent idempotent check. A no-write check against the original Android repository validates all 28 expected changes.

No database schema, authentication, synchronization, Unraid, or GitHub Actions changes were made. No commits or pushes were performed.
