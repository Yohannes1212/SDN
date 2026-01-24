# SDN Traffic Prediction

## Overview

This project analyzes traffic patterns and predicts future traffic within Software-Defined Networking (SDN) environments. It involves capturing network traffic using RYU controller, followed by training ARIMA machine learning models to forecast traffic. The implementation includes traffic flow generation, data capture, and prediction using 80% of the data for training and 20% for testing.

## Objectives

- To implement a random topology using Mininet and Ryu controller
- To generate network traffic dataset
- To capture traffic flowing through the network
- To apply machine learning (ARIMA) to predict future traffic patterns

## Requirements

- Python 3.x
- Mininet network emulator
- RYU SDN controller
- Python libraries (installed via requirements.txt)

## Installation

1. Install dependencies:
```bash
sudo pip3 install -r requirements.txt
```

2. Start the RYU controller in a separate terminal:
```bash
ryu-manager ryu.app.simple_switch_stp
```

## Usage

### 1. Generate Network Topology and Traffic

Run the following command to create a random network topology and generate traffic:

```bash
sudo python3 main.py --switches 7 --hosts 2 --cross-connection 0.3 --time 30 --flows 2 --base-flows 3
```

Parameters:
- `--switches`: Number of switches in the network (default: 7)
- `--hosts`: Number of hosts per switch (default: 2)
- `--cross-connection`: Interconnectivity ratio between switches (default: 0.3)
- `--time`: Test duration in seconds (default: 30)
- `--flows`: Number of periodic flows (default: 2)
- `--base-flows`: Number of continuous flows (default: 3)
- `--seed`: Random seed for reproducibility (default: 0)

The script:
1. Creates a random network topology
2. Establishes continuous and periodic traffic flows
3. Captures traffic data on all interfaces

### 2. Traffic Prediction

After collecting traffic data, run the prediction script:

```bash
python3 traffic_prediction.py
```

Parameters:
- `--csv`: Path to captured data directory (default: "captures")
- `--store-plot`: Output directory for plots (default: "plots")
- `--training-split`: Training data percentage (default: 0.8)
- `--sample-period`: Data resampling period (default: "0.2S")

## Implementation Details
<img width="6537" height="410" alt="image" src="https://github.com/user-attachments/assets/5526372b-26a1-4461-a97f-ffd88a78c550" />
<img width="6877" height="305" alt="image" src="https://github.com/user-attachments/assets/9c8a3905-5362-47a5-a22e-8aadb8c8bf59" />


### Network Topology Generation
- Creates a random network with configurable number of switches and hosts
- Establishes minimum spanning tree connectivity plus cross-connections
- Visualizes the network topology using NetworkX

### Traffic Generation
- Establishes continuous base flows for background traffic
- Creates periodic traffic flows with random durations and bandwidths
- Traffic is captured on all network interfaces

### Traffic Prediction
- Uses ARIMA (AutoRegressive Integrated Moving Average) model
- Preprocesses data by resampling and converting to Mbps
- Evaluates prediction accuracy using MSE, RMSE, and MAE metrics
- Generates visualizations comparing actual vs. predicted traffic

## Output

The implementation produces:
1. Network topology visualization ("network_topology.png")
2. Traffic capture data (CSV files in "captures" directory)
3. Traffic prediction plots for each switch in the network ("plots" directory)

## Example

Complete test run:

```bash
# In terminal 1 - Start RYU controller
ryu-manager ryu.app.simple_switch_stp

# In terminal 2 - Run network simulation
sudo python3 main.py --switches 5 --hosts 3 --cross-connection 0.4 --time 60

# After simulation completes
python3 traffic_prediction.py --training-split 0.8
```

## Notes

- The simulation requires root privileges to run Mininet
- Longer capture durations generally provide better prediction results
- The ARIMA model uses parameters (5,1,0) which can be adjusted for better results
- Network visualization helps understand traffic flow patterns
