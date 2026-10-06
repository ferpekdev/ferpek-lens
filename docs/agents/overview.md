# Agents

The FERPEK Agent runs directly on monitored hosts.

Its responsibilities include:

- host enrollment;
- log source discovery;
- service discovery;
- pack synchronization;
- log collection;
- pack rule processing;
- reporting relevant activity and findings to the FERPEK Lens server.

## Credentials

After enrollment, the agent stores its own credentials locally.

The temporary enrollment token is removed after successful enrollment.

## Service

On supported Linux systems, the agent runs as a systemd service named `ferpek-agent.service`.

The agent currently requires elevated privileges because infrastructure logs and journald sources are not always accessible to unprivileged users.
