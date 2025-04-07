#!/usr/bin/env python3

import os
import math
import argparse
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from statsmodels.tsa.arima.model import ARIMA
from pathlib import Path

class TrafficPredictor:
    def __init__(self, filename, sample_period, training_split=0.8):
        self.filename = filename
        self.sample_period = sample_period
        self.training_split = training_split
        self.df = None
        self.prediction = None
        self.training_data = None
        self.zone = self._extract_zone_from_path()
        
    def _extract_zone_from_path(self):
        """Extract zone information from the path or filename"""
        path_parts = Path(self.filename).parts
        switch_name = path_parts[-2]  # Parent directory (switch name)
        
        # Extract zone from switch name (s_zone)
        if switch_name.startswith('s_'):
            return switch_name[2:]
        return "unknown"
        
    def read_from_csv(self):
        """Load and preprocess traffic data from CSV"""
        # Read the CSV file
        self.df = pd.read_csv(self.filename)
        
        # Convert timestamp to datetime
        self.df['ds'] = pd.to_datetime(self.df['ds'], unit='s')
        
        # Set timestamp as index and resample
        self.df.set_index('ds', inplace=True)
        self.df = self.df.resample(self.sample_period).sum().fillna(0)
        
        # Convert from bytes to Mbps
        seconds_per_period = pd.Timedelta(self.sample_period).total_seconds()
        self.df['y'] = (self.df['y'] * 8) / (seconds_per_period * 2**20)
        
        # Add time features
        self.df['hour'] = self.df.index.hour
        self.df['is_peak'] = self._is_peak_hour(self.df.index.hour)
        self.df['day_part'] = self._get_day_part(self.df.index.hour)
        
        return self.df
    
    def _is_peak_hour(self, hour):
        """Determine if hour is peak time for this zone"""
        peak_hours = {
            'entertainment': range(18, 24),
            'security': range(0, 24),  # Security is always "peak"
            'automation': [6, 7, 8, 17, 18, 19, 20, 21],
            'workstation': range(9, 18),
            'gateway': range(0, 24)  # Gateway is always "peak"
        }
        return hour in peak_hours.get(self.zone, range(0, 24))
    
    def _get_day_part(self, hour):
        """Classify hour into part of day"""
        if 5 <= hour < 12:
            return 'morning'
        elif 12 <= hour < 17:
            return 'afternoon'
        elif 17 <= hour < 22:
            return 'evening'
        else:
            return 'night'
    
    def get_arima_order(self):
        """Get appropriate ARIMA parameters for this zone"""
        # Zone-specific ARIMA parameters
        orders = {
            'entertainment': (10, 0, 0),  # Higher AR component for streaming patterns
            'security': (3, 0, 0),        # Lower order for more stable traffic
            'automation': (5, 0, 0),      # Medium order for periodic patterns
            'workstation': (8, 0, 0),     # Medium-high for business hours
            'gateway': (30, 0, 0)         # High order for aggregated traffic
        }
        return orders.get(self.zone, (10, 0, 0))  # Default to medium order
    
    def run_arima(self, custom_order=None):
        """Run ARIMA prediction on the traffic data"""
        # Read and preprocess data
        self.df = self.read_from_csv()
        
        # Split data into training and testing
        split_idx = int(self.training_split * len(self.df))
        self.training_data = self.df.iloc[:split_idx]
        
        # Use custom order if provided, otherwise use zone-specific order
        order = custom_order if custom_order else self.get_arima_order()
        
        # Fit ARIMA model
        model = ARIMA(self.training_data['y'], order=order)
        fitted_model = model.fit()
        
        # Make predictions
        self.prediction = fitted_model.predict(
            start=self.df.index.min(),
            end=self.df.index.max()
        )
        
        # Calculate metrics
        test_data = self.df.iloc[split_idx:]
        if not test_data.empty:
            test_predictions = self.prediction[test_data.index]
            mse = np.mean((test_predictions - test_data['y']) ** 2)
            rmse = np.sqrt(mse)
            mae = np.mean(np.abs(test_predictions - test_data['y']))
            
            # Calculate peak/off-peak metrics if we have that data
            peak_mae = np.nan
            off_peak_mae = np.nan
            
            if 'is_peak' in test_data.columns:
                peak_data = test_data[test_data['is_peak']]
                off_peak_data = test_data[~test_data['is_peak']]
                
                if not peak_data.empty:
                    peak_predictions = self.prediction[peak_data.index]
                    peak_mae = np.mean(np.abs(peak_predictions - peak_data['y']))
                
                if not off_peak_data.empty:
                    off_peak_predictions = self.prediction[off_peak_data.index]
                    off_peak_mae = np.mean(np.abs(off_peak_predictions - off_peak_data['y']))
            
            metrics = {
                'mse': mse,
                'rmse': rmse,
                'mae': mae,
                'peak_mae': peak_mae,
                'off_peak_mae': off_peak_mae
            }
            
            return fitted_model, metrics
        
        return fitted_model, {}
    
    def plot(self, ax=None, show_training_split=True):
        """Plot actual vs predicted traffic"""
        if ax is None:
            _, ax = plt.subplots(figsize=(10, 6))
        
        # Plot predictions
        ax.plot(self.prediction, label="Prediction", color='red', linestyle='--')
        
        # Plot actual data
        ax.plot(self.df['y'], label="Actual Traffic", color='blue')
        
        # Mark training split
        if show_training_split and self.training_data is not None:
            ax.axvline(
                x=self.training_data.index.max(),
                color='green',
                linestyle='--',
                label='Training Split'
            )
        
        # Highlight peak hours if available
        if 'is_peak' in self.df.columns:
            peak_periods = self.df[self.df['is_peak']].index
            if len(peak_periods) > 0:
                ylim = ax.get_ylim()
                ax.fill_between(
                    peak_periods, 0, ylim[1],
                    color='yellow', alpha=0.2,
                    label='Peak Hours'
                )
                ax.set_ylim(ylim)
        
        # Set title based on zone
        zone_titles = {
            'entertainment': 'Entertainment Devices',
            'security': 'Security Devices',
            'automation': 'Home Automation',
            'workstation': 'Work Devices',
            'gateway': 'Internet Gateway'
        }
        title = zone_titles.get(self.zone, self.zone.capitalize())
        ax.set_title(f"{title} Traffic")
        
        ax.set_xlabel('Time')
        ax.set_ylabel('Bandwidth (Mbps)')
        ax.grid(True, alpha=0.3)
        
        return ax

