#!/usr/bin/env python3
"""
main.py — SDN Traffic Prediction experiment

Builds a Mininet topology, generates structured traffic, captures
every packet per switch interface into CSV files, then exits cleanly.

Usage:
    sudo python3 main.py [--switches N] [--hosts N] [--cross-connection P]
                         [--time T] [--base-flows B] [--flows F]
"""

from mininet.topo import Topo
from mininet.net import Mininet
from mininet.node import OVSKernelSwitch
from mininet.link import TCLink
from mininet.log import setLogLevel

import networkx as nx
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.image as mpimg
from scapy.all import AsyncSniffer

import argparse
import csv
import math
import os
import random
import re
import time


CAPTURES_FOLDER    = "captures"
HOST_LINK_MAX_BW   = 2
HOST_LINK_MIN_BW   = 1
SWITCH_LINK_MAX_BW = 2
SWITCH_LINK_MIN_BW = 1


class Topology(Topo):

    def __init__(self, num_switches, num_hosts, interconnectivity, seed=0):
        super().__init__()
        self.num_switches      = num_switches
        self.num_hosts         = num_hosts
        self.interconnectivity = interconnectivity
        self.seed              = seed

        random.seed(self.seed)
        host_count = 1

        for i in range(self.num_switches):
            sw = f"s{i + 1}"
            self.addSwitch(sw, stp=True, failMode='standalone')

            if i > 0:
                bw = random.uniform(SWITCH_LINK_MIN_BW, SWITCH_LINK_MAX_BW)
                self.addLink(sw, f"s{i}", bw=bw)

            for _ in range(self.num_hosts):
                host = f"h{host_count}"
                self.addHost(host)
                bw = random.uniform(HOST_LINK_MIN_BW, HOST_LINK_MAX_BW)
                self.addLink(sw, host, bw=bw)
                host_count += 1

        # cross-links between non-adjacent switches
        connected_pairs = set()
        for i in range(1, self.num_switches + 1):
            for j in range(1, self.num_switches + 1):
                if i == j or abs(i - j) == 1:
                    continue
                if (j, i) in connected_pairs:
                    continue
                if random.random() < self.interconnectivity:
                    connected_pairs.add((i, j))
                    bw = random.uniform(SWITCH_LINK_MIN_BW, SWITCH_LINK_MAX_BW)
                    self.addLink(f"s{i}", f"s{j}", bw=bw)

    def save_topology_image(self, path="topology_image.png"):
        G = nx.Graph()
        for node in self.nodes():
            G.add_node(node,
                node_type='switch' if node.startswith('s') else 'host')
        for u, v in self.links():
            G.add_edge(u, v)

        switch_nodes = [n for n, d in G.nodes(data=True)
                        if d['node_type'] == 'switch']
        host_nodes   = [n for n, d in G.nodes(data=True)
                        if d['node_type'] == 'host']

        pos       = nx.spring_layout(G, seed=42,
                                     k=1 / math.sqrt(max(len(G), 1)),
                                     iterations=100)
        label_pos = {k: (v[0], v[1] + 0.09) for k, v in pos.items()}

        plt.figure(figsize=(8, 6))
        ax = plt.gca()

        nx.draw_networkx_edges(G, pos, ax=ax, alpha=0.8,
                               width=1.5, edge_color='#555555')
        nx.draw_networkx_labels(G, label_pos,
                                labels={n: n for n in switch_nodes},
                                ax=ax, font_size=12,
                                font_color='#003366', font_weight='bold')
        nx.draw_networkx_labels(G, label_pos,
                                labels={n: n for n in host_nodes},
                                ax=ax, font_size=12,
                                font_color='#006400', font_weight='bold')

        try:
            sw_icon   = mpimg.imread('switch_icon.png')
            host_icon = mpimg.imread('host_icon.png')
            for node, (x, y) in pos.items():
                icon = (sw_icon if G.nodes[node]['node_type'] == 'switch'
                        else host_icon)
                s = 0.15
                ax.imshow(icon,
                          extent=(x-s/2, x+s/2, y-s/2, y+s/2),
                          aspect='equal', zorder=5)
        except FileNotFoundError:
            nx.draw_networkx_nodes(G, pos, nodelist=switch_nodes,
                                   node_color='red',    node_size=500)
            nx.draw_networkx_nodes(G, pos, nodelist=host_nodes,
                                   node_color='orange', node_size=300)

        plt.title("Network Topology", fontsize=16)
        ax.margins(0.1, 0.1)
        ax.tick_params(left=False, bottom=False,
                       labelleft=False, labelbottom=False)
        plt.box(False)
        plt.savefig(path, dpi=300)
        plt.close()
        print(f"\n*** Topology image saved → '{path}'")


