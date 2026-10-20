#!/bin/bash
# Testing-network job helper for worker sessions.
#   testnet_job.sh start LOG -- COMMAND...   run COMMAND detached, appending to LOG;
#                                            COMMAND is remembered in LOG.cmd
#   testnet_job.sh wait LOG                  block up to ~9 minutes; if the job died
#                                            (e.g. container restart) before printing a
#                                            *_DONE line, restart it with --resume LOG;
#                                            commit and push LOG; print JOB_RUNNING or
#                                            JOB_DONE and the last state line
set -u
cd "$(dirname "$0")/.."
mode=$1; log=$2; shift 2
pidfile="$log.pid"
cmdfile="$log.cmd"

launch() {
    mkdir -p "$(dirname "$log")"
    # shellcheck disable=SC2046
    setsid nohup bash -c "$(cat "$cmdfile") --resume '$log'" >> "$log" 2>&1 < /dev/null &
    echo $! > "$pidfile"
}

alive() { [ -f "$pidfile" ] && kill -0 "$(cat "$pidfile")" 2>/dev/null; }
finished() { grep -qE '^(SPSA_DONE|TESTNET_DONE)' "$log" 2>/dev/null; }

case "$mode" in
  start)
    [ "${1:-}" = "--" ] && shift
    mkdir -p "$(dirname "$log")"
    printf '%q ' "$@" > "$cmdfile"
    launch
    echo "JOB_STARTED pid $(cat "$pidfile")"
    ;;
  wait)
    for _ in $(seq 1 54); do
      alive || break
      sleep 10
    done
    if ! alive && ! finished; then
      echo "JOB_RESUMING" | tee -a "$log"
      launch
      sleep 5
    fi
    # Results are shipped only from worker branches (testnet/<label>-<worker>).
    if git symbolic-ref --short HEAD 2>/dev/null | grep -q '^testnet/'; then
      git add -f "$log" "$cmdfile" >/dev/null 2>&1
      git -c user.name="Aster testnet" -c user.email="testnet@users.noreply.github.com" \
        commit -q -m "testnet: results $(basename "$log")" >/dev/null 2>&1
      for delay in 2 4 8 16; do
        git push -q -u origin HEAD >/dev/null 2>&1 && break
        sleep $delay
      done
    fi
    if finished && ! alive; then echo JOB_DONE; else echo JOB_RUNNING; fi
    grep -E "SPSA_STATE|TESTNET_RESULT|TESTNET_READY|Traceback|RuntimeError|Error" "$log" | tail -1 | cut -c1-400
    ;;
esac
