#!/usr/bin/env bash


set -euo pipefail

SMALL_BLOCK=1000     
LARGE_BLOCK=65535     

DATA_AMOUNTS=("100m" "500m" "1g" "2g")

SKIP_TCP_SAW=1        
BINARY_DIR="$(dirname "$0")/build"
SERVER_BIN="${BINARY_DIR}/server"
CLIENT_BIN="${BINARY_DIR}/client"

SERVER_WAIT=1        
CLIENT_TIMEOUT=600  
PROTO="${1:-}"
HOST="${2:-127.0.0.1}"
PORT="${3:-9000}"

if [[ -z "$PROTO" ]]; then
    echo "Usage: $0 tcp|udp|quic [host] [port]"
    exit 1
fi

if [[ "$PROTO" != "tcp" && "$PROTO" != "udp" && "$PROTO" != "quic" ]]; then
    echo "Unknown protocol: $PROTO"
    exit 1
fi

if [[ ! -x "$CLIENT_BIN" || ! -x "$SERVER_BIN" ]]; then
    echo "[ERROR] Binaries not found in ${BINARY_DIR}."
    echo "Build first:  mkdir -p build && cd build && cmake .. && make -j\$(nproc)"
    exit 1
fi

RESULT_FILE="results_${PROTO}.txt"
echo "============================================================" | tee -a "$RESULT_FILE"
echo " PCD HW1 — Protocol: ${PROTO^^}  $(date)"                    | tee -a "$RESULT_FILE"
echo " Host: $HOST   Port: $PORT"                                   | tee -a "$RESULT_FILE"
echo " Small block: ${SMALL_BLOCK} B   Large block: ${LARGE_BLOCK} B" | tee -a "$RESULT_FILE"
echo "============================================================" | tee -a "$RESULT_FILE"


cleanup_server() {
    if [[ -n "${SERVER_PID:-}" ]]; then
        kill "$SERVER_PID" 2>/dev/null || true
        wait "$SERVER_PID" 2>/dev/null || true
        SERVER_PID=""
    fi
}
trap cleanup_server EXIT


if [[ "$PROTO" == "tcp" && "$SKIP_TCP_SAW" -eq 1 ]]; then
    MODES=("streaming")
else
    MODES=("streaming" "stop-and-wait")
fi


for BLOCK in "$SMALL_BLOCK" "$LARGE_BLOCK"; do
    for AMOUNT in "${DATA_AMOUNTS[@]}"; do
        for MODE in "${MODES[@]}"; do

            echo ""                                                              | tee -a "$RESULT_FILE"
            echo "────────────────────────────────────────────────────────────" | tee -a "$RESULT_FILE"
            echo " Proto=${PROTO^^}  Block=${BLOCK}B  Amount=${AMOUNT}  Mode=${MODE}" | tee -a "$RESULT_FILE"
            echo "────────────────────────────────────────────────────────────" | tee -a "$RESULT_FILE"

            cleanup_server
            "$SERVER_BIN" --protocol "$PROTO" --port "$PORT" \
                >> "server_${PROTO}.log" 2>&1 &
            SERVER_PID=$!
            sleep "$SERVER_WAIT"

            if ! kill -0 "$SERVER_PID" 2>/dev/null; then
                echo "[ERROR] Server crashed — check server_${PROTO}.log"     | tee -a "$RESULT_FILE"
                continue
            fi

            set +e
            timeout "$CLIENT_TIMEOUT" \
                "$CLIENT_BIN" \
                    --protocol   "$PROTO"  \
                    --host       "$HOST"   \
                    --port       "$PORT"   \
                    --block-size "$BLOCK"  \
                    --total-bytes "$AMOUNT" \
                    --mode       "$MODE"   \
                2>&1 | tee -a "$RESULT_FILE"
            EXIT_CODE=$?
            set -e

            if [[ $EXIT_CODE -eq 124 ]]; then
                echo "[WARN] Client timed out after ${CLIENT_TIMEOUT}s"        | tee -a "$RESULT_FILE"
            elif [[ $EXIT_CODE -ne 0 ]]; then
                echo "[WARN] Client exited with code $EXIT_CODE"               | tee -a "$RESULT_FILE"
            fi

            sleep 1

            cleanup_server

        done
    done
done

echo ""                                                                         | tee -a "$RESULT_FILE"
echo "============================================================"             | tee -a "$RESULT_FILE"
echo " All tests complete.  Results saved to: $RESULT_FILE"                    | tee -a "$RESULT_FILE"
echo "============================================================"             | tee -a "$RESULT_FILE"
