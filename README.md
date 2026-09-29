# FERPEK

FERPEK is a small project I'm building to make infrastructure logs less painful to work with.

I'm a sysadmin, and I kept running into the same problem: servers already tell us a lot about what's happening, but the useful information is usually buried between hundreds or thousands of log lines.

I wanted something that could sit in the middle and help me answer a simpler question:

**What in these logs is actually worth reading?**

That's what FERPEK is trying to do.

## What it does

A lightweight agent reads configured log sources on a host and uses packs to understand events from services such as OpenSSH, Fail2ban, Nginx and Postfix.

FERPEK currently separates what it sees into:

- **Raw** — the original log events.
- **Relevant** — events that FERPEK understands and considers useful to surface.
- **Findings** — patterns or situations that may actually need attention.

Raw logs are optional.

You can let FERPEK analyse logs locally and only send Relevant activity and Findings to the server.

That is intentional — I don't want FERPEK to become another system that simply gives you more logs to read.

## Current state

FERPEK is still early and I'm actively building and testing it.

Right now it has:

- a central server and Web UI
- a lightweight Linux agent
- source discovery
- configurable monitoring and raw log collection
- Relevant activity
- Findings
- declarative YAML packs
- one-time agent enrollment
- retention controls

Current packs include OpenSSH, Fail2ban, Nginx and Postfix.

There's still plenty to improve.

## Why I'm building it

I'm not trying to replace Zabbix, Graylog, Loki or full observability platforms.

FERPEK is much narrower.

The idea is to reduce the amount of information an operator has to read before understanding what happened.

I'm building it primarily because I want to use it myself, and I'm making it public because I'd like to know whether other sysadmins find the same idea useful.

Feedback, criticism and ideas are welcome.

## Website

https://ferpek.com
