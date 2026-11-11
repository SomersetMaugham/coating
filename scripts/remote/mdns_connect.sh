#!/bin/sh
# ssh ProxyCommand for the Windows test machine: resolve NAME.local over multicast DNS only, accept only a private
# IPv4 address, and connect to it.  Plain name lookup is not safe here: when the mDNS answer is late, macOS also asks
# the unicast DNS server, and an ISP resolver that answers unknown names with its own (public) address wins
# (seen 2026-11-12: desktop-....local -> 218.38.137.28).  The host key check would refuse that host, but the
# connection must never leave the local network in the first place.
#
#   ProxyCommand ~/.ssh/mdns_connect.sh DESKTOP-NAME.local %p       (copy this file to ~/.ssh/, chmod +x)
name="$1"
port="${2:-22}"
out="$(mktemp)"
dns-sd -G v4 "$name" > "$out" 2>/dev/null &
pid=$!
ip=""
i=0
while [ $i -lt 30 ]; do  # up to 3 s
  # dns-sd columns: Timestamp A/R Flags IF Hostname Address TTL.  IF 0 = from the unicast cache: ignore it.
  ip="$(awk '$2 == "Add" && $4 != "0" { print $6 }' "$out" |
        grep -E '^(10\.|192\.168\.|172\.(1[6-9]|2[0-9]|3[01])\.)[0-9.]+$' | head -n 1)"
  [ -n "$ip" ] && break
  sleep 0.1
  i=$((i + 1))
done
{ kill "$pid" && wait "$pid"; } 2>/dev/null
rm -f "$out"
if [ -z "$ip" ]; then
  echo "mdns_connect: no private IPv4 address for $name over mDNS (is the machine on and on this network?)" >&2
  exit 1
fi
exec nc "$ip" "$port"
