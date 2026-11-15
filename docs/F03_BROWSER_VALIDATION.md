# F03 normal-browser description validation

The description textarea deliberately has no HTML `minlength`. Nonempty short
descriptions reach the same server validator in authenticated and anonymous
intake and receive its deduplicated inline error. Required and maximum-length
constraints remain. The smaller intrinsic textarea fits a 320-pixel viewport
without relying on inline CSS that the anonymous Content Security Policy blocks.

The server trims outer whitespace. Unicode letters, numbers, punctuation and
symbols and interior Unicode space separators count toward the minimum of 20.
Combining marks, line breaks and invisible control/format padding do not add to
that minimum. Bidirectional formatting controls are rejected separately. Normal
right-to-left text remains permitted. This is the existing conservative Unicode
count, not a change to the validator or a grapheme-counting implementation.

## Run the actual browser regression

Use a disposable virtual environment with the repository's Python requirements:

```sh
python -m pip install -r requirements.txt -r requirements-dev.txt playwright==1.58.0
python -m playwright install chromium
export DJANGO_SECRET_KEY=synthetic-local-browser-tests-only
export DJANGO_DB_ENGINE=sqlite
export SCMS_BROWSER_EVIDENCE_DIR=build/evidence/intake-browser
python -m pytest integration_checks/intake_browser.py --no-cov -q --junitxml=build/evidence/intake-browser/junit.xml
```

OpenSSL must be available. On Linux, Playwright may require its documented
`install --with-deps chromium` installation. A system Chromium can be selected
explicitly with `SCMS_CHROMIUM_EXECUTABLE=/absolute/path/to/chromium`.
Missing browser dependencies are failures, never silently skipped. This explicit
suite is separate from the ordinary server test discovery; the dedicated
`Intake browser validation` workflow executes it on PR changes.

Eight Chromium cases cover both real intake routes with short text, invisible
padding, combining-mark padding and outer whitespace at 320 by 740 pixels. They
use normal button clicks, real CSRF and secure cookies through a disposable
loopback TLS proxy. Checks require an actual HTTP 400, one inline description
error, its label/ARIA associations and visible in-viewport bounds, retained safe
values/request token, no premature persistence, and successful corrected Unicode
submission using an interior space and the same token. Page-only screenshots of
the short-text error contain synthetic data only; private one-time references
are never captured.

The test-only privacy/transport/intake settings exist solely in the disposable
pytest process. Default application release gates remain closed. The synthetic
reference labels are short; these checks do not establish acceptance of every
campus label, screen-reader behavior, every browser, unaided testing or final Q06.

PR83 also edits the authenticated view. Its upload-error placement must be
preserved alongside PR89's `add_unique_error` calls when those branches integrate.
This follow-up does not replace the view or merge PR83 into PR89.
