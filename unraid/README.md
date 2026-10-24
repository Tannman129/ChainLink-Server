# ChainLink Server on Unraid

Reusable Unraid Docker template version 2 files for the already published
`ghcr.io/tannman129/chainlink-server:0.2.0` image and `postgres:17`.
These files describe container settings; they do not change application code,
database schema, or running containers. Existing Compose settings and older
source/package version references are intentionally unchanged.

| File | Purpose |
| --- | --- |
| `chainlink-server.xml` | API and WebUI; host TCP 8010 to container 8000 |
| `chainlink-postgresql.xml` | PostgreSQL 17; persistent storage, no published ports |
| `icons/chainlink-server.png` | Square derivative of the existing ChainLink artwork |
| `icons/postgresql.png` | Official PostgreSQL elephant PNG |

## What each artifact does

- The [GitHub repository](https://github.com/Tannman129/ChainLink-Server) stores
  source code, documentation, templates, and icons.
- A Docker image contains the runnable software. Unraid pulls the API image from
  GitHub Container Registry (GHCR) and PostgreSQL from Docker Hub.
- An Unraid XML template fills in the Docker creation form with image, network,
  ports, mounts, and environment settings. It contains no application binaries.

Publishing templates to GitHub does **not** automatically list the app in Unraid
Community Applications. Inclusion requires a separate submission through the
[Community Applications process](https://docs.unraid.net/community-applications/).

The git remote is `https://github.com/Tannman129/ChainLink-Server.git`, on branch
`main`. XML icon and template URLs use that exact owner/repository and stable
paths under `https://raw.githubusercontent.com/Tannman129/ChainLink-Server/main/unraid/`.
**New files are local until someone explicitly commits and pushes them.** The
remote URLs may return 404 until publication; creating these files does not
publish them. A private repository also requires authenticated retrieval and
will not provide anonymously accessible icon URLs to Unraid.

## Before installing

For an existing working deployment, read **Adopt existing containers safely**
first. Do not run the fresh-install steps against its data or secrets.
All commands below are instructions for a future operator action on Unraid;
adding this directory does not execute them.

Both containers use the user-defined bridge network `chainlink_net`. In the
Unraid terminal, check for it:

```bash
docker network inspect chainlink_net
```

Only if it does not exist, create it:

```bash
docker network create --driver bridge chainlink_net
```

Create the network **before opening the templates** so Unraid can offer
`Custom: chainlink_net` in Network Type. Verify an existing network has the
intended bridge configuration. Docker DNS resolves `chainlink-postgresql` on
this network; the API connects to its container port `5432`. No host database
port is needed. Other containers attached to this network can also reach it.

Check that `/mnt/cache` is your actual pool mount and that the intended appdata
storage remains on that pool. Adapt the host paths if your pool has another
name. A fixed pool path must not be moved away by an appdata/mover policy.

## Password file for a fresh database

The PostgreSQL template binds the **file**
`/mnt/cache/appdata/chainlink/secrets/postgres_password` to
`/run/secrets/postgres_password` with access mode **Read Only** (`ro`). The file
contains only the raw password, optionally followed by a newline: no variable
name, quotes, or connection URL. Create it before starting PostgreSQL; a missing
bind source can become a directory instead of the required file.

For a new installation only, run as root in the Unraid terminal:

```bash
(
  set -eu
  umask 077
  mkdir -p /mnt/cache/appdata/chainlink/postgres
  mkdir -p /mnt/cache/appdata/chainlink/secrets
  chmod 700 /mnt/cache/appdata/chainlink/secrets
  # Noclobber refuses to overwrite an existing password file.
  set -o noclobber
  openssl rand -hex 32 > /mnt/cache/appdata/chainlink/secrets/postgres_password
  chmod 644 /mnt/cache/appdata/chainlink/secrets/postgres_password
)
```

The root-owned `0700` parent protects host access; the file's `0644` mode lets
the image's postgres user read the individual file mounted inside the container,
including after the entrypoint drops root privileges. Do not export the secrets
directory through shares, relax its parent permissions, or mount it into other
containers. A root-only `0600` file can prevent the postgres user from reading
this bind mount. Keep PostgreSQL's image-default entrypoint/user behavior; the
API's `10001:10001` user setting does not apply to PostgreSQL.

`POSTGRES_PASSWORD_FILE` is the **container** path. Do not also configure
`POSTGRES_PASSWORD`. This is a read-only bind mount using the image's `_FILE`
support, not a Docker Swarm secret. The initialization variables only initialize
an empty data directory. Changing the file does not rotate an existing database
role's password, and changing `POSTGRES_DB`/`POSTGRES_USER` does not rename an
existing database/role. See the [official image documentation](https://github.com/docker-library/docs/blob/master/postgres/README.md).

For an existing database, retain its credentials and populate the file with the
current password through a trusted local editor if a file is not already in use.
Never overwrite an existing password file as part of template adoption.

## Configure the API

`DATABASE_URL` is deliberately blank, required, editable, and masked in the form.
Enter the real value only in your local Unraid configuration. This is a
**placeholder format**, not a working connection string:

```text
postgresql+psycopg://DB_USER:URL_ENCODED_PASSWORD@chainlink-postgresql:5432/DB_NAME
```

Replace `DB_USER` and `DB_NAME` with the actual database role and database
(`chainlink` for both in a fresh default installation). Use the same password
as the password file, percent-encoding special characters in the URL's username
and password components. Do not encode the whole URL. The hex password generated
above needs no additional encoding. Do not use `localhost`, the Unraid host IP,
or API port `8010` as the database endpoint. The API does not read
`POSTGRES_PASSWORD_FILE`; it needs its complete `DATABASE_URL` environment value.

Masking only hides the value in the form: Unraid's saved user template and Docker
container metadata still contain it. Protect flash/config backups and diagnostic
exports; never copy populated user templates, secrets, or real connection strings
back into Git. Avoid commands that print the URL or put it into shell history.

`SESSION_COOKIE_SECURE` defaults to `true` for HTTPS. For trusted local HTTP
testing at `http://UNRAID_IP:8010/`, explicitly set it to `false`; secure cookies
cannot support sign-in over ordinary HTTP. Use HTTPS and `true` for remote
access. The WebUI shortcut remains `http://[IP]:[PORT:8000]/`; with HTTPS, use
your proxy's HTTPS address or adjust your local shortcut. The 8010 mapping
publishes the API on the host, unlike Compose's loopback-only default.

## Install through Unraid

1. Prepare the network, storage, and password file above. Confirm port 8010 is
   free. For an existing installation, use the adoption procedure below.
2. Copy the two local XML files to Unraid's
   `/boot/config/plugins/dockerMan/templates-user/` as
   `my-chainlink-server.xml` and `my-chainlink-postgresql.xml`. Use a local
   transfer such as SCP/SFTP; preserve any existing files with those names
   instead of overwriting them. These become local editable user templates.
3. After the files have actually been published, you can instead download the
   [server template](https://raw.githubusercontent.com/Tannman129/ChainLink-Server/main/unraid/chainlink-server.xml)
   and [PostgreSQL template](https://raw.githubusercontent.com/Tannman129/ChainLink-Server/main/unraid/chainlink-postgresql.xml)
   and copy them to those locations. Inspect downloads as XML; do not save an
   error page as a template. Icons will load from the raw URLs only after
   publication. Missing icons do not prevent local XML installation.
4. On Unraid's **Docker** tab, choose **Add Container**, then the
   `chainlink-postgresql` user template. Confirm `Custom: chainlink_net`, both
   mounts, the password file's **Read Only** access, all four variables, and
   the absence of port mappings. In Advanced View verify Extra Parameters
   contains `--restart=unless-stopped`. Create/start PostgreSQL when ready.
5. Wait until PostgreSQL accepts connections, using its logs and this read-only
   check (substitute your existing database/role if different):

   ```bash
   docker exec chainlink-postgresql pg_isready -h 127.0.0.1 -p 5432 -U chainlink -d chainlink
   ```

   TCP avoids mistaking the image's initialization-only Unix-socket server for
   the final server. `pg_isready` checks availability, not password validity or
   the application's schema.
6. A fresh PostgreSQL database still needs the release's existing Alembic
   migrations through your established migration procedure before API use.
   Consult [the project's migration documentation](../README.md#migrations),
   use the same `0.2.0` image and intended database, and keep credentials local.
   The Compose migration service targets its own Compose database by default;
   do not run it unchanged expecting it to migrate this Unraid database.
   These XML templates do not run migrations, and the API does not create the
   schema automatically. Do not rerun migrations merely to adopt a working
   installation. Schema-changing operations are a separate, planned action.
7. Choose **Add Container** and the `chainlink-server` user template. Fill in
   `DATABASE_URL`, choose the cookie setting, and verify `8010` → `8000/tcp`.
   Advanced View must show `--user=10001:10001 --workdir=/app
   --restart=unless-stopped`. Keep the image's default command. Start only when
   the database and schema are ready.
8. Check `/health`, then `/v1/courses` and the WebUI. `/health` is process
   liveness only; a successful catalog read also exercises the database/schema.
   Test sign-in with an existing account and the intended HTTP/HTTPS setting.

PostgreSQL must be available before the API starts. In Unraid, order PostgreSQL
before the API and set a suitable AutoStart delay in Advanced View. A delay and
`unless-stopped` do **not** implement Compose's `depends_on: service_healthy`,
and Docker restarts do not guarantee dependency readiness. Verify readiness
after host/daemon restarts and recover the API after PostgreSQL becomes ready
if needed. See [Unraid's startup and container settings](https://docs.unraid.net/unraid-os/using-unraid-to/run-docker-containers/managing-and-customizing-containers/).

## Adopt existing containers safely

The server already runs successfully on Unraid. There is no need to replace it
just to maintain reusable templates. Copying XML files alone does not adopt,
stop, or change containers. Plan any later transition separately:

1. Record current names, image tags **and image IDs/digests**, networks/aliases,
   ports, user, working directory, restart policy, mounts, actual `PGDATA`, and
   environment settings in a private local record. Keep credentials out of Git
   and shared logs. Back up existing Unraid user XML/configuration separately.
2. Take a PostgreSQL-aware backup (for example, `pg_dump` plus needed roles)
   and verify a restore into an isolated PostgreSQL 17 database. Preserve the
   original data storage and password file. Do not copy a live PostgreSQL data
   directory as a substitute for a consistent backup.
3. Compare these defaults with the running settings. Retain the real storage
   source, `PGDATA`, database name, role, password, image, and network aliases.
   A named Docker volume is not automatically moved into the template's bind
   path. If needed, represent the existing volume explicitly in a local Unraid
   configuration; never blindly accept an empty default directory. A different
   `PGDATA` can also initialize a new, apparently empty database. Preserve the
   current image when it differs from this template's fresh-install default.
4. Stage local XML copies without overwriting existing user templates. Review
   the form and cancel without applying until you have approved the complete
   configuration and a maintenance window. Applying an edited container form
   may recreate the container; it is not a metadata-only operation. Do not
   create a second container with the same name or API host port.
5. If a later replacement is necessary, stop API writes first and coordinate
   the database shutdown/startup with the approved transition. **Never run two
   PostgreSQL containers against the same data directory.** Reuse the existing
   storage unchanged. Moving to a new path is a separate backup/restore task;
   do not combine it with template adoption. Preserve the original configuration
   and storage for rollback; do not delete volumes, images, containers, or data
   as part of this preparation.
6. Before resuming traffic, verify PostgreSQL readiness, actual database and
   schema, and representative existing courses/accounts/rounds. Then check API
   liveness, catalog reads, and sign-in. If validation fails, stop the new API
   and any replacement database before restoring the original configuration
   against its original storage. Never point simultaneous database processes
   at that storage. Keep writes paused until validation succeeds.

No migrations, password rotations, image updates, or schema changes are needed
solely to maintain or adopt these templates.

## Future image updates

These templates retain `ghcr.io/tannman129/chainlink-server:0.2.0` and
`postgres:17`. To update later, review release notes, back up and test restore,
verify that the intended image tag exists, then deliberately change the API
template's `<Repository>` and your local Unraid Repository field to that exact
released tag. Review any required migrations as a separate operation before
starting the new API. Test database reads and authentication afterward; retain
the previous image/configuration for a compatible rollback.

Editing/publishing XML does not rebuild an image or automatically update an
installed container's repository tag. Unraid's later update/apply action can
pull an image and recreate the container. `postgres:17` is a moving major-version
tag, so updates can change its patch release or base image; record digests when
planning a reproducible update or rollback. Do not change PostgreSQL's major
version or data layout without a separate tested PostgreSQL upgrade plan.

## Icon provenance

- `chainlink-server.png`: 256 × 256 PNG, full uncropped artwork resized with
  aspect ratio preserved and centered on black. Source:
  `/home/tannman/AndroidStudioProjects/DiscGolf/assets/Midnight Red Disc Golf Basket.png`.
  The source file is untouched. Source SHA-256:
  `9aff23b27741b16f42cdef55946d56ca54e4b1e1061154f81401dcd035ac1649`.
- `postgresql.png`: unchanged 120 × 120 three-color elephant downloaded from
  the [official PostgreSQL logo collection](https://wiki.postgresql.org/wiki/Logo),
  [direct PNG source](https://wiki.postgresql.org/images/3/30/PostgreSQL_logo.3colors.120x120.png).
  SHA-256: `d3efdff93443f5feb1a8371d4ad5b851501589d3ae20cf6f57623d8f92ec2fa0`.
  PostgreSQL and the Slonik logo are trademarks or registered trademarks of the
  PostgreSQL Community Association of Canada; see the linked collection's
  trademark policy. This separate icon identifies PostgreSQL, without implying
  that PostgreSQL endorses ChainLink.

## Local validation

Field names and configuration attributes follow Unraid's
[Docker template parser](https://github.com/limetech/webgui/blob/master/emhttp/plugins/dynamix.docker.manager/include/Helpers.php).
Runtime user, working directory, and restart policy are Docker options in
`ExtraParams`; port, path, and environment values are version 2 `Config` entries.

Parse both templates without contacting Docker or a database:

```bash
python3 - <<'PY'
from pathlib import Path
import xml.etree.ElementTree as ET
for path in sorted(Path('unraid').glob('*.xml')):
    root = ET.parse(path).getroot()
    assert root.tag == 'Container' and root.get('version') == '2'
    print(path, 'valid version 2 XML')
PY
```

Before publishing, also review the port mapping, private database networking,
read-only password-file mount, required/editable variables, exact image tags,
and raw icon URLs. Keep `DATABASE_URL` empty in the reusable XML. Do not publish
populated Unraid user templates. XML parsing and static field checks do not
replace a later operator-controlled Unraid installation test.
