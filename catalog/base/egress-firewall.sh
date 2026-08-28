#!/bin/bash
# Egress firewall: whitelist permitted outbound destinations, block everything else.
# Closes the primary exfiltration vector identified in agentic AI security research.
#
# Usage: egress-firewall [extra-domain ...]
# Extra domains (e.g. Z.AI endpoint host) are appended to the whitelist.
# Re-applied at each container session start (iptables rules are in-memory).

set -uo pipefail

# NOT `set -e`: the per-domain resolution loop below is allowed to fail for individual hosts (a
# CDN that will not resolve must not abort the whole firewall). Every call that MUST succeed is
# checked explicitly instead — see `require` and the final verification.

# A rule that could not be installed is not a weaker firewall, it is NO firewall. For most of this
# project's life every iptables call here failed with "Permission denied" (the container had no
# CAP_NET_ADMIN) and this script still printed "Egress active" and exited 0, so the launcher's
# fail-closed guard never fired and every container ran with unrestricted egress (#429).
require() {
    if ! "$@"; then
        echo "[firewall] FATAL: $* failed — refusing to report a firewall that is not installed" >&2
        exit 1
    fi
}

WHITELIST=(
    # Anthropic / Claude API
    api.anthropic.com
    statsig.anthropic.com

    # GitHub (git, gh CLI, release downloads, raw files)
    github.com
    api.github.com
    codeload.github.com
    objects.githubusercontent.com
    raw.githubusercontent.com
    uploads.github.com
    alive.github.com

    # npm registry
    registry.npmjs.org

    # Python packages
    pypi.org
    files.pythonhosted.org

    # mise tool manager
    mise.jdx.dev
)

# Append any extra domains passed as arguments (e.g. Z.AI API host)
for arg in "$@"; do
    [ -n "$arg" ] && WHITELIST+=("$arg")
done

# Flush existing OUTPUT rules and set default DROP policy. These four are the firewall: if any
# one of them does not take, everything after it is decoration on an open netns.
require iptables -F OUTPUT
require iptables -P OUTPUT DROP

# Always allow loopback
require iptables -A OUTPUT -o lo -j ACCEPT

# Allow established/related connections (responses to our requests)
require iptables -A OUTPUT -m state --state ESTABLISHED,RELATED -j ACCEPT

# Allow DNS so tools can resolve names
require iptables -A OUTPUT -p udp --dport 53 -j ACCEPT
require iptables -A OUTPUT -p tcp --dport 53 -j ACCEPT

# The varlock broker's door. The broker binds 127.0.0.1 on the HOST and is reachable from the pod
# only because podman is started with `pasta --map-host-loopback,169.254.1.1`; nothing else on any
# network can reach it. `require`d, not best-effort like the two gateway rules below, because this
# address is a constant — an iptables failure here is a broken firewall, not a missing lookup
# (#429). Do not widen to a link-local CIDR — see #436.
require iptables -A OUTPUT -d 169.254.1.1 -j ACCEPT

# Allow access to the host gateway (for connecting to local services on the host). Rootless podman
# has TWO relevant gateways: the default-route gateway (HOST_GW) and the podman host-gateway
# `host.containers.internal` — the address shared service sidecars publish their ports to (plan
# 04-01). iptables is netns-wide, so allowing this unblocks the whole pod, including the hatago
# MCP proxy that reaches host-published services.
HOST_GW=$(ip route 2>/dev/null | awk '/default/ {print $3; exit}')
[ -n "$HOST_GW" ] && iptables -A OUTPUT -d "$HOST_GW" -j ACCEPT
PODMAN_GW=$(getent ahosts host.containers.internal 2>/dev/null | awk '{print $1}' | head -1)
[ -n "$PODMAN_GW" ] && iptables -A OUTPUT -d "$PODMAN_GW" -j ACCEPT

# Detect ip6tables availability
HAS_IP6TABLES=false
command -v ip6tables >/dev/null 2>&1 && ip6tables -L OUTPUT >/dev/null 2>&1 && HAS_IP6TABLES=true

if [ "$HAS_IP6TABLES" = "true" ]; then
    ip6tables -F OUTPUT
    ip6tables -P OUTPUT DROP
    ip6tables -A OUTPUT -o lo -j ACCEPT
    ip6tables -A OUTPUT -m state --state ESTABLISHED,RELATED -j ACCEPT
    ip6tables -A OUTPUT -p udp --dport 53 -j ACCEPT
    ip6tables -A OUTPUT -p tcp --dport 53 -j ACCEPT
fi

# Resolve each whitelisted domain and allow its current IPs (IPv4 via iptables, IPv6 via ip6tables)
allowed_ips=0
failed=()
for domain in "${WHITELIST[@]}"; do
    ips=$(getent ahosts "$domain" 2>/dev/null | awk '{print $1}' | sort -u)
    if [ -z "$ips" ]; then
        failed+=("$domain")
        continue
    fi
    for ip in $ips; do
        if [[ "$ip" == *:* ]]; then
            # IPv6 address
            if [ "$HAS_IP6TABLES" = "true" ]; then
                ip6tables -A OUTPUT -d "$ip" -j ACCEPT
                allowed_ips=$((allowed_ips + 1))
            fi
        else
            # IPv4 address
            iptables -A OUTPUT -d "$ip" -j ACCEPT
            allowed_ips=$((allowed_ips + 1))
        fi
    done
done

# Verify the end state rather than trusting the calls above, then say so. Cheap, and it is the
# only line here that can honestly justify the message that follows.
if ! iptables -S OUTPUT 2>/dev/null | grep -qx -- '-P OUTPUT DROP'; then
    echo "[firewall] FATAL: OUTPUT policy is not DROP after applying rules — no firewall is in effect" >&2
    exit 1
fi

# Mark this session so apply_firewall skips re-application while container is running.
# Best-effort: the marker is an optimisation, and a read-only /run must not fail a working firewall.
touch /run/egress-firewall-active 2>/dev/null || true

echo "[firewall] Egress active: $allowed_ips IPs across ${#WHITELIST[@]} domains"
[ ${#failed[@]} -gt 0 ] && echo "[firewall] Warning: could not resolve: ${failed[*]}"
exit 0
