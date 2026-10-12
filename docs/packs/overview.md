# Packs

Packs define how FERPEK Lens understands infrastructure services.

A pack can describe:

- supported platforms;
- service discovery;
- log sources;
- detection rules;
- relevant activity;
- findings;
- configuration requirements.

Packs are designed to keep service-specific knowledge outside the core agent wherever possible.

Pack compatibility is versioned independently across the FERPEK Lens Server, Agent and Pack Engine. Packs that require newer rule-language capabilities can declare a minimum `pack_engine` version and are not distributed to incompatible agents.

See **Pack development** for the current pack rule and compatibility model.

## Official packs

Official FERPEK Lens packs are maintained separately in the `ferpek-lens-packs` repository.

The initial official catalog includes:

- OpenSSH
- Nginx
- Fail2ban
- Postfix

The pack catalog is intentionally small while the pack architecture is still being developed and hardened.

## Pack registry

FERPEK Lens can retrieve information about official packs from the FERPEK pack registry.

In the future, the public pack catalog will also be available through `packs.ferpek.com`.
