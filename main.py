#!/usr/bin/env python3

# Mininet libraries
from mininet.topo import Topo
from mininet.net import Mininet
from mininet.node import OVSKernelSwitch, RemoteController
from mininet.cli import CLI
from mininet.link import TCLink
from mininet.log import setLogLevel, info

# Installed libraries
import networkx as nx
import matplotlib.pyplot as plt
from scapy.all import AsyncSniffer

# Default libraries
import time
import random
import os
import re
import csv
import math
import argparse
import threading

# Simulation parameters
FOLDER_CAPTURES = "captures"

class RandomTopo(Topo):
    def __init__(self, num_switches, hosts_per_switch, interconnectivity, seed=0):
        super().__init__()
        self.num_switches = num_switches
        self.hosts_per_switch = hosts_per_switch
        self.interconnectivity = interconnectivity
        self.seed = seed
        
        # Set random seed for reproducibility
        random.seed(self.seed)
        
        # Create switches
        switches = []
        for i in range(self.num_switches):
            switch = self.addSwitch(f's{i+1}', stp=True, failMode='standalone')
            switches.append(switch)
            
            # Create and connect hosts for each switch
            for j in range(self.hosts_per_switch):
                host = self.addHost(f'h{i+1}{j+1}')
                # Random bandwidth between 1-10 Mbps
                self.addLink(host, switch, bw=random.uniform(1, 10))
        
        # Connect switches in a line topology (minimum spanning tree)
        for i in range(1, self.num_switches):
            # Random bandwidth between 10-50 Mbps
            self.addLink(switches[i], switches[i-1], bw=random.uniform(10, 50))
        
        # Add random cross-connections based on interconnectivity parameter
        connected_pairs = set()
        for i in range(self.num_switches):
            for j in range(i+2, self.num_switches):  # Skip adjacent switches (already connected)
                if random.random() < self.interconnectivity:
                    # Avoid duplicate connections
                    if (i, j) not in connected_pairs and (j, i) not in connected_pairs:
                        # Random bandwidth between 5-30 Mbps
                        self.addLink(switches[i], switches[j], bw=random.uniform(5, 30))
                        connected_pairs.add((i, j))
    
    def visualize_topology(self):
        """Create a visual representation of the network topology"""
        G = nx.Graph()
        
        # Add nodes
        switch_nodes = []
        host_nodes = []
        
        for node in self.nodes():
            if node.startswith('s'):
                G.add_node(node, node_type='switch')
                switch_nodes.append(node)
            else:
                G.add_node(node, node_type='host')
                host_nodes.append(node)
        
        # Add edges (links)
        for u, v in self.links(withKeys=True):
            G.add_edge(u, v)
        
        # Create visualization
        plt.figure(figsize=(12, 8))
        pos = nx.spring_layout(G, seed=42)
        
        # Draw nodes
        nx.draw_networkx_nodes(G, pos, nodelist=switch_nodes, node_color='red', 
                               node_size=500, label='Switches')
        nx.draw_networkx_nodes(G, pos, nodelist=host_nodes, node_color='blue', 
                               node_size=300, label='Hosts')
        
        # Draw edges and labels
        nx.draw_networkx_edges(G, pos, width=1.0, alpha=0.7)
        nx.draw_networkx_labels(G, pos, font_size=8)
        
        plt.title("Network Topology")
        plt.axis('off')
        plt.tight_layout()
        plt.savefig("network_topology.png")
        plt.close()
        print("Topology visualization saved as 'network_topology.png'")

