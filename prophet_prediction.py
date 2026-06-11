#!/usr/bin/env python3
"""
prophet_prediction.py

Traffic prediction using Prophet for comparison with ARIMA.
Uses the same CSV captures produced by Scapy.

Usage:
    pip install prophet
    python3 prophet_prediction.py --csv captures --store-plot plots_prophet
                                  --training-split 0.75 --sample-period 1S
"""

import os
import math
import argparse
import warnings
warnings.filterwarnings('ignore')

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

from prophet import Prophet


class ProphetPrediction():

    def read_from_csv(self, filename, sample_period):
        # Prophet needs columns named 'ds' (datetime) and 'y' (value)
        df = pd.read_csv(filename)
        df['ds'] = pd.to_datetime(df['ds'], unit='s')
        df.set_index('ds', inplace=True)
        df = df.resample(sample_period).sum(numeric_only=True).fillna(0)

        bin_seconds = pd.Timedelta(sample_period).total_seconds()
        df['y'] = (df['y'] * 8) / (bin_seconds * 2**20)

        # reset index so 'ds' becomes a column again
        df = df.reset_index()
        self.df = df[['ds', 'y']]

    def run_prophet(self, training_split=0.75):
        split_idx          = int(training_split * len(self.df))
        self.training_data = self.df.iloc[:split_idx].copy()
        self.test_data     = self.df.iloc[split_idx:].copy()

        print(f'    Training rows : {len(self.training_data)}')
        print(f'    Test rows     : {len(self.test_data)}')

        if len(self.training_data) < 10:
            print(f'    [WARN] Not enough training rows for Prophet')
            self.forecast_df  = None
            self.in_sample_df = None
            return float('nan'), float('nan')

        # weekly and yearly seasonality are off — 120s is too short
        # daily seasonality is on since we are working at sub-second scale
        model = Prophet(
            daily_seasonality       = True,
            weekly_seasonality      = False,
            yearly_seasonality      = False,
            changepoint_prior_scale = 0.05,
            interval_width          = 0.95,
        )

        try:
            model.fit(self.training_data)
        except Exception as e:
            print(f'    [ERROR] Prophet fit failed: {e}')
            self.forecast_df  = None
            self.in_sample_df = None
            return float('nan'), float('nan')

        # fitted values on the training window — used only for plotting
        in_sample_future  = model.make_future_dataframe(
            periods=0, freq='S', include_history=True
        )
        self.in_sample_df = model.predict(in_sample_future)

        # blind forecast on the test window
        n_test           = len(self.test_data)
        future           = model.make_future_dataframe(
            periods=n_test, freq='S', include_history=False
        )
        self.forecast_df = model.predict(future)

        # bandwidth cannot go negative
        for col in ['yhat', 'yhat_lower', 'yhat_upper']:
            self.forecast_df[col] = self.forecast_df[col].clip(lower=0)

        actual    = self.test_data['y'].values
        predicted = self.forecast_df['yhat'].values[:n_test]
        mae  = float(np.mean(np.abs(predicted - actual)))
        rmse = float(np.sqrt(np.mean((predicted - actual) ** 2)))

        return mae, rmse

    def plot(self, ax):
        if self.forecast_df is None:
            ax.text(0.5, 0.5, 'Fit failed',
                    transform=ax.transAxes, ha='center')
            return

        n_test = len(self.test_data)

        ax.plot(self.df['ds'], self.df['y'],
                label='Actual', linestyle='dotted',
                color='steelblue', linewidth=1.2)

        ax.plot(self.in_sample_df['ds'],
                self.in_sample_df['yhat'].clip(lower=0),
                label='Training (fitted)',
                color='orange', linewidth=1.0, alpha=0.85)

        ax.plot(self.forecast_df['ds'][:n_test],
                self.forecast_df['yhat'][:n_test],
                label='Forecast (blind)',
                color='red', linewidth=1.5)

        ax.fill_between(
            self.forecast_df['ds'][:n_test],
            self.forecast_df['yhat_lower'][:n_test],
            self.forecast_df['yhat_upper'][:n_test],
            alpha=0.15, color='red', label='95% interval'
        )

        ax.axvline(
            x=self.training_data['ds'].max(),
            color='green', linestyle='--',
            linewidth=1.2, label='Train/Test split'
        )

        ax.set_xlabel('Time')
        ax.set_ylabel('Mbps')
        ax.grid(True, alpha=0.3)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='Prophet traffic prediction — SDN project'
    )
    parser.add_argument('--csv',            type=str,   default='captures')
    parser.add_argument('--store-plot',     type=str,   default='plots_prophet')
    parser.add_argument('--training-split', type=float, default=0.75)
    parser.add_argument('--sample-period',  type=str,   default='1S')
    args = parser.parse_args()

    if not os.path.exists(args.store_plot):
        os.mkdir(args.store_plot)

    print(f'Training split : {args.training_split*100:.0f}% / '
          f'{(1-args.training_split)*100:.0f}%')
    print(f'Sample period  : {args.sample_period}\n')

    summary = []

    for switch in sorted(os.listdir(args.csv)):
        switch_path = os.path.join(args.csv, switch)
        if not os.path.isdir(switch_path):
            continue

        intf_csv   = sorted(f for f in os.listdir(switch_path)
                            if f.endswith('.csv'))
        plot_count = len(intf_csv)

        if plot_count <= 1:
            print(f'Skipping {switch} — only {plot_count} interface(s)')
            continue

        print(f'\n{"="*50}')
        print(f'  Switch: {switch}')
        print(f'{"="*50}')

        num_cols = math.ceil(math.sqrt(plot_count))
        num_rows = math.ceil(plot_count / num_cols)

        fig, axs = plt.subplots(
            num_rows, num_cols,
            sharey=False, sharex=False,
            figsize=(7 * num_cols, 4 * num_rows)
        )
        axs = np.array(axs).flatten()

        for ax, interface in zip(axs, intf_csv):
            full_path = os.path.join(switch_path, interface)
            print(f'\n  Interface: {interface[:-4]}')

            pred = ProphetPrediction()

            try:
                pred.read_from_csv(full_path, args.sample_period)
            except Exception as e:
                print(f'  [ERROR] {e}')
                ax.axis('off')
                continue

            mae, rmse = pred.run_prophet(
                training_split=args.training_split
            )

            if math.isnan(mae):
                ax.set_title(f'{interface[:-4]}\n(fit failed)')
                ax.axis('off')
                continue

            print(f'  MAE={mae:.4f}  RMSE={rmse:.4f} Mbps')

            summary.append({
                'Switch':    switch,
                'Interface': interface[:-4],
                'MAE':       round(mae,  4),
                'RMSE':      round(rmse, 4)
            })

            pred.plot(ax)
            ax.set_title(
                f'{interface[:-4]}\nMAE={mae:.4f}  RMSE={rmse:.4f} Mbps',
                fontsize=10
            )

        for ax in axs[plot_count:]:
            ax.axis('off')

        handles, labels = axs[0].get_legend_handles_labels()
        fig.legend(handles, labels, loc='upper right',
                   fancybox=True, fontsize=9)
        fig.suptitle(f'Switch: {switch} — Prophet', fontsize=14)

        plt.tight_layout(pad=0.8)
        out_path = os.path.join(args.store_plot, switch) + '.png'
        plt.savefig(out_path, dpi=150, bbox_inches='tight')
        plt.close(fig)
        print(f'\n  Saved → {out_path}')

    if summary:
        print(f'\n{"="*50}')
        print('  SUMMARY — Prophet')
        print(f'{"="*50}')
        df = pd.DataFrame(summary)
        print(df.to_string(index=False))
        print(f'\nAverage MAE  : {df["MAE"].mean():.4f} Mbps')
        print(f'Average RMSE : {df["RMSE"].mean():.4f} Mbps')
        best  = df.loc[df["MAE"].idxmin()]
        worst = df.loc[df["MAE"].idxmax()]
        print(f'Best  : {best["Switch"]}/{best["Interface"]}  '
              f'MAE={best["MAE"]:.4f}')
        print(f'Worst : {worst["Switch"]}/{worst["Interface"]}  '
              f'MAE={worst["MAE"]:.4f}')
