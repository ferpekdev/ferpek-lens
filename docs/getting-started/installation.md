# Installation

The recommended way to install FERPEK Lens is with the official server installer.

FERPEK Lens is still under active development and should not yet be considered production-ready.

## Supported platform

The current server installer supports:

- Debian-based Linux systems
- amd64 / x86_64 architecture

Support for additional operating systems and architectures will be documented when those installation paths are implemented and tested.

## Requirements

The target host must have:

- internet access;
- root access or sudo privileges;
- an available TCP port for the web interface;
- an available TCP port for the FERPEK Server API and Agent communication.

The default ports are:

- `5173` for the web interface;
- `8000` for the FERPEK Server API and Agent communication.

Docker and Docker Compose are installed automatically when they are not already available.

Git, Node.js and Python are not required to install FERPEK Lens.

## Install FERPEK Lens

Install `curl` if it is not already available:

    apt-get update
    apt-get install -y curl

Then run the FERPEK Lens installer:

    curl -fsSL https://raw.githubusercontent.com/ferpekdev/ferpek-lens/main/deploy/install-server.sh | sudo sh

The installer will:

1. verify the operating system and architecture;
2. install the required system packages;
3. install Docker if necessary;
4. install Docker Compose if necessary;
5. check for an existing FERPEK Lens deployment;
6. verify that the configured ports are available;
7. create the server installation directory;
8. download the deployment configuration;
9. pull the official FERPEK Lens container images;
10. start the FERPEK Lens server and web interface;
11. wait for the server to become healthy.

## Installation directory

The FERPEK Lens server is installed in:

    /opt/ferpek-lens-server

The directory contains the deployment configuration:

    /opt/ferpek-lens-server/compose.yml
    /opt/ferpek-lens-server/.env

The `.env` file contains the installed FERPEK Lens version and deployment settings.

## Container images

FERPEK Lens uses official container images published through GitHub Container Registry:

    ghcr.io/ferpekdev/ferpek-lens-server
    ghcr.io/ferpekdev/ferpek-lens-web

The installer currently installs the stable FERPEK Lens release defined by the installer.

## Open the web interface

After a successful installation, the installer displays the address of the FERPEK Lens web interface.

By default:

    http://SERVER_IP:5173

Replace `SERVER_IP` with the address of the machine running FERPEK Lens.

## Initial setup

On the first visit, FERPEK Lens asks you to complete the initial setup.

The current setup screen creates the first administrator account.

Additional first-run configuration options will be introduced as the setup workflow evolves.

## Verify the installation

Check the running containers:

    cd /opt/ferpek-lens-server
    docker compose ps

Both the server and web containers should become healthy.

Check the server health endpoint:

    curl http://127.0.0.1:8000/health

A successful response looks similar to:

    {"status":"ok","version":"0.4.1"}

The exact version may differ from the example above.

## Persistent data

FERPEK Lens stores server data in a persistent Docker volume.

With the default deployment, the volume is:

    ferpek-lens_server_data

Do not remove this volume unless you intentionally want to delete FERPEK Lens data.

In particular, avoid:

    docker compose down -v

when you only want to stop or restart FERPEK Lens.

## Stop FERPEK Lens

To stop the services without deleting persistent data:

    cd /opt/ferpek-lens-server
    docker compose down

## Start FERPEK Lens

Start the existing deployment with:

    cd /opt/ferpek-lens-server
    docker compose up -d

## Custom ports

The installer supports custom ports.

Example:

    curl -fsSL https://raw.githubusercontent.com/ferpekdev/ferpek-lens/main/deploy/install-server.sh | sudo sh -s -- --web-port 8080 --server-port 8081

The web and server ports must be different and must not already be in use.

## Install a specific version

A specific FERPEK Lens release can be selected with:

    curl -fsSL https://raw.githubusercontent.com/ferpekdev/ferpek-lens/main/deploy/install-server.sh | sudo sh -s -- --version 0.4.1

When a specific version is selected, FERPEK Lens uses the deployment configuration associated with that release.

## Existing installations

The installer refuses to overwrite an existing FERPEK Lens installation.

If FERPEK Lens is already installed, the existing deployment should be managed or upgraded instead of running the installer again.

Upgrade and migration workflows are still being developed.

## Development installation

The installer described above is intended for normal self-hosted deployments.

Developers who want to modify FERPEK Lens source code can instead clone the repository and use the development Docker Compose configuration.

Development installation instructions will be documented separately.

## Next step

After FERPEK Lens is running and the initial administrator account has been created, continue with:

**Add your first host**
