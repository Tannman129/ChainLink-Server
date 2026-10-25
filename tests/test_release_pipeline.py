"""Exercise the release guard without credentials, network access, or publishing."""

import base64
import importlib.util
import io
import os
import subprocess
from email.message import Message
from pathlib import Path
from unittest.mock import Mock
from urllib.error import HTTPError, URLError
from urllib.request import HTTPHandler, HTTPSHandler
from urllib.response import addinfourl

import pytest
import yaml


spec = importlib.util.spec_from_file_location(
    "check_release_tag",
    Path(__file__).resolve().parents[1] / ".github/scripts/check_release_tag.py",
)
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)


MANIFEST_URL = "https://ghcr.io/v2/tannman129/chainlink-server/manifests/0.2.1"


def token_response(body=b'{"token": "registry-secret"}', status=200):
    response = io.BytesIO(body)
    response.status = status
    return response


def registry_error(status, body, url=MANIFEST_URL):
    return HTTPError(url, status, "registry error", {}, io.BytesIO(body))


@pytest.fixture
def registry(monkeypatch):
    opener = Mock()
    monkeypatch.setattr(guard.REGISTRY, "open", opener)
    return opener


def test_confirmed_missing_manifest_allows_release(registry):
    registry.side_effect = [
        token_response(),
        registry_error(404, b'{"errors": [{"code": "MANIFEST_UNKNOWN"}]}'),
    ]
    guard.ensure_absent("0.2.1", "publisher", "github-secret")
    auth_request = registry.call_args_list[0].args[0]
    manifest_request = registry.call_args_list[1].args[0]
    expected = base64.b64encode(b"publisher:github-secret").decode()
    assert auth_request.get_header("Authorization") == f"Basic {expected}"
    assert manifest_request.get_header("Authorization") == "Bearer registry-secret"
    assert manifest_request.full_url.endswith("/tannman129/chainlink-server/manifests/0.2.1")
    assert "application/vnd.oci.image.index.v1+json" in manifest_request.get_header("Accept")


def test_existing_manifest_blocks_release(registry):
    registry.side_effect = [token_response(), io.BytesIO(b'{}')]
    with pytest.raises(RuntimeError, match="already exists"):
        guard.ensure_absent("0.2.0", "publisher", "secret")


@pytest.mark.parametrize(
    "failure",
    [
        registry_error(401, b'{"errors": [{"code": "UNAUTHORIZED"}]}'),
        registry_error(403, b'{"errors": [{"code": "DENIED"}]}'),
        registry_error(429, b'{}'),
        registry_error(500, b'{}'),
        registry_error(404, b'{"errors": [{"code": "NAME_UNKNOWN"}]}'),
        registry_error(404, b'{"errors": []}'),
        registry_error(404, b'{}'),
        registry_error(404, b'<html>Not Found</html>'),
        registry_error(404, b'{"errors": [{"code": "MANIFEST_UNKNOWN"}, {"code": "DENIED"}]}'),
        registry_error(404, b'{"errors": [{"code": "MANIFEST_UNKNOWN"}]}', "https://other.example/manifest"),
        URLError("connection failed"),
        TimeoutError("timed out"),
    ],
)
def test_unverifiable_manifest_blocks_release(registry, failure):
    registry.side_effect = [token_response(), failure]
    with pytest.raises(Exception):
        guard.ensure_absent("0.2.1", "publisher", "secret")


@pytest.mark.parametrize("body", [b'{}', b'{"token": ""}', b'{"token": null}', b'bad json'])
def test_invalid_auth_response_blocks_release(registry, body):
    registry.return_value = token_response(body)
    with pytest.raises((KeyError, ValueError)):
        guard.ensure_absent("0.2.1", "publisher", "secret")
    assert registry.call_count == 1


@pytest.mark.parametrize("version", ["v0.2.1", "01.2.3", "1.2", "1.2.3-rc1", "1.2.3+build", "../dev"])
def test_invalid_version_never_contacts_registry(registry, version):
    with pytest.raises(ValueError, match="Invalid release version"):
        guard.ensure_absent(version, "publisher", "secret")
    registry.assert_not_called()


def test_auth_failure_exits_without_exposing_credentials(registry, monkeypatch, capsys):
    monkeypatch.setenv("RELEASE_VERSION", "0.2.1")
    monkeypatch.setenv("GITHUB_ACTOR", "publisher")
    monkeypatch.setenv("GHCR_TOKEN", "github-secret")
    registry.side_effect = RuntimeError("github-secret registry-secret")
    assert guard.main() == 1
    output = capsys.readouterr()
    assert "refusing to publish" in output.out
    assert "secret" not in output.out + output.err


@pytest.mark.parametrize("status", [201, 204, 206])
def test_unexpected_auth_status_blocks_release(registry, status):
    registry.return_value = token_response(status=status)
    with pytest.raises(ValueError, match="Unexpected authentication response"):
        guard.ensure_absent("0.2.1", "publisher", "github-secret")
    assert registry.call_count == 1