class NetworkManager:
    def __init__(self):
        self.net = None
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
        """Wait for Spanning Tree Protocol to converge"""
        print("Waiting for STP to converge...")
        for switch in self.net.switches:
            while "FORWARD" not in switch.cmd(f'ovs-ofctl show {switch.name} | grep -o FORWARD | head -n1'):
                time.sleep(1)
                print(".", end="", flush=True)
            print(f"\n{switch.name} converged")
    
    def generate_traffic(self, duration, num_flows, base_flows):
        """Generate traffic between random hosts"""
        print(f"Generating {base_flows} continuous flows and {num_flows} periodic flows")
        
        # Start iperf servers on all hosts
        for host in self.net.hosts:
            host.cmd('iperf -s -p 5050 &')
        
        # Generate continuous base flows
        for _ in range(base_flows):
            src = random.choice(self.net.hosts)
            dst = random.choice([h for h in self.net.hosts if h != src])
            src.cmd(f'iperf -t 0 -c {dst.IP()} -p 5050 -i 1 &')
            print(f"Started continuous flow: {src.name} -> {dst.name}")
        
        # Generate periodic flows over time
        end_time = time.time() + duration
        
        def run_periodic_flows():
            while time.time() < end_time:
                for _ in range(num_flows):
                    src = random.choice(self.net.hosts)
                    dst = random.choice([h for h in self.net.hosts if h != src])
                    
                    # Random duration between 2-8 seconds
                    flow_duration = random.randint(2, 8)
                    
                    # Random bandwidth between 1-20 Mbps
                    bandwidth = random.randint(1, 20)
                    
                    src.cmd(f'iperf -t {flow_duration} -c {dst.IP()} -p 5050 -b {bandwidth}M &')
                
                # Wait random time between 1-5 seconds before next batch
                time.sleep(random.uniform(1, 5))
        
        # Start traffic generation in a thread
        thread = threading.Thread(target=run_periodic_flows)
        thread.daemon = True
        thread.start()
    
    def create_captures_folder(self):
        """Create folders for storing traffic captures"""
        os.system(f"rm -rf {FOLDER_CAPTURES}")
        os.mkdir(FOLDER_CAPTURES)
        
        # Create a folder for each switch
        for switch in self.net.switches:
            os.mkdir(os.path.join(FOLDER_CAPTURES, switch.name))
    
    def start_traffic_capture(self):
        """Capture traffic on all interfaces"""
        interface_pattern = re.compile(r's\d+-eth\d+')
        interfaces = [i for i in os.listdir('/sys/class/net/') if interface_pattern.match(i)]
        
        if len(interfaces) == 0:
            print("ERROR: Could not find any mininet network adapters")
            return
        
        def start_sniffer(iface, path):
            csvfile = open(path + '.csv', 'w', newline='')
            writer = csv.writer(csvfile)
            print(f"Beginning capture on {iface}")
            
            writer.writerow(['ds', 'y'])
            
            def handler(pkt):
                writer.writerow([time.time(), len(pkt)])
            
            sniffer = AsyncSniffer(iface=iface, store=False, prn=handler)
            sniffer.start()
            return sniffer, csvfile
        
        for iface in interfaces:
            # Get the switch name by splitting interface
            switch_name = iface.split('-')[0]
            path = os.path.join(FOLDER_CAPTURES, switch_name, f"intf_{iface.split('-')[1]}")
            self.sniffers.append(start_sniffer(iface, path))
    
    def stop_traffic_capture(self):
        """Stop all traffic captures"""
        for sniffer, csvfile in self.sniffers:
            sniffer.stop()
            csvfile.close()

def parse_arguments():
    parser = argparse.ArgumentParser(description="SDN Traffic Prediction - Network Setup")
    parser.add_argument('--switches', type=int, default=7, help="Number of switches")
    parser.add_argument('--hosts', type=int, default=2, help="Number of hosts per switch")
    parser.add_argument('--cross-connection', type=float, default=0.30, 
                      help="Interconnectivity ratio between switches (0-1)")
    parser.add_argument('--time', type=int, default=30, help="Test duration in seconds")
    parser.add_argument('--flows', type=int, default=2, help="Number of periodic flows")
    parser.add_argument('--base-flows', type=int, default=3, help="Number of continuous flows")
    parser.add_argument('--seed', type=int, default=0, help="Random seed for reproducibility")
    return parser.parse_args()

if __name__ == "__main__":
    args = parse_arguments()
    
    print('*** Cleaning network instances')
    os.system("mn -c")
    
    # Create random topology
    topology = RandomTopo(
        args.switches, 
        args.hosts, 
        args.cross_connection,
        args.seed
    )
    
    # Visualize the topology
    topology.visualize_topology()
    
    # Create and start network
    setLogLevel('info')
    network = NetworkManager()
    net = network.create_net(topology)
    
    net.build()
    net.start()
    time.sleep(1)
    
    # Wait for STP to converge
    network.check_stp_configuration()
    
    print("\n*** Testing ping connectivity...")
    net.pingAll()
    
    # Start traffic capture
    print("\n*** Setting up traffic capture...")
    network.create_captures_folder()
    network.start_traffic_capture()
    
    # Generate traffic
    print("\n*** Generating traffic...")
    network.generate_traffic(args.time, args.flows, args.base_flows)
    
    # Wait for test to complete
    print(f"\n*** Running test for {args.time} seconds...")
    time.sleep(args.time)
    
    # Stop capture and cleanup
    print("\n*** Stopping traffic capture...")
    network.stop_traffic_capture()
    net.stop()
    
    print("\n*** Test completed! Run traffic_prediction.py to analyze the data.") 