class NetworkManager:

    def __init__(self):
        self.net      = None
        self.sniffers = []

    def create_net(self, topology):
        self.net = Mininet(
            topo=topology,
            switch=OVSKernelSwitch,
            build=False,
            autoSetMacs=True,
            autoStaticArp=True,
            link=TCLink
        )
        return self.net

    def check_stp_configuration(self):
        # STP takes ~30s to elect a root and move ports to FORWARD.
        # We poll every switch — not just s1 — to be sure all are ready.
        print("\n*** Waiting for STP to converge on all switches...")
        for switch in self.net.switches:
            name = switch.name
            print(f"    Checking {name}...", end='', flush=True)
            while True:
                out = switch.cmdPrint(
                    f'ovs-ofctl show {name} | grep -o FORWARD | head -n1'
                )
                if 'FORWARD' in out:
                    print(" ready")
                    break
                time.sleep(3)

    def start_servers(self, base_flows, flows_per_host):
        random.seed(time.time())

        for h in self.net.hosts:
            h.cmd('iperf -s -p 5050 &')

        # continuous flows — always-on background load
        safe_base = min(base_flows, len(self.net.hosts))
        if safe_base < base_flows:
            print(f"[WARN] base_flows clamped {base_flows}→{safe_base}")
        for h in random.sample(self.net.hosts, safe_base):
            others = [x for x in self.net.hosts if x != h]
            target = random.choice(others)
            h.cmd(f"iperf -t 0 -c {target.IP()} -p 5050 &")
            print(f"    Continuous flow: {h.name} → {target.name}")

        # periodic ON/OFF flows — the structured signal ARIMA learns from
        for h in self.net.hosts:
            others     = [x for x in self.net.hosts if x != h]
            safe_flows = min(flows_per_host, len(others))
            if safe_flows < flows_per_host:
                print(f"[WARN] flows_per_host clamped {flows_per_host}→{safe_flows} "
                      f"for {h.name}")
            for target in random.sample(others, safe_flows):
                h.cmd(f"python3 utils/traffic_generation.py {target.IP()} &")
                print(f"    Periodic flow:   {h.name} → {target.name}")

    def create_captures_folder(self):
        os.system(f"rm -rf {CAPTURES_FOLDER}")
        os.mkdir(CAPTURES_FOLDER)
        for sw in self.net.switches:
            os.mkdir(os.path.join(CAPTURES_FOLDER, sw.name))

    def start_traffic_capture(self):
        iface_re   = re.compile(r's\d+-eth\d+')
        interfaces = [i for i in os.listdir('/sys/class/net/')
                      if iface_re.match(i)]

        if not interfaces:
            raise RuntimeError("No Mininet interfaces found — did the network start?")

        for iface in interfaces:
            parts   = iface.split('-')
            path    = os.path.join(CAPTURES_FOLDER, *parts)
            csvfile = open(path + '.csv', 'w', newline='')
            writer  = csv.writer(csvfile)
            writer.writerow(['ds', 'y'])

            # factory avoids the classic loop-closure bug
            def make_handler(w):
                def handler(pkt):
                    w.writerow([pkt.time, len(pkt)])
                return handler

            sniffer = AsyncSniffer(
                iface=iface,
                store=False,
                prn=make_handler(writer)
            )
            sniffer.start()
            print(f"    Capturing on {iface}")
            self.sniffers.append((sniffer, csvfile))

    def stop_traffic_capture(self):
        for sniffer, csvfile in self.sniffers:
            sniffer.stop()
            csvfile.close()
        self.sniffers.clear()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="SDN Traffic Prediction — data collection"
    )
    parser.add_argument('--switches',         type=int,   default=2)
    parser.add_argument('--hosts',            type=int,   default=2)
    parser.add_argument('--cross-connection', type=float, default=0.30)
    parser.add_argument('--time',             type=int,   default=120)
    parser.add_argument('--base-flows',       type=int,   default=2)
    parser.add_argument('--flows',            type=int,   default=2)
    args = parser.parse_args()

    print('*** Cleaning previous Mininet state...')
    os.system("mn -c 2>/dev/null")

    topology = Topology(
        num_switches=args.switches,
        num_hosts=args.hosts,
        interconnectivity=args.cross_connection,
        seed=0
    )
    topology.save_topology_image()

    setLogLevel('info')

    network = NetworkManager()
    net     = network.create_net(topology)
    net.build()
    net.start()
    time.sleep(1)

    network.check_stp_configuration()
    print("\n*** STP converged. Waiting 5s for tables to settle...")
    time.sleep(5)

    print("\n*** Testing connectivity...")
    net.pingAll()
    time.sleep(1)

    print("\n*** Starting traffic generators...")
    network.start_servers(args.base_flows, args.flows)
    time.sleep(2)

    print("\n*** Starting packet capture...")
    network.create_captures_folder()
    network.start_traffic_capture()

    print(f"\n*** Experiment running for {args.time}s — do not interrupt...")

    # try/finally guarantees teardown even if something crashes mid-experiment
    try:
        time.sleep(args.time)
    finally:
        print("\n*** Stopping capture and tearing down network...")
        network.stop_traffic_capture()
        net.stop()

    print(f"\n*** Done. CSV files are in: {CAPTURES_FOLDER}")
    print(f"    Run: python3 traffic_prediction.py --csv {CAPTURES_FOLDER}")
