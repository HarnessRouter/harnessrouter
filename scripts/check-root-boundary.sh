#!/bin/sh
# Inside a running container, as root with --privileged (root needs it to read another uid's /proc/<pid>/environ). Root must never
# read or run what the product user can change (GHSA-mm72-wr37-26pv). Read off the running container, not the Dockerfile: a later
# line, or a volume, can undo what an earlier one says. The release gate runs this; the checks that write leave nothing behind.
bad=0
fail() { echo "ROOT BOUNDARY: $1"; bad=1; }

n=$(find /app /data/agent-tools -xdev ! -user root ! -path '/app/ui/.next/cache*' 2>/dev/null | wc -l)
[ "$n" = 0 ] || fail "$n paths under /app or the tools are not root's, for example $(find /app /data/agent-tools -xdev ! -user root ! -path '/app/ui/.next/cache*' 2>/dev/null | head -1)"
n=$(find /app /data/agent-tools -xdev -perm /022 ! -type l ! -path '/app/ui/.next/cache*' 2>/dev/null | wc -l)
[ "$n" = 0 ] || fail "$n paths under /app or the tools can be written by a group or by anyone"
[ "$(stat -c %u:%a /data)" = "0:1771" ] || fail "/data is $(stat -c %U:%a /data), not root's with the sticky bit"
# A base's install uid (19001 and up, docker/entrypoint.sh install_as_uid) leaves nothing behind: no process and no HOME.
n=$(cat /proc/[0-9]*/status 2>/dev/null | awk '/^Uid:/ && $2 >= 19001 && $2 < 19100' | wc -l)
[ "$n" = 0 ] || fail "$n processes of an install uid are still running"
n=$(find /tmp -maxdepth 1 -name 'hr-install.*' 2>/dev/null | wc -l)
[ "$n" = 0 ] || fail "$n install homes are left in /tmp"
[ "$(stat -c %u:%a /data/workspaces)" = "0:751" ] || fail "/data/workspaces is $(stat -c %U:%a /data/workspaces)"

home_of() { tr '\0' '\n' < "/proc/$1/environ" 2>/dev/null | sed -n 's/^HOME=//p'; }
pid_of() { ps -eo pid,args | awk -v p="$1" 'index($0, p) && !/awk/ {print $1; exit}'; }
[ "$(home_of 1)" != "/home/agent" ] || fail "PID 1 has the product user's HOME"
[ "$(home_of "$(pid_of 'uvicorn server:app')")" = "/root" ] || fail "the runner's HOME is $(home_of "$(pid_of 'uvicorn server:app')")"
[ "$(home_of "$(pid_of 'uvicorn app:app')")" = "/home/agent" ] || fail "the gateway's HOME is $(home_of "$(pid_of 'uvicorn app:app')")"
# A session scope changes the filesystem uid and gid, not these: with group 0 here a planted link reaches what group 0 can write.
g=$(sed -n 's/^Groups:[[:space:]]*//p' "/proc/$(pid_of 'uvicorn server:app')/status" | tr -d ' ')
[ -z "$g" ] || fail "the runner keeps supplementary groups: $g"

for t in /app/x /app/ui/json.py /app/runner/x /app/gateway/x /data/agent-tools/x; do
  if su -s /bin/sh agent -c "touch '$t'" 2>/dev/null; then rm -f "$t"; fail "the product user can write $t"; fi
done
for d in agent-tools environments ws-markers workspaces; do
  if su -s /bin/sh agent -c "mv /data/$d /data/$d.moved" 2>/dev/null; then mv "/data/$d.moved" "/data/$d"; fail "the product user can move /data/$d"; fi
done
su -s /bin/sh agent -c 'touch /data/.check && rm /data/.check' 2>/dev/null || fail "the product user cannot make its own files on the volume"

[ "$bad" = 0 ] && echo "root boundary holds"
exit "$bad"
