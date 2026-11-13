#!/usr/bin/env bash
# Docker sets the iptables FORWARD policy to DROP, which would also drop VPN traffic.
# DOCKER-USER is the chain Docker reserves for us; the real filtering stays in our nftables table.
set -euo pipefail
for ipt in iptables ip6tables; do
  command -v "$ipt" >/dev/null || continue
  "$ipt" -n -L DOCKER-USER >/dev/null 2>&1 || continue
  "$ipt" -C DOCKER-USER -i wg0 -j ACCEPT 2>/dev/null || "$ipt" -I DOCKER-USER -i wg0 -j ACCEPT
  "$ipt" -C DOCKER-USER -o wg0 -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT 2>/dev/null \
    || "$ipt" -I DOCKER-USER -o wg0 -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT
done
