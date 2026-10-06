# Add your first host

FERPEK Lens monitors infrastructure through the FERPEK Agent.

## Generate an enrollment token

Open **Hosts** in the FERPEK Lens web interface and select **Add host**.

FERPEK Lens generates a temporary, single-use enrollment token and displays the installation command.

## Install the agent

Run the generated command on the Linux host you want to monitor.

The current automatic installer is intended for Debian-based Linux systems and requires root or sudo privileges.

During installation, FERPEK will:

- install the required dependencies;
- download the FERPEK Agent;
- configure the systemd service;
- enroll the host;
- create local agent credentials;
- remove the temporary enrollment token.

## Host connection

When enrollment succeeds, the host appears automatically in the FERPEK Lens interface.

The agent then reports available log sources and pack discovery information.

You can enable the appropriate packs for that host from the web interface.
