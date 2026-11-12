pipeline {
    agent { label 'docker-python' }

    options {
        timestamps()
        disableConcurrentBuilds()
        timeout(time: 60, unit: 'MINUTES')
    }

    parameters {
        booleanParam(name: 'DEPLOY_TO_PRODUCTION', defaultValue: false,
                     description: 'Request a gated deployment from the protected Main branch.')
    }

    environment {
        DJANGO_DEBUG = 'False'
        DJANGO_ALLOWED_HOSTS = 'localhost,127.0.0.1'
        COMPLAINT_INTAKE_ENABLED = 'False'
        ANONYMOUS_INTAKE_ENABLED = 'False'
        ANONYMOUS_PRIVACY_READY = 'False'
        ANONYMOUS_TRANSPORT_VERIFIED = 'False'
        DJANGO_HTTPS_MODE = ''
        DJANGO_SECURE_SSL_REDIRECT = 'False'
        DJANGO_SESSION_COOKIE_SECURE = 'False'
        DJANGO_CSRF_COOKIE_SECURE = 'False'
        DJANGO_SECURE_HSTS_SECONDS = '0'
    }

    stages {
        stage('Install verification tools') {
            steps {
                sh 'python --version'
                sh 'python -m pip install --disable-pip-version-check -r requirements-dev.txt bandit==1.8.6 pip-audit==2.9.0'
            }
        }

        stage('Static and security checks') {
            steps {
                sh 'python -m compileall -q accounts complaints routing workflow scms'
                sh 'bandit -q -r accounts complaints routing workflow scms'
                sh 'pip-audit -r requirements.txt -r requirements-dev.txt'
            }
        }

        stage('Django checks, tests and coverage') {
            steps {
                // Generate a throwaway key in the agent shell; never expose a Jenkins secret to PR code.
                sh '''DJANGO_SECRET_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')" \\
                    sh scripts/ci_checks.sh build/evidence/jenkins/${BUILD_NUMBER}'''
            }
            post {
                always {
                    archiveArtifacts artifacts: 'build/evidence/jenkins/**', allowEmptyArchive: true
                }
            }
        }

        stage('Build container image') {
            steps {
                sh '''
                    set -eu
                    docker build --pull --tag "scms-app:${GIT_COMMIT}" .
                    test_key=$(python -c 'import secrets; print(secrets.token_urlsafe(48))')
                    docker run --rm --entrypoint python \\
                        -e DJANGO_SECRET_KEY="$test_key" \\
                        -e DJANGO_DEBUG=False -e DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1 \\
                        -e COMPLAINT_INTAKE_ENABLED=False -e ANONYMOUS_INTAKE_ENABLED=False \\
                        -e ANONYMOUS_PRIVACY_READY=False -e ANONYMOUS_TRANSPORT_VERIFIED=False \\
                        "scms-app:${GIT_COMMIT}" manage.py check
                '''
            }
        }

        stage('Deploy to production') {
            when {
                allOf {
                    branch 'Main'
                    not { changeRequest() }
                    expression { params.DEPLOY_TO_PRODUCTION }
                }
            }
            input {
                message 'Deploy the verified Main image to the configured production host?'
                ok 'Deploy'
                submitter 'scms-deploy-approvers'
            }
            steps {
                script {
                    if (!env.SCMS_IMAGE_REPOSITORY?.trim() || !env.SCMS_DEPLOY_HOST?.trim()
                            || !env.SCMS_DEPLOY_DIR?.trim()) {
                        error('Configure SCMS_IMAGE_REPOSITORY, SCMS_DEPLOY_HOST and SCMS_DEPLOY_DIR in Jenkins.')
                    }
                    if (!(env.SCMS_IMAGE_REPOSITORY ==~ /[A-Za-z0-9][A-Za-z0-9._:\/-]*/) ||
                            !(env.SCMS_DEPLOY_HOST ==~ /[A-Za-z0-9][A-Za-z0-9_.@-]*/) ||
                            !(env.SCMS_DEPLOY_DIR ==~ /\/[A-Za-z0-9._\/-]+/) ||
                            env.SCMS_DEPLOY_DIR.contains('/../') || env.SCMS_DEPLOY_DIR.endsWith('/..') ||
                            !(env.GIT_COMMIT ==~ /[0-9a-f]{40}/)) {
                        error('Jenkins deployment target or commit does not match the required safe format.')
                    }
                    if (!env.SCMS_REGISTRY_HOST?.trim() || !(env.SCMS_REGISTRY_HOST ==~ /[A-Za-z0-9][A-Za-z0-9.:-]*/)) {
                        error('Configure a valid SCMS_REGISTRY_HOST in Jenkins.')
                    }
                    env.DEPLOY_IMAGE = "${env.SCMS_IMAGE_REPOSITORY}:${env.GIT_COMMIT}"
                }
                withCredentials([usernamePassword(credentialsId: 'scms-registry-push',
                                 usernameVariable: 'REGISTRY_USER', passwordVariable: 'REGISTRY_TOKEN'),
                                 file(credentialsId: 'scms-deploy-known-hosts',
                                 variable: 'KNOWN_HOSTS_FILE')]) {
                    sshagent(credentials: ['scms-deploy-ssh']) {
                        sh '''#!/bin/sh
                            set -eu
                            set +x
                            trap 'docker logout "${SCMS_REGISTRY_HOST}" >/dev/null 2>&1 || true' EXIT
                            printf '%s' "$REGISTRY_TOKEN" | docker login "${SCMS_REGISTRY_HOST:?Configure SCMS_REGISTRY_HOST}" \\
                                --username "$REGISTRY_USER" --password-stdin
                            docker tag "scms-app:${GIT_COMMIT}" "$DEPLOY_IMAGE"
                            if ! push_output=$(docker push "$DEPLOY_IMAGE" 2>&1); then
                                printf '%s\n' "$push_output" >&2
                                exit 1
                            fi
                            printf '%s\n' "$push_output"
                            image_digest=$(printf '%s\n' "$push_output" | awk '/digest: sha256:/ { for (i=1; i<=NF; i++) if ($i ~ /^sha256:/) { print $i; exit } }')
                            case "$image_digest" in
                                sha256:????????????????????????????????????????????????????????????????) ;;
                                *) echo 'Registry did not return a valid image digest.' >&2; exit 1 ;;
                            esac
                            deploy_ref="${SCMS_IMAGE_REPOSITORY}@${image_digest}"
                            printf 'Deploying immutable image %s\n' "$deploy_ref"
                            ssh -o BatchMode=yes -o StrictHostKeyChecking=yes \\
                                -o "UserKnownHostsFile=$KNOWN_HOSTS_FILE" "$SCMS_DEPLOY_HOST" \\
                                "cd '$SCMS_DEPLOY_DIR' && SCMS_IMAGE='$deploy_ref' docker compose --env-file .env.docker pull app && SCMS_IMAGE='$deploy_ref' docker compose --env-file .env.docker up -d --no-build --wait app"
                        '''
                    }
                }
            }
        }
    }

    post {
        always {
            sh 'docker image rm -f scms-app:${GIT_COMMIT} >/dev/null 2>&1 || true'
        }
    }
}
