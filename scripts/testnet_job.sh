#!/bin/bash
# Testing-network job helper for worker sessions.
#   testnet_job.sh start LOG -- COMMAND...   run COMMAND detached, output to LOG
#   testnet_job.sh wait LOG                  block up to ~9 minutes; commit and push
#                                            LOG to the current branch; print
#                                            JOB_RUNNING or JOB_DONE and the last
#                                            result/state line
set -u
cd "$(dirname "$0")/.."
mode=$1; log=$2; shift 2
pidfile="$log.pid"
case "$mode" in
  start)
    [ "${1:-}" = "--" ] && shift
    mkdir -p "$(dirname "$log")"
    setsid nohup "$@" > "$log" 2>&1 < /dev/null &
    echo $! > "$pidfile"
    echo "JOB_STARTED pid $(cat "$pidfile")"
    ;;
  wait)
    pid=$(cat "$pidfile")
    for _ in $(seq 1 54); do
      kill -0 "$pid" 2>/dev/null || break
      sleep 10
    done
    git add -f "$log" >/dev/null 2>&1
    git -c user.name="Aster testnet" -c user.email="testnet@users.noreply.github.com" \
      commit -q -m "testnet: results $(basename "$log")" >/dev/null 2>&1
    for delay in 2 4 8 16; do
      git push -q -u origin HEAD >/dev/null 2>&1 && break
      sleep $delay
    done
    if kill -0 "$pid" 2>/dev/null; then echo JOB_RUNNING; else echo JOB_DONE; fi
    grep -E "SPSA_STATE|TESTNET_RESULT|TESTNET_READY|Traceback|RuntimeError|Error" "$log" | tail -1 | cut -c1-400
    ;;
esac
