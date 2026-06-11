#!/usr/bin/env python3
"""
traffic_prediction.py

Reads per-interface CSV captures from Scapy, converts them to Mbps
time series, fits ARIMA, and forecasts the blind test window.

Usage:
    python3 traffic_prediction.py [--csv captures] [--store-plot plots]
                                  [--training-split 0.75]
                                  [--sample-period 1S]
                                  [--order 30,0,0]
"""

import os
import math
import argparse

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from statsmodels.tsa.arima.model import ARIMA
from statsmodels.tsa.stattools import adfuller


class TrafficPrediction():

    def read_from_csv(self, filename, sample_period):
        self.df = pd.read_csv(filename)
        self.df['ds'] = pd.to_datetime(self.df['ds'], unit='s')
        self.df.set_index('ds', inplace=True)
        self.df = self.df.resample(sample_period).sum(numeric_only=True).fillna(0)

        bin_seconds = pd.Timedelta(sample_period).total_seconds()
        self.df['y'] /= bin_seconds
        self.df['y'] *= 8
        self.df['y'] /= 2**20

    def check_stationarity(self, training_data):
        # ADF test — informational only, does not change the order
        series = training_data['y'].dropna()
        result = adfuller(series)
        p_val  = result[1]
        status = "stationary (d=0 ok)" if p_val < 0.05 else "non-stationary (consider d=1)"
        print(f"    ADF p-value: {p_val:.4f}  →  {status}")
        return p_val

    def run_arima(self, order, training_split=0.75):
        split_idx          = int(training_split * len(self.df))
        self.training_data = self.df.iloc[:split_idx]
        self.test_data     = self.df.iloc[split_idx:]

        if len(self.training_data) < max(order[0], 5):
            print(f"    [WARN] Only {len(self.training_data)} training rows "
                  f"for order {order}")

        self.check_stationarity(self.training_data)

        try:
            model        = ARIMA(self.training_data['y'], order=order)
            fitted_model = model.fit()
        except Exception as e:
            print(f"    [ERROR] ARIMA failed: {e}")
            self.in_sample_fit = None
            self.forecast_vals = None
            return float('nan'), float('nan')

        # fittedvalues = what the model saw during training — for plotting only
        self.in_sample_fit = fitted_model.fittedvalues.clip(lower=0)

        # forecast() predicts beyond the last training point — model never saw these
        n_test       = len(self.test_data)
        raw_forecast = fitted_model.forecast(steps=n_test)

        # forecast() returns integer-indexed series — reassign timestamps for the plot
        self.forecast_vals = pd.Series(
            raw_forecast.clip(0).values,
            index=self.test_data.index
        )

        actual    = self.test_data['y'].values
        predicted = self.forecast_vals.values
        mae  = float(np.mean(np.abs(predicted - actual)))
        rmse = float(np.sqrt(np.mean((predicted - actual) ** 2)))

        return mae, rmse

    def plot(self, ax):
        if self.forecast_vals is None:
            ax.text(0.5, 0.5, "Fit failed",
                    transform=ax.transAxes, ha='center')
            return

        ax.plot(self.df['y'],
                label="Actual", linestyle='dotted',
                color='steelblue', linewidth=1.2)

        ax.plot(self.in_sample_fit,
                label="In-sample fit",
                color='orange', linewidth=1.0, alpha=0.85)

        ax.plot(self.forecast_vals,
                label="Forecast (blind)",
                color='red', linewidth=1.5)

        ax.axvline(
            x=self.training_data.index.max(),
            color='green', linestyle='--',
            linewidth=1.0, label='Training Split'
        )

        ax.set_xlabel("Time")
        ax.set_ylabel("Mbps")
        ax.grid(True, alpha=0.3)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="ARIMA traffic prediction for SDN captures"
    )
    parser.add_argument('--csv',            type=str,   default="captures")
    parser.add_argument('--store-plot',     type=str,   default="plots")
    parser.add_argument('--training-split', type=float, default=0.75)
    parser.add_argument('--sample-period',  type=str,   default="1S")
    parser.add_argument('--order',          type=str,   default="30,0,0")
    args = parser.parse_args()

    try:
        p, d, q     = map(int, args.order.split(','))
        arima_order = (p, d, q)
    except Exception:
        print(f"Invalid order '{args.order}' — using (30,0,0)")
        arima_order = (30, 0, 0)

    if not os.path.exists(args.store_plot):
        os.mkdir(args.store_plot)

    print(f"ARIMA order    : {arima_order}")
    print(f"Training split : {args.training_split*100:.0f}% / "
          f"{(1-args.training_split)*100:.0f}%")
    print(f"Sample period  : {args.sample_period}\n")

    for switch in sorted(os.listdir(args.csv)):
        switch_path = os.path.join(args.csv, switch)
        if not os.path.isdir(switch_path):
            continue

        intf_csv   = [f for f in os.listdir(switch_path) if f.endswith('.csv')]
        plot_count = len(intf_csv)

        if plot_count <= 1:
            print(f"Skipping {switch} — only {plot_count} interface(s)")
            continue

        num_cols = math.ceil(math.sqrt(plot_count))
        num_rows = math.ceil(plot_count / num_cols)

        fig, axs = plt.subplots(num_rows, num_cols,
                                sharey=False, sharex=False,
                                figsize=(6 * num_cols, 4 * num_rows))
        axs = np.array(axs).flatten()

        for ax, interface in zip(axs, intf_csv):
            full_path = os.path.join(switch_path, interface)
            print(f"Reading {full_path}")

            prediction = TrafficPrediction()

            try:
                prediction.read_from_csv(full_path, args.sample_period)
            except Exception as e:
                print(f"  [ERROR] {e}")
                ax.axis('off')
                continue

            print(f"Running ARIMA{arima_order}...")
            mae, rmse = prediction.run_arima(
                order=arima_order,
                training_split=args.training_split
            )

            if math.isnan(mae):
                ax.set_title(f"{interface[:-4]}\n(fit failed)")
                ax.axis('off')
                continue

            print(f"MAE: {mae:.4f} Mbps   RMSE: {rmse:.4f} Mbps")

            prediction.plot(ax)
            ax.set_title(f"{interface[:-4]}\nMAE={mae:.4f}  RMSE={rmse:.4f} Mbps")

        for ax in axs[plot_count:]:
            ax.axis('off')

        fig.legend(*axs[0].get_legend_handles_labels(), fancybox=True)
        fig.suptitle(f"Switch: {switch}", fontsize=20)

        plt.tight_layout(pad=0.5)
        out_path = os.path.join(args.store_plot, switch) + '.png'
        plt.savefig(out_path, dpi=150)
        plt.close(fig)
        print(f"Saved → {out_path}\n")
