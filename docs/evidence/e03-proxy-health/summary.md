# E03 proxy HTTPS health-check verification

Local verification was performed against HEAD `30fa47b00ea6a512225f185a1f50a92a5ab51630`
with uncommitted Dockerfile, E03 documentation and test changes. This is not
clean-commit evidence. The corrected Dockerfile SHA-256 was
`f67d63d3425214e4cdf5cb75c942f2ecbb95128720972a1f477b55151d8925f4`;
the isolated Docker build context contained the same Dockerfile hash.

- An image built from the original commit was run with proxy HTTPS mode and
  HTTPS redirects enabled. Its exact configured Docker health command exited
  1 after the redirect led to a refused local HTTPS connection. A request
  marked as forwarded HTTPS returned 200. Docker reported that container
  unhealthy.
- A rebuilt image with the corrected Dockerfile was run in separate disposable
  containers using SQLite and no published ports or persistent volumes. In
  proxy mode with redirects, secure cookies and HSTS enabled, Docker reported
  healthy and the exact configured health command exited 0. An unmarked HTTP
  request still returned 301. In normal mode, Docker reported healthy and the
  exact configured health command exited 0.
- `docker compose config --quiet` passed using synthetic configuration. The
  Compose application service inherits the image health check; the database
  service retains its `pg_isready` check. No deployment stack was started.
- Focused Docker/Jenkins tests: 12 passed. The full test runner completed with
  1,172 passed, 96.14% overall coverage and all module coverage gates passing.
  Django system and migration consistency checks passed. `run.json` records
  the test runner's source state; `coverage-summary.txt` is its gate output.

The proxy-mode probe uses the existing Django forwarding-header configuration.
Q02 must still verify backend isolation and that the deployed ingress overwrites
untrusted client forwarding headers before production activation.
