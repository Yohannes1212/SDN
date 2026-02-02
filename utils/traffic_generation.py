import sys
import os
import subprocess 
import random
import time

MAX_RANDOM_FLOW_BW = .5
MAX_RANDOM_FLOW_DURATION = 2
MAX_IDLE_TIME = 2

if __name__ == "__main__":
    host_ip = sys.argv[1]
    # random.random() → gives a number between 0 and 1
    # So duration ∈ [0, 2], 
    # bandwidth ∈ [0, 0.5] Mbps,
    # idle ∈ [0, 2]
    duration = random.random()*MAX_RANDOM_FLOW_DURATION
    bw = random.random()*MAX_RANDOM_FLOW_BW
    idle_time = random.random()*MAX_IDLE_TIME
    cmd = f'iperf -t {duration} -c {host_ip} -b {bw}M -p 5050'
    # starts an iperfclient to the given host with the random bandwidth 
    # and duration waits for it to finish, 
    # then sleeps for some random time before starting again. This creates periodic, bursty, random traffic. 
    while True:
        subprocess.Popen( cmd, shell=True).wait()
        time.sleep(idle_time)
