"""Fail closed unless authenticated GHCR confirms the release manifest is absent."""

import base64
import json
import os
import re
import sys
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, Request, build_opener


REPOSITORY = "tannman129/chainlink-server"
ACCEPT = ", ".join(
    [
        "application/vnd.oci.image.index.v1+json",
        "application/vnd.oci.image.manifest.v1+json",
        "application/vnd.docker.distribution.manifest.list.v2+json",
        "application/vnd.docker.distribution.manifest.v2+json",
    ]
)


class RejectRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Raise before urllib can send either Authorization header elsewhere.
        raise HTTPError(req.full_url, code, "Registry redirect refused", {}, None)


REGISTRY = build_opener(RejectRedirects())


def ensure_absent(version, actor, credential):
    if not re.fullmatch(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)", version):
        raise ValueError("Invalid release version")
    if not actor or not credential:
        raise ValueError("Missing registry credentials")

    basic = base64.b64encode(f"{actor}:{credential}".encode()).decode()
    request = Request(
        f"https://ghcr.io/token?service=ghcr.io&scope=repository:{REPOSITORY}:pull",
        headers={"Authorization": f"Basic {basic}"},
    )
    with REGISTRY.open(request, timeout=30) as response:
        if response.status != 200:
            raise ValueError("Unexpected authentication response")
        token = json.load(response)["token"]
    if not isinstance(token, str) or not token:
        raise ValueError("Missing registry bearer token")

    request = Request(
        f"https://ghcr.io/v2/{REPOSITORY}/manifests/{version}",
        headers={"Authorization": f"Bearer {token}", "Accept": ACCEPT},
    )
    try:
        with REGISTRY.open(request, timeout=30):
            pass
    except HTTPError as error:
        # A generic 404, denied access, or an unavailable registry is not proof
        # of absence. Require the registry's specific missing-manifest response.
        if error.code == 404 and error.url == request.full_url:
            errors = json.load(error).get("errors", [])
            if errors and all(item.get("code") == "MANIFEST_UNKNOWN" for item in errors):
                return
        raise
    raise RuntimeError("Release image already exists")


def main():
    try:
        ensure_absent(
            os.environ["RELEASE_VERSION"],
            os.environ["GITHUB_ACTOR"],
            os.environ["GHCR_TOKEN"],
        )
    except Exception:
        # Never log response bodies, headers, tokens, or exception details.
        print("::error::Release tag exists or its absence could not be verified; refusing to publish.")
        return 1
    print("Release tag is absent; publishing may proceed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
