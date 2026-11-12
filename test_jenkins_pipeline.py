from pathlib import Path


ROOT = Path(__file__).resolve().parent


def test_jenkins_pipeline_orders_gates_before_deployment():
    text = (ROOT / "Jenkinsfile").read_text()
    stages = [
        "stage('Install verification tools')",
        "stage('Static and security checks')",
        "stage('Django checks, tests and coverage')",
        "stage('Build container image')",
        "stage('Deploy to production')",
    ]
    assert [text.index(stage) for stage in stages] == sorted(text.index(stage) for stage in stages)
    deploy = text[text.index(stages[-1]):]
    assert "beforeInput true" in deploy
    assert "branch 'Main'" in deploy
    assert "params.DEPLOY_TO_PRODUCTION" in deploy
    assert "submitter 'scms-deploy-approvers'" in deploy
    assert "scms-deploy-known-hosts" in deploy
    assert "scms-deploy-ssh" in deploy
    assert "scms-registry-push" in deploy
    assert "not { changeRequest() }" in deploy
    assert "--no-build --wait app" in deploy
    assert "docker push \"$DEPLOY_IMAGE\"" in deploy
    assert "if ! push_output=$(docker push \"$DEPLOY_IMAGE\"" in deploy
    assert "trap 'docker logout" in deploy
    assert "deploy_ref=\"${SCMS_IMAGE_REPOSITORY}@${image_digest}\"" in deploy
    assert "docker build --pull --tag \"scms-app:${GIT_COMMIT}\" ." in text
    assert "docker run --rm --entrypoint python" in text


def test_jenkins_pipeline_uses_gated_test_defaults_and_no_inline_secrets():
    text = (ROOT / "Jenkinsfile").read_text()
    assert "credentials('scms-ci-django-secret-key')" not in text
    assert "DJANGO_SECRET_KEY=\"$(python -c 'import secrets" in text
    assert "ANONYMOUS_INTAKE_ENABLED = 'False'" in text
    assert "ANONYMOUS_PRIVACY_READY = 'False'" in text
    assert "ANONYMOUS_TRANSPORT_VERIFIED = 'False'" in text
    assert "DJANGO_HTTPS_MODE = ''" in text
    assert "DJANGO_SECURE_SSL_REDIRECT = 'False'" in text
    assert "DJANGO_SESSION_COOKIE_SECURE = 'False'" in text
    assert "DJANGO_CSRF_COOKIE_SECURE = 'False'" in text
    assert "DJANGO_SECURE_HSTS_SECONDS = '0'" in text
    assert "python -m pip_audit -r requirements.txt -r requirements-dev.txt" in text
    assert "bandit==1.9.4 pip-audit==2.9.0" in text
    assert "-r requirements.txt -r requirements-dev.txt bandit==1.9.4 pip-audit==2.9.0" in text
    assert "python -m compileall -q accounts complaints routing workflow scms manage.py scripts" in text
    assert 'python -m bandit -q -r accounts complaints routing workflow scms manage.py scripts -x "**/test_*.py,**/tests.py,scripts/q04_load.py"' in text
    assert "DEPLOY_IMAGE =" in text
    assert "password-stdin" in text
    assert not any(line.strip().startswith(("DJANGO_SECRET_KEY=", "REGISTRY_TOKEN="))
                   for line in text.splitlines())


def test_registry_and_ssh_credentials_are_confined_to_gated_deploy_stage():
    text = (ROOT / "Jenkinsfile").read_text()
    deploy_start = text.index("stage('Deploy to production')")
    credential_use = text.index("withCredentials(")
    assert credential_use > deploy_start
    assert "not { changeRequest() }" in text[deploy_start:credential_use]
    assert "branch 'Main'" in text[deploy_start:credential_use]
    assert "submitter 'scms-deploy-approvers'" in text[deploy_start:]


def test_bandit_suppressions_are_limited_to_public_signing_salts():
    for name, expected in (
        ("complaints/anonymous_views.py", 'TOKEN_SALT = "complaints.anonymous-intake"  # nosec B105'),
        ("complaints/views.py", 'TOKEN_SALT = "complaints.authenticated-intake"  # nosec B105'),
    ):
        lines = (ROOT / name).read_text().splitlines()
        matches = [index for index, line in enumerate(lines) if line == expected]
        assert len(matches) == 1
        assert "public domain-separation values" in lines[matches[0] - 1]


def test_bandit_subprocess_suppressions_are_limited_to_fixed_ci_runner_calls():
    lines = (ROOT / "scripts/run_tests.py").read_text().splitlines()
    import_matches = [index for index, line in enumerate(lines) if line == "import subprocess  # nosec B404"]
    run_matches = [index for index, line in enumerate(lines) if "subprocess.run(" in line and "# nosec B603" in line]
    assert len(import_matches) == len(run_matches) == 1
    assert "fixed argv" in lines[import_matches[0] - 1]
    assert "repository-controlled" in lines[run_matches[0] - 1]
