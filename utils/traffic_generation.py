import sys
import os
import subprocess
import random
import time
import signal

ON_DURATION  = 5.0   # seconds — how long each active burst lasts
OFF_DURATION = 1.0   # seconds — silence between bursts
MIN_FLOW_BW  = 0.2   # Mbps — minimum bandwidth during ON phase
MAX_FLOW_BW  = 1.0   # Mbps — maximum bandwidth during ON phase

def graceful_exit(signum, frame):
    """Allow Mininet to kill this process cleanly via SIGTERM(termination signal)."""
    sys.exit(0)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: traffic_generation.py <host_ip>")
        sys.exit(1)

    # Read host_ip ONCE before the loop — not on every iteration
    host_ip = sys.argv[1]

    # Handle SIGTERM so Mininet can shut down cleanly
    signal.signal(signal.SIGTERM, graceful_exit)

    print(f"[traffic_gen] Starting intermittent traffic to {host_ip}")
    print(f"[traffic_gen] Pattern: ON={ON_DURATION}s / OFF={OFF_DURATION}s")

    while True:
        # ON phase — send traffic for ON_DURATION seconds
        # BW varies each cycle so the signal is not a flat square wave
        bw = MIN_FLOW_BW + random.random() * (MAX_FLOW_BW - MIN_FLOW_BW)

        print(f"[traffic_gen] ON  → {host_ip} | {ON_DURATION}s @ {bw:.3f}Mbps")
        subprocess.Popen(
            f"iperf -t {ON_DURATION:.1f} -c {host_ip} -b {bw:.3f}M -p 5050",
            shell=True
        ).wait()

        # OFF phase — complete silence so ARIMA can learn the ON/OFF rhythm
        print(f"[traffic_gen] OFF → {host_ip} | {OFF_DURATION}s silence")
        time.sleep(OFF_DURATION)
