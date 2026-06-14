# Vision for container-code

- The current SKU is a containerized version of the host configuration.
- New variants
  - Host authentication but empty configuration. All the commands, skills, agents and hooks are proxied to a custom folder externally that can be under git control.  
  - I need different containers for different configurations. For example, I'd like to experiment with different memory systems, and I don't want to pollute my host system.
  - I'm also considering building those memory systems as containers and exposing them as sidecars.
  - Examples:
    - OpenBrain
    - HindSight
- New Agents:
  - omp (Oh my pi)
  - opengsd/gds-pi
-