def process_switch_data(switch_path, sample_period, training_split, store_plot):
    """Process all interfaces for a single switch"""
    # Get list of CSV files for this switch
    csv_files = [f for f in os.listdir(switch_path) if f.endswith('.csv')]
    
    if len(csv_files) <= 1:
        print(f"No sufficient connections on {switch_path}, skipping")
        return None
    
    # Calculate grid dimensions for subplot
    num_plots = len(csv_files)
    cols = min(3, num_plots)
    rows = math.ceil(num_plots / cols)
    
    # Create figure for this switch
    fig, axs = plt.subplots(rows, cols, figsize=(15, 10), sharey=True)
    if num_plots == 1:
        axs = np.array([axs])
    axs = axs.flatten()
    
    # Track metrics for this switch
    switch_metrics = []
    
    # Process each interface
    for i, csv_file in enumerate(csv_files):
        full_path = os.path.join(switch_path, csv_file)
        interface_name = csv_file.split('.')[0]  # Remove extension
        
        print(f"Processing {full_path}")
        
        # Create predictor and run ARIMA
        predictor = TrafficPredictor(full_path, sample_period, training_split)
        predictor.read_from_csv()
        _, metrics = predictor.run_arima()
        
        # Plot on the corresponding subplot
        predictor.plot(axs[i])
        axs[i].set_title(f"{interface_name}")
        
        # Store metrics
        metrics['interface'] = interface_name
        switch_metrics.append(metrics)
    
    # Hide unused subplots
    for i in range(num_plots, len(axs)):
        axs[i].set_visible(False)
    
    # Get switch name for title
    switch_name = os.path.basename(switch_path)
    
    # Add common legend and title
    handles, labels = axs[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc='upper right', bbox_to_anchor=(0.99, 0.99))
    fig.suptitle(f"Traffic Prediction - {switch_name}", fontsize=16)
    
    # Adjust layout and save
    plt.tight_layout()
    plt.subplots_adjust(top=0.92)
    output_file = os.path.join(store_plot, f"{switch_name}.png")
    plt.savefig(output_file)
    print(f"Saved plot to {output_file}")
    plt.close()
    
    return switch_metrics

