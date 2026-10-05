# FERPEK Lens

FERPEK Lens is an open-source log analysis platform for system administrators.

A lightweight agent reads logs on your hosts, packs understand what those logs mean, and the server surfaces Relevant activity and Findings in one place.

The goal is simple:

**Spend less time digging through logs and more time understanding what actually happened.**

## What it does

A lightweight agent reads configured log sources on a host and uses packs to understand events from different services.

FERPEK Lens currently separates what it sees into:

- **Raw**: the original log events.
- **Relevant**: events that FERPEK Lens understands and considers useful to surface.
- **Findings**: patterns or situations that may actually need attention.

Raw logs are optional.

You can let FERPEK Lens analyse logs locally and only send Relevant activity and Findings to the server.

That is intentional. I don't want FERPEK Lens to become another system that simply gives you more logs to read.

## Current state

FERPEK Lens is still early and I'm actively building and testing it.

Right now it has:

- A central server and Web UI
- A lightweight Linux agent
- Source discovery
- Configurable monitoring and raw log collection
- Relevant activity
- Findings
- Declarative YAML packs
- One-time agent enrollment
- Retention controls

Current packs include OpenSSH, Fail2ban, Nginx and Postfix. There's still plenty to improve.

## Why I'm building it

I'm a sysadmin myself, a fairly new one. I've been doing this professionally for about two years.

Maybe it was laziness that made me start this project.

Over those two years, I kept running into the same thing: reading logs.

I know, reading logs is one of the fundamentals of our job. But wouldn't it be easier to have one place where you could quickly see the logs that actually matter?

Of course, every log matters depending on what you're troubleshooting. But imagine some emails aren't being sent and they're getting stuck in the mail queue.

Normally, you connect to the server, open the logs, figure out roughly when it happened, search through them, correlate what you find, and eventually understand what went wrong.

Wouldn't it be easier to open a platform that already tells you what happened, where it happened and when it happened, so you can start troubleshooting immediately?

That's basically FERPEK Lens.

A log reader designed to make infrastructure logs easier to understand and easier to act on.

I originally made this mostly for myself.

Then I got a little carried away with it.

I made a name, a logo, branding, an interface, agents, packs... and somehow I've now been working on this for almost two months in my free time after work.

So I decided to make it open source.

If other sysadmins find it useful, great. And if the community wants to contribute new packs, rules, improvements or completely new ideas, even better.

I've already learned a lot while building FERPEK Lens, and that's also a big part of why I'm continuing to work on it.

I'd like FERPEK Lens to become sustainable in the future, while keeping the core project open source.

I'm also completely open to constructive criticism.

You can tell me something is badly designed, that I'm solving the problem the wrong way, etc...

But I'll listen to the feedback, good or bad.

## Website

https://ferpek.com/products/lens/

## License

FERPEK Lens is licensed under the GNU Affero General Public License v3.0 only (AGPL-3.0-only).

See [LICENSE](LICENSE) for details.
