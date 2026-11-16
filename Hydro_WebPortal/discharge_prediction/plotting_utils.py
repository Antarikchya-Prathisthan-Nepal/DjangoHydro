"""
Utilities for generating and updating discharge forecast plots
"""
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, date
from django.conf import settings
from django.utils import timezone
from django.db import models
from .models import DischargeStation, DischargePrediction, MonthlyForecast, DHMStage
import os
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

class ForecastPlotter:
    """Handle automatic generation of forecast plots"""
    
    def __init__(self):
        self.plots_dir = getattr(settings, 'FORECAST_PLOTS_DIR', 'static/plots/forecasts')
        self.ensure_plots_directory()
        
        # Plot styling
        plt.style.use('seaborn-v0_8')
        self.colors = {
            'observed': '#2E86C1',
            'predicted': '#E74C3C',
            'confidence': '#F8C471',
            'background': '#FDFEFE',
            'grid': '#D5DBDB'
        }
    
    def ensure_plots_directory(self):
        """Create plots directory if it doesn't exist"""
        Path(self.plots_dir).mkdir(parents=True, exist_ok=True)
    
    def plot_monthly_forecast(self, station, forecast_month_date, save_plot=True):
        """
        Generate monthly forecast plot
        
        Args:
            station: DischargeStation instance
            forecast_month_date: First day of forecast month
            save_plot: Whether to save plot to file
        
        Returns:
            str: Path to saved plot file
        """
        try:
            # Get monthly forecast data
            monthly_forecast = MonthlyForecast.objects.filter(
                station=station,
                forecast_month=forecast_month_date
            ).first()
            
            if not monthly_forecast:
                raise Exception(f"No monthly forecast found for {station.name} - {forecast_month_date.strftime('%B %Y')}")
            
            # Get prediction data for the month
            predictions = DischargePrediction.objects.filter(
                station=station,
                forecast_timestamp__year=forecast_month_date.year,
                forecast_timestamp__month=forecast_month_date.month
            ).order_by('forecast_timestamp')
            
            if not predictions.exists():
                raise Exception(f"No predictions found for {station.name} - {forecast_month_date.strftime('%B %Y')}")
            
            # Prepare data
            dates = [p.forecast_timestamp.date() for p in predictions]
            predicted_discharge = [p.predicted_discharge for p in predictions]
            confidence_lower = [p.confidence_interval_lower or p.predicted_discharge * 0.85 for p in predictions]
            confidence_upper = [p.confidence_interval_upper or p.predicted_discharge * 1.15 for p in predictions]
            
            # Get historical data for context (previous 30 days)
            historical_start = forecast_month_date - timedelta(days=30)
            historical_records = DHMStage.objects.filter(
                station=station,
                timestamp__date__range=[historical_start, forecast_month_date - timedelta(days=1)]
            ).order_by('timestamp')
            
            historical_dates = [r.timestamp.date() for r in historical_records]
            historical_discharge = [
                station.compute_discharge_from_stage(r.stage_height)
                for r in historical_records
            ]
            
            # Create plot
            fig, ax = plt.subplots(figsize=(14, 8))
            fig.patch.set_facecolor(self.colors['background'])
            ax.set_facecolor(self.colors['background'])
            
            # Plot historical data
            if historical_dates:
                ax.plot(historical_dates, historical_discharge, 
                       color=self.colors['observed'], linewidth=2, 
                       label='Observed Discharge', marker='o', markersize=3)
            
            # Plot predictions
            ax.plot(dates, predicted_discharge, 
                   color=self.colors['predicted'], linewidth=2.5, 
                   label='Predicted Discharge', marker='s', markersize=4)
            
            # Plot confidence interval
            ax.fill_between(dates, confidence_lower, confidence_upper,
                          color=self.colors['confidence'], alpha=0.3,
                          label='Confidence Interval')
            
            # Formatting
            ax.set_title(f'{station.name} - Discharge Forecast\n{forecast_month_date.strftime("%B %Y")}',
                        fontsize=16, fontweight='bold', pad=20)
            ax.set_xlabel('Date', fontsize=12, fontweight='bold')
            ax.set_ylabel('Discharge (m³/s)', fontsize=12, fontweight='bold')
            
            # Format x-axis
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%d'))
            ax.xaxis.set_major_locator(mdates.DayLocator(interval=2))
            ax.xaxis.set_minor_locator(mdates.DayLocator())
            
            # Add vertical line to separate historical from predicted
            if historical_dates:
                ax.axvline(x=forecast_month_date, color='gray', linestyle='--', alpha=0.7)
                ax.text(forecast_month_date, ax.get_ylim()[1] * 0.9, 'Forecast Start',
                       rotation=90, ha='right', va='top', fontsize=10)
            
            # Force y-axis to start at 0
            y_max = max(
                max(predicted_discharge) if predicted_discharge else 0,
                max(historical_discharge) if historical_discharge else 0,
                max(confidence_upper) if confidence_upper else 0
            )
            # Add 5% padding to the top
            ax.set_ylim(0, y_max * 1.05 if y_max > 0 else 1)
            
            # Grid and legend
            ax.grid(True, alpha=0.3, color=self.colors['grid'])
            ax.legend(loc='upper right', frameon=True, fancybox=True, shadow=True)
            
            # Add statistics text box
            stats_text = f"""Forecast Statistics:
Mean: {monthly_forecast.mean_predicted_discharge:.1f} m³/s
Max: {monthly_forecast.max_predicted_discharge:.1f} m³/s
Min: {monthly_forecast.min_predicted_discharge:.1f} m³/s
Total Volume: {monthly_forecast.total_predicted_volume/1e6:.1f} million m³
Confidence: {(monthly_forecast.confidence_score or 0.85)*100:.0f}%"""
            
            ax.text(0.02, 0.98, stats_text, transform=ax.transAxes,
                   fontsize=10, verticalalignment='top',
                   bbox=dict(boxstyle='round', facecolor='white', alpha=0.8))
            
            plt.tight_layout()
            
            if save_plot:
                # Save plot
                filename = f"{station.station_id}_{forecast_month_date.strftime('%Y_%m')}_forecast.png"
                filepath = os.path.join(self.plots_dir, filename)
                plt.savefig(filepath, dpi=300, bbox_inches='tight', 
                          facecolor=self.colors['background'])
                logger.info(f"Monthly forecast plot saved: {filepath}")
                
                plt.close()
                return filepath
            else:
                plt.show()
                return None
                
        except Exception as e:
            logger.error(f"Failed to generate monthly forecast plot: {str(e)}")
            plt.close()
            return None
    
    def plot_annual_overview(self, station, year, save_plot=True):
        """
        Generate annual discharge overview with predictions
        
        Args:
            station: DischargeStation instance
            year: Year to plot
            save_plot: Whether to save plot to file
        
        Returns:
            str: Path to saved plot file
        """
        try:
            # Get all data for the year
            year_start = date(year, 1, 1)
            year_end = date(year, 12, 31)
            
            # Historical/observed data
            observed_records = DHMStage.objects.filter(
                station=station,
                timestamp__date__range=[year_start, year_end]
            ).order_by('timestamp')
            predicted_records = DischargePrediction.objects.filter(
                station=station,
                forecast_timestamp__date__range=[year_start, year_end]
            ).order_by('forecast_timestamp')
            
            # Create plot
            fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(16, 12), sharex=True)
            fig.patch.set_facecolor(self.colors['background'])
            
            # Main discharge plot
            if observed_records.exists():
                obs_dates = [r.timestamp.date() for r in observed_records]
                obs_discharge = [
                    station.compute_discharge_from_stage(r.stage_height)
                    for r in observed_records
                ]
                ax1.plot(obs_dates, obs_discharge, color=self.colors['observed'], 
                        linewidth=1.5, label='Observed Discharge', alpha=0.8)
            
            if predicted_records.exists():
                pred_dates = [p.forecast_timestamp.date() for p in predicted_records]
                pred_discharge = [p.predicted_discharge for p in predicted_records]
                ax1.plot(pred_dates, pred_discharge, color=self.colors['predicted'], 
                        linewidth=1.5, label='Predicted Discharge', alpha=0.8)
            
            ax1.set_title(f'{station.name} - Annual Discharge Overview {year}',
                         fontsize=16, fontweight='bold')
            ax1.set_ylabel('Discharge (m³/s)', fontsize=12, fontweight='bold')
            
            # Force discharge y-axis to start at 0
            if predicted_records.exists() or observed_records.exists():
                y_max1 = max(
                    max(pred_discharge) if predicted_records.exists() else 0,
                    max(obs_discharge) if observed_records.exists() else 0
                )
                ax1.set_ylim(0, y_max1 * 1.05)
                
            ax1.grid(True, alpha=0.3)
            ax1.legend()
            
            # Monthly statistics subplot
            monthly_stats = self._calculate_monthly_statistics(station, year)
            
            months = list(range(1, 13))
            month_names = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                          'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
            
            observed_monthly = [monthly_stats['observed'].get(m, 0) for m in months]
            predicted_monthly = [monthly_stats['predicted'].get(m, 0) for m in months]
            
            x = np.arange(len(month_names))
            width = 0.35
            
            ax2.bar(x - width/2, observed_monthly, width, label='Observed Mean',
                   color=self.colors['observed'], alpha=0.7)
            ax2.bar(x + width/2, predicted_monthly, width, label='Predicted Mean',
                   color=self.colors['predicted'], alpha=0.7)
            
            ax2.set_title('Monthly Average Discharge', fontsize=14, fontweight='bold')
            ax2.set_ylabel('Average Discharge (m³/s)', fontsize=12, fontweight='bold')
            ax2.set_xlabel('Month', fontsize=12, fontweight='bold')
            ax2.set_xticks(x)
            ax2.set_xticklabels(month_names)
            
            # Force y-axis to start at 0
            y_max2 = max(
                max(observed_monthly) if observed_monthly else 0,
                max(predicted_monthly) if predicted_monthly else 0
            )
            ax2.set_ylim(0, y_max2 * 1.05 if y_max2 > 0 else 1)
            
            ax2.grid(True, alpha=0.3)
            ax2.legend()
            
            plt.tight_layout()
            
            if save_plot:
                filename = f"{station.station_id}_{year}_annual_overview.png"
                filepath = os.path.join(self.plots_dir, filename)
                plt.savefig(filepath, dpi=300, bbox_inches='tight')
                logger.info(f"Annual overview plot saved: {filepath}")
                
                plt.close()
                return filepath
            else:
                plt.show()
                return None
                
        except Exception as e:
            logger.error(f"Failed to generate annual overview plot: {str(e)}")
            plt.close()
            return None
    
    def plot_prediction_accuracy(self, station, start_date, end_date, save_plot=True):
        """
        Generate prediction accuracy analysis plot
        
        Args:
            station: DischargeStation instance
            start_date: Start date for analysis
            end_date: End date for analysis
            save_plot: Whether to save plot to file
        
        Returns:
            str: Path to saved plot file
        """
        try:
            # Get predictions with actual data
            predictions = DischargePrediction.objects.filter(
                station=station,
                forecast_timestamp__date__range=[start_date, end_date],
                actual_discharge__isnull=False
            ).order_by('forecast_timestamp')
            
            if not predictions.exists():
                raise Exception("No validated predictions found for accuracy analysis")
            
            # Prepare data
            predicted_values = [p.predicted_discharge for p in predictions]
            actual_values = [p.actual_discharge for p in predictions]
            accuracy_scores = [p.accuracy_score for p in predictions]
            dates = [p.forecast_timestamp.date() for p in predictions]
            
            # Create subplots
            fig, ((ax1, ax2), (ax3, ax4)) = plt.subplots(2, 2, figsize=(16, 12))
            fig.patch.set_facecolor(self.colors['background'])
            
            # 1. Predicted vs Actual scatter plot
            ax1.scatter(actual_values, predicted_values, alpha=0.6, 
                       color=self.colors['predicted'], s=50)
            
            # Perfect prediction line
            min_val = min(min(actual_values), min(predicted_values))
            max_val = max(max(actual_values), max(predicted_values))
            ax1.plot([min_val, max_val], [min_val, max_val], 'r--', linewidth=2, alpha=0.8)
            
            ax1.set_xlabel('Actual Discharge (m³/s)', fontweight='bold')
            ax1.set_ylabel('Predicted Discharge (m³/s)', fontweight='bold')
            ax1.set_title('Predicted vs Actual Discharge', fontweight='bold')
            
            # Force axes to start at 0
            ax1.set_xlim(0, max_val * 1.05)
            ax1.set_ylim(0, max_val * 1.05)
            
            ax1.grid(True, alpha=0.3)
            
            # Add R² and RMSE
            correlation = np.corrcoef(actual_values, predicted_values)[0, 1]
            rmse = np.sqrt(np.mean([(p - a)**2 for p, a in zip(predicted_values, actual_values)]))
            ax1.text(0.05, 0.95, f'R² = {correlation**2:.3f}\nRMSE = {rmse:.2f}',
                    transform=ax1.transAxes, verticalalignment='top',
                    bbox=dict(boxstyle='round', facecolor='white', alpha=0.8))
            
            # 2. Time series comparison
            ax2.plot(dates, actual_values, color=self.colors['observed'], 
                    linewidth=2, label='Actual', marker='o', markersize=4)
            ax2.plot(dates, predicted_values, color=self.colors['predicted'], 
                    linewidth=2, label='Predicted', marker='s', markersize=4)
            
            ax2.set_xlabel('Date', fontweight='bold')
            ax2.set_ylabel('Discharge (m³/s)', fontweight='bold')
            ax2.set_title('Time Series Comparison', fontweight='bold')
            
            # Force y-axis to start at 0
            y_max = max(
                max(actual_values) if actual_values else 0,
                max(predicted_values) if predicted_values else 0
            )
            ax2.set_ylim(0, y_max * 1.05 if y_max > 0 else 1)
            
            ax2.grid(True, alpha=0.3)
            ax2.legend()
            
            # Format dates
            ax2.xaxis.set_major_formatter(mdates.DateFormatter('%m/%d'))
            ax2.xaxis.set_major_locator(mdates.WeekdayLocator())
            
            # 3. Accuracy scores over time
            ax3.plot(dates, accuracy_scores, color=self.colors['predicted'], 
                    linewidth=2, marker='o', markersize=4)
            ax3.axhline(y=np.mean(accuracy_scores), color='red', linestyle='--', 
                       label=f'Mean Accuracy: {np.mean(accuracy_scores):.3f}')
            
            ax3.set_xlabel('Date', fontweight='bold')
            ax3.set_ylabel('Accuracy Score', fontweight='bold')
            ax3.set_title('Prediction Accuracy Over Time', fontweight='bold')
            ax3.grid(True, alpha=0.3)
            ax3.legend()
            ax3.set_ylim(0, 1)
            
            # Format dates
            ax3.xaxis.set_major_formatter(mdates.DateFormatter('%m/%d'))
            ax3.xaxis.set_major_locator(mdates.WeekdayLocator())
            
            # 4. Error distribution
            errors = [p - a for p, a in zip(predicted_values, actual_values)]
            ax4.hist(errors, bins=20, color=self.colors['confidence'], 
                    alpha=0.7, edgecolor='black')
            ax4.axvline(x=0, color='red', linestyle='--', linewidth=2)
            ax4.axvline(x=np.mean(errors), color='blue', linestyle='--', 
                       label=f'Mean Error: {np.mean(errors):.2f}')
            
            ax4.set_xlabel('Prediction Error (m³/s)', fontweight='bold')
            ax4.set_ylabel('Frequency', fontweight='bold')
            ax4.set_title('Error Distribution', fontweight='bold')
            ax4.grid(True, alpha=0.3)
            ax4.legend()
            
            plt.suptitle(f'{station.name} - Prediction Accuracy Analysis\n{start_date} to {end_date}',
                        fontsize=16, fontweight='bold')
            plt.tight_layout()
            
            if save_plot:
                filename = f"{station.station_id}_accuracy_{start_date}_{end_date}.png"
                filepath = os.path.join(self.plots_dir, filename)
                plt.savefig(filepath, dpi=300, bbox_inches='tight')
                logger.info(f"Accuracy analysis plot saved: {filepath}")
                
                plt.close()
                return filepath
            else:
                plt.show()
                return None
                
        except Exception as e:
            logger.error(f"Failed to generate accuracy plot: {str(e)}")
            plt.close()
            return None
    
    def _calculate_monthly_statistics(self, station, year):
        """Calculate monthly statistics for observed and predicted data"""
        stats = {'observed': {}, 'predicted': {}}
        
        for month in range(1, 13):
            # Observed data
            observed = DHMStage.objects.filter(
                station=station,
                timestamp__year=year,
                timestamp__month=month
            )
            if observed.exists():
                stats['observed'][month] = sum(
                    station.compute_discharge_from_stage(r.stage_height) or 0
                    for r in observed
                ) / observed.count()
            
            # Predicted data
            predicted = DischargePrediction.objects.filter(
                station=station,
                forecast_timestamp__year=year,
                forecast_timestamp__month=month
            )
            if predicted.exists():
                stats['predicted'][month] = predicted.aggregate(
                    avg_discharge=models.Avg('predicted_discharge')
                )['avg_discharge']
        
        return stats
    
    def generate_all_plots(self, station, target_month=None):
        """
        Generate all plots for a station
        
        Args:
            station: DischargeStation instance
            target_month: Month to focus on (default: current month)
        """
        if target_month is None:
            target_month = date.today().replace(day=1)
        
        generated_plots = []
        
        try:
            # Monthly forecast plot
            monthly_plot = self.plot_monthly_forecast(station, target_month)
            if monthly_plot:
                generated_plots.append(monthly_plot)
            
            # Annual overview
            annual_plot = self.plot_annual_overview(station, target_month.year)
            if annual_plot:
                generated_plots.append(annual_plot)
            
            # Accuracy analysis (last 30 days)
            end_date = date.today()
            start_date = end_date - timedelta(days=30)
            accuracy_plot = self.plot_prediction_accuracy(station, start_date, end_date)
            if accuracy_plot:
                generated_plots.append(accuracy_plot)
            
            logger.info(f"Generated {len(generated_plots)} plots for {station.name}")
            return generated_plots
            
        except Exception as e:
            logger.error(f"Failed to generate plots for {station.name}: {str(e)}")
            return generated_plots
