"""The test-first terminal scripts (ili-test-deploy/-promote/-remove) had several
correctness bugs fixed on 2026-09-09 after a Sonnet review of the first (Haiku)
implementation — see kanban card idea_8acbdcb728. These tests pin the fixed
properties down with `bash -n`/shellcheck plus source-text checks (no docker
engine needed, matching the style of test_ssh_hardening.py), so a later edit
that reintroduces one of the bugs fails here instead of in the sandbox.
"""
import os
import shutil
import subprocess

import pytest

ROOT = os.path.join(os.path.dirname(__file__), "..")
SCRIPTS_DIR = os.path.join(ROOT, "deploy", "terminal")
SCRIPTS = ["ili-test-deploy.sh", "ili-test-promote.sh", "ili-test-remove.sh"]


def read(name):
    with open(os.path.join(SCRIPTS_DIR, name), encoding="utf-8") as fh:
        return fh.read()


@pytest.mark.parametrize("name", SCRIPTS)
def test_bash_syntax_is_valid(name):
    result = subprocess.run(
        ["bash", "-n", os.path.join(SCRIPTS_DIR, name)],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.skipif(shutil.which("shellcheck") is None, reason="shellcheck not installed")
@pytest.mark.parametrize("name", SCRIPTS)
def test_shellcheck_is_clean(name):
    result = subprocess.run(
        ["shellcheck", os.path.join(SCRIPTS_DIR, name)],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stdout


class TestDeployScript:
    def setup_method(self):
        self.src = read("ili-test-deploy.sh")

    def test_find_free_port_checks_all_running_containers_not_the_new_name(self):
        # Bug: `docker port "$TEST_NAME"` before the container exists always
        # returned nothing -> always picked PORT_BASE. Fix probes `docker ps`
        # across ALL containers instead.
        assert 'docker ps --format' in self.src
        assert 'docker port "$TEST_NAME"' not in self.src

    def test_compose_branch_reads_back_the_actual_published_port(self):
        # Bug: the compose branch ignored $TEST_PORT entirely (compose owns the
        # port mapping) and the health check probed the wrong port. Fix reads
        # the real port off the started container.
        assert 'ps -q' in self.src
        assert 'docker port "$CID"' in self.src

    def test_health_check_targets_docker_host_not_localhost(self):
        # Bug: in sandbox mode (DOCKER_HOST=tcp://sandbox:2376) the test
        # container's port is published on the `sandbox` DinD service, not on
        # the terminal container's own "localhost".
        assert 'TARGET_HOST' in self.src
        assert 'curl -sf "http://$TARGET_HOST:$TEST_PORT$API_PATH"' in self.src
        assert 'curl -sf "http://localhost:$TEST_PORT' not in self.src

    def test_initial_copy_keeps_git_metadata_for_pull(self):
        # Bug: excluding .git from the prod->test copy made the documented
        # "git pull" step a no-op (no repo to pull into).
        assert '--exclude=.git' not in self.src
        assert 'git pull' in self.src

    def test_git_pull_failure_is_not_fatal(self):
        # Bug: under set -euo pipefail, a bare `git pull --ff-only` aborts the
        # whole script on the first pull failure (no tracking branch, no TTY
        # for credentials, diverged history) — all routine inside a container,
        # not exceptional. Must degrade to a warning and keep the copied tree.
        assert 'git pull --ff-only' in self.src
        assert "git pull --ff-only 2>&1 | sed 's/^/  /' || warn" in self.src

    def test_compose_ps_pipeline_does_not_abort_on_sigpipe(self):
        # `head -1` can close its pipe early and SIGPIPE the producer (exit
        # 141); under pipefail that would abort the script here too.
        assert "ps -q | head -1 || true" in self.src

    def test_cleanup_helper_is_compose_aware(self):
        # Bug: `docker rm -f $TEST_NAME` cannot find compose-created containers
        # (named <slug>-test-<service>-1).
        assert 'cleanup_test_container' in self.src
        assert 'docker compose -f "$path/docker-compose.yml"' in self.src

    def test_health_check_failure_path_still_runs_cleanup(self):
        # Bug: error() already calls exit 1, so cleanup + exit 2 written after
        # it was dead code — the failure branch must not call error().
        failure_block = self.src.split('$max_attempts ]]; then', 1)[1].split("fi", 1)[0]
        assert "error " not in failure_block
        assert "exit 2" in failure_block


class TestPromoteScript:
    def setup_method(self):
        self.src = read("ili-test-promote.sh")

    def test_container_stop_is_compose_aware(self):
        assert 'docker-compose.yml' in self.src
        assert 'docker compose -f "$TEST_PATH/docker-compose.yml"' in self.src

    def test_writeback_still_excludes_git(self):
        # Unlike the initial deploy copy, writing test->prod must NOT bring the
        # test copy's .git back over the original project's own repo.
        assert '--exclude=.git' in self.src


class TestRemoveScript:
    def setup_method(self):
        self.src = read("ili-test-remove.sh")

    def test_cleanup_is_compose_aware(self):
        assert 'docker-compose.yml' in self.src
        assert 'docker compose -f "$TEST_PATH/docker-compose.yml"' in self.src