def create_summary_plot(metrics_by_switch, store_plot):
    """Create a summary plot comparing performance across switches"""
    # Skip if no data
    if not metrics_by_switch:
        return
    
    # Prepare data for plotting
    switches = list(metrics_by_switch.keys())
    metrics = ['rmse', 'mae', 'peak_mae']
    metric_labels = {'rmse': 'RMSE', 'mae': 'MAE', 'peak_mae': 'Peak MAE'}
    
    # Calculate average metrics for each switch
    avg_metrics = {}
    for switch, metrics_list in metrics_by_switch.items():
        if not metrics_list:
            continue
            
        avg_metrics[switch] = {}
        for metric in metrics:
            values = [m.get(metric, np.nan) for m in metrics_list]
            values = [v for v in values if not np.isnan(v)]
            if values:
                avg_metrics[switch][metric] = np.mean(values)
            else:
                avg_metrics[switch][metric] = 0
    
    # Create bar chart
    fig, ax = plt.subplots(figsize=(12, 8))
    
    num_switches = len(avg_metrics)
    bar_width = 0.25
    index = np.arange(num_switches)
    
    for i, metric in enumerate(metrics):
        values = [avg_metrics[s].get(metric, 0) for s in avg_metrics]
        ax.bar(index + i*bar_width, values, bar_width, label=metric_labels[metric])
    
    ax.set_xlabel('Switch')
    ax.set_ylabel('Error (Mbps)')
    ax.set_title('Traffic Prediction Performance by Switch')
    ax.set_xticks(index + bar_width)
    ax.set_xticklabels(list(avg_metrics.keys()))
    ax.legend()
    
    plt.tight_layout()
    plt.savefig(os.path.join(store_plot, 'performance_summary.png'))
    plt.close()

def main():
    parser = argparse.ArgumentParser(description="Smart Home Traffic Prediction")
    parser.add_argument('--csv', type=str, default="captures",
                      help="Folder containing captured traffic data")
    parser.add_argument('--store-plot', type=str, default="plots",
                      help="Folder where prediction plots will be stored")
    parser.add_argument('--training-split', type=float, default=0.8,
                      help="Percentage of data used for training (0-1)")
    parser.add_argument('--sample-period', type=str, default="0.2S",
                      help="Period over which to combine network data")
    
    args = parser.parse_args()
    
    # Create output directory if needed
    if not os.path.exists(args.store_plot):
        os.mkdir(args.store_plot)
    
    # Process all switches in the captures directory
    path = args.csv
    if not os.path.isdir(path):
        print(f"Error: {path} is not a directory")
        return
    
    # Track metrics for all switches
    all_metrics = {}
    
    # Process each switch
    for switch in os.listdir(path):
        switch_path = os.path.join(path, switch)
        if not os.path.isdir(switch_path):
            continue
            
        print(f"\nProcessing switch: {switch}")
        metrics = process_switch_data(
            switch_path,
            args.sample_period,
            args.training_split,
            args.store_plot
        )
        
        if metrics:
            all_metrics[switch] = metrics
    
    # Create summary plot
    create_summary_plot(all_metrics, args.store_plot)
    
    print("\nTraffic prediction completed! Results saved to", args.store_plot)

if __name__ == "__main__":
    main() 