@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
@pytest.mark.parametrize("destination", [
    "https://other.example/token",
    "http://ghcr.io/token",
    "http://other.example/token",
    "https://ghcr.io/other",
])
@pytest.mark.parametrize("redirect_token_request", [True, False])
def test_redirects_never_send_credentials_or_accept_redirected_404(
    monkeypatch, capsys, status, destination, redirect_token_request,
):
    # Stub only HTTP transport, retaining the real opener, redirect handler,
    # error processing, and main entry point. No sockets or credentials used.
    requests = []

    def transport(handler, request):
        requests.append(request)
        headers = Message()
        if request.full_url.startswith("https://ghcr.io/token?") and not redirect_token_request:
            code, body = 200, b'{"token": "registry-secret"}'
        elif request.full_url == destination:
            code, body = 404, b'{"errors": [{"code": "MANIFEST_UNKNOWN"}]}'
        else:
            code, body = status, b'github-secret registry-secret'
            headers["Location"] = destination
        response = addinfourl(io.BytesIO(body), headers, request.full_url, code)
        response.msg = "synthetic response"
        return response

    monkeypatch.setattr(HTTPSHandler, "https_open", transport)
    monkeypatch.setattr(HTTPHandler, "http_open", transport)
    monkeypatch.setenv("RELEASE_VERSION", "0.2.1")
    monkeypatch.setenv("GITHUB_ACTOR", "publisher")
    monkeypatch.setenv("GHCR_TOKEN", "github-secret")
    assert guard.main() == 1
    assert len(requests) == (1 if redirect_token_request else 2)
    assert all(request.full_url != destination for request in requests)
    assert requests[0].get_header("Authorization").startswith("Basic ")
    if not redirect_token_request:
        assert requests[1].get_header("Authorization") == "Bearer registry-secret"
    output = capsys.readouterr()
    assert "secret" not in output.out + output.err
    assert base64.b64encode(b"publisher:github-secret").decode() not in output.out + output.err


# BaseLoader keeps GitHub's YAML `on` key and boolean scalars as strings.
WORKFLOW = yaml.load(
    (Path(__file__).resolve().parents[1] / ".github/workflows/docker.yml").read_text(),
    Loader=yaml.BaseLoader,
)
PUBLISH = WORKFLOW["jobs"]["publish"]


def run_workflow_step(step_id, tmp_path, **environment):
    step = next(step for step in PUBLISH["steps"] if step.get("id") == step_id)
    output = tmp_path / "output"
    output.write_text("")
    result = subprocess.run(
        ["bash", "--noprofile", "--norc", "-e", "-o", "pipefail", "-c", step["run"]],
        env={**os.environ, "GITHUB_OUTPUT": str(output), **environment},
        capture_output=True, text=True,
    )
    return result, output.read_text()


@pytest.mark.parametrize("event,can_publish", [
    ("pull_request", False), ("workflow_dispatch", False), ("push", True),
])
def test_only_push_events_can_enter_publish_job(event, can_publish):
    # Keep the event gate deliberately simple; assert the actual expression,
    # rather than maintaining a second GitHub Actions expression interpreter.
    assert PUBLISH["if"] == "github.event_name == 'push'"
    assert (event == "push") is can_publish
    assert WORKFLOW["on"]["push"] == {"branches": ["main"], "tags": ["v*.*.*"]}
    assert WORKFLOW["on"]["pull_request"] == {"branches": ["main"]}
    assert "workflow_dispatch" in WORKFLOW["on"]


@pytest.mark.parametrize("ref,tag", [
    ("refs/heads/main", "dev"),
    ("refs/tags/v0.2.1", "0.2.1"),
    ("refs/tags/v12.34.56", "12.34.56"),
    ("refs/tags/v0.0.0", "0.0.0"),
    ("refs/tags/v01.2.3", None),
    ("refs/tags/v1.02.3", None),
    ("refs/tags/v1.2.03", None),
    ("refs/tags/v1.2.3-rc1", None),
    ("refs/tags/v1.2.3+build", None),
    ("refs/tags/v1.2", None),
    ("refs/tags/v1.2.3.4", None),
    ("refs/heads/feature", None),
])
def test_workflow_selects_only_dev_or_exact_release_version(tmp_path, ref, tag):
    result, output = run_workflow_step(
        "image", tmp_path, GITHUB_REF=ref, GITHUB_REF_NAME=ref.split("/", 2)[2],
    )
    if tag is None:
        assert result.returncode != 0
        assert output == ""
    else:
        assert result.returncode == 0, result.stderr
        assert output == f"tag={tag}\n"
    push = PUBLISH["steps"][-1]
    assert push["run"] == 'docker push "$IMAGE"'
    assert push["env"]["IMAGE"] == "ghcr.io/tannman129/chainlink-server:${{ steps.image.outputs.tag }}"


def test_permissions_prerequisites_and_publication_order():
    assert WORKFLOW["permissions"] == {"contents": "read"}
    assert PUBLISH["needs"] == ["test", "build"]
    for name, job in WORKFLOW["jobs"].items():
        assert "continue-on-error" not in job
        expected = {"contents": "read", "packages": "write"} if name == "publish" else {"contents": "read"}
        assert job.get("permissions", WORKFLOW["permissions"]) == expected
        for step in job["steps"]:
            assert "continue-on-error" not in step
            if step.get("uses", "").startswith("docker/build-push-action@"):
                assert step["with"]["push"] == "false"
                assert step["with"]["target"] == "production"
    assert "if" not in WORKFLOW["jobs"]["test"]
    assert "if" not in WORKFLOW["jobs"]["build"]
    assert any(step.get("run") == "python -m pytest -v" for step in WORKFLOW["jobs"]["test"]["steps"])
    assert any(step.get("uses", "").startswith("docker/build-push-action@") for step in WORKFLOW["jobs"]["build"]["steps"])
    assert PUBLISH["concurrency"] == {
        "group": "chainlink-image-${{ github.ref }}", "cancel-in-progress": "false",
    }
    steps = PUBLISH["steps"]
    build = next(i for i, step in enumerate(steps) if step.get("uses", "").startswith("docker/build-push-action@"))
    freshness = next(i for i, step in enumerate(steps) if step.get("id") == "freshness")
    guard_step = next(i for i, step in enumerate(steps) if step.get("run") == "python3 .github/scripts/check_release_tag.py")
    login = next(i for i, step in enumerate(steps) if step.get("uses", "").startswith("docker/login-action@"))
    assert build < freshness < guard_step < login < len(steps) - 1
    assert steps[build]["with"]["load"] == "true"
    assert steps[build]["with"]["tags"] == steps[-1]["env"]["IMAGE"]
    assert steps[guard_step]["if"] == "github.ref_type == 'tag'"
    for step in (steps[login], steps[-1]):
        assert step["if"] == "steps.freshness.outputs.publish == 'true'"


@pytest.mark.parametrize("main_sha,exit_code,ref,expected", [
    ("a" * 40, 0, "refs/heads/main", "publish=true\n"),
    ("b" * 40, 0, "refs/heads/main", "publish=false\n"),
    ("", 0, "refs/heads/main", ""),
    ("null", 0, "refs/heads/main", ""),
    ("bad-response", 0, "refs/heads/main", ""),
    ("a" * 40, 1, "refs/heads/main", ""),
    ("", 1, "refs/tags/v0.2.1", "publish=true\n"),
])
def test_freshness_gate_blocks_stale_builds_and_api_failures(tmp_path, main_sha, exit_code, ref, expected):
    gh = tmp_path / "gh"
    gh.write_text(
        '#!/bin/bash\n'
        '[[ "$*" == "api repos/owner/repo/git/ref/heads/main --jq .object.sha" ]] || exit 9\n'
        'printf "%s\\n" "$TEST_MAIN_SHA"\n'
        'exit "$TEST_GH_EXIT"\n'
    )
    gh.chmod(0o755)
    result, output = run_workflow_step(
        "freshness", tmp_path, PATH=f"{tmp_path}:{os.environ['PATH']}",
        GITHUB_REF=ref, GITHUB_SHA="a" * 40, GITHUB_REPOSITORY="owner/repo",
        TEST_MAIN_SHA=main_sha, TEST_GH_EXIT=str(exit_code), GH_TOKEN="synthetic-test-token",
    )
    assert output == expected
    assert (result.returncode == 0) is bool(expected)
    assert "synthetic-test-token" not in result.stdout + result.stderr


@pytest.mark.parametrize("arrival_order", [["a", "b", "a"], ["b", "a"]])
def test_older_run_or_rerun_skips_after_newer_main_publishes(tmp_path, arrival_order):
    # Model jobs entering the workflow's serialized publish section. Both
    # delayed completion and rerunning an old commit must skip after b wins.
    gh = tmp_path / "gh"
    gh.write_text('#!/bin/bash\nprintf "%s\\n" "$TEST_MAIN_SHA"\n')
    gh.chmod(0o755)
    tip = "a"
    publications = []
    for commit in arrival_order:
        if commit == "b":
            tip = "b"
        result, output = run_workflow_step(
            "freshness", tmp_path, PATH=f"{tmp_path}:{os.environ['PATH']}",
            GITHUB_REF="refs/heads/main", GITHUB_SHA=commit * 40,
            GITHUB_REPOSITORY="owner/repo", TEST_MAIN_SHA=tip * 40,
        )
        assert result.returncode == 0, result.stderr
        if output == "publish=true\n":
            publications.append(commit)
        else:
            assert output == "publish=false\n"
    assert publications[-1] == "b"
    assert publications[publications.index("b"):] == ["b"]
