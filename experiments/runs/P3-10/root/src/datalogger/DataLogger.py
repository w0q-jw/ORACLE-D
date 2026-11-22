# SPDX-License-Identifier: Apache-2.0
# Copyright 2023-2026 Deutsches Elektronen Synchrotron DESY 
#                     and the University of Glasgow
# Authors: Dwayne Spiteri and Gordon Stewart.
# For more information about rights and fair use please refer to src/Main.py.
# For full detailed and legal infomration please read the LICENSE and NOTICE
#    files in the main directory 
# ===========================================================================

from logging import config

from util import Logging

import os
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

logger = Logging.get_logger()


class DataLogger():

    # This should also write to disk...

    def __init__(self, config): 
        self._jobs_submitted = 0
        self._jobs_generated = 0
        self._jobs_started = 0
        self._jobs_finished = 0
        self._jobs_failed = 0
        self._jobs_aborted = 0
        self._jobs_total_cores_used = 0        

        # Could store these by job type...
        self._cumulative_cpu_time = 0
        self._cumulative_wallclock_time = 0
        self._total_energy_consumed = 0
        self._peaktime_energy_consumed = 0
        self._total_carbon_consumed = 0
        self._peaktime_carbon_consumed = 0
        self._sum_occupancy = 0
        self._cumulative_wait_time = 0
        
        # Averages
        self._avg_jobs_completed = 0
        self._avg_energy_per_job = 0
        self._avg_carbon_per_job = 0
        self._avg_occupancy = 0

        self._job_durations = []
        self._timestep_timestamps = []
        self._timestep_occupancies = []
        self._timestep_carbon_intensities = []
        self._site_job_totals = {}
        self._site_job_started_totals = {}
        self._site_job_finished_totals = {}

        # verbosity
        self._verbosity = config["output"]["verbosity"]
        self._run_dir = config["output"].get("run_dir", "logs")
        self._simulation_parameters = {}

        self._site_id = config.get("site_id", config.get("output", {}).get("site_id", "site"))

    def set_simulation_parameters(self, simulation_parameters):
        self._simulation_parameters = simulation_parameters

    def set_jobs_generated(self, jobs_generated):
        self._jobs_generated = jobs_generated

    def job_submit(self, job):
        self._jobs_submitted += 1
        pass


    def job_start(self, job, worker_node):
        if self._verbosity in ["high"]:
            logger.info(f'At site {self._site_id}: Starting job {job} on node {worker_node.hostname} with origin {job.origin_site} at {job.start_time}')
        self._jobs_started += 1
        self._jobs_total_cores_used += job.cores_req

        if job.submit_time != None and job.start_time != None:
            wait_seconds = (job.start_time - job.submit_time).total_seconds()
            self._cumulative_wait_time += wait_seconds


    def job_finish(self, job, worker_node):
        if self._verbosity in ["high"]:
            logger.info(f'At site {self._site_id}: Job {job} finished on node {worker_node.hostname} with origin {job.origin_site} at {job.end_time}')
        self._jobs_finished += 1
        self._cumulative_wallclock_time += job.duration
        self._job_durations.append(job.duration)
        # Yes, Sam, I know... ;-)
        self._cumulative_cpu_time += job.duration * job.cores_req

    def energy_and_carbon_consumed(self, timestep_energy_consumed, timestep_carbon_consumed_per_site_energy):
        '''
        This should pass power dissipated in per timestep (kWh) such that the total consumption is in kiloWatt-hours
        This should pass carbon consumed in per timestep (g/kWh) such that the total consumption is in grams/kiloWatt-hours
        '''
        self._total_energy_consumed += timestep_energy_consumed # kWh
        self._total_carbon_consumed += timestep_energy_consumed * timestep_carbon_consumed_per_site_energy #g/kWh

    def peaktime_energy_and_carbon_consumed(self, timestep_energy_consumed, timestep_carbon_consumed_per_site_energy):
        '''
        This should pass power dissipated in per timestep (kWh) such that the total consumption is in kiloWatt-hours
        This should pass carbon consumed in per timestep (g/kWh) such that the total consumption is in grams/kiloWatt-hours
        '''
        self._peaktime_energy_consumed += timestep_energy_consumed # kWh
        self._peaktime_carbon_consumed += timestep_energy_consumed * timestep_carbon_consumed_per_site_energy #g/kWh  
    
    def sum_occupancy(self, timestep_occupancy):
        '''
        This should store the sum of the occupancy every timestep (to be divided by the number of timesteps when the simulation ends)
        '''
        self._sum_occupancy += timestep_occupancy # kWh


    def record_timestep_metrics(self, timestep_timestamp, timestep_occupancy, timestep_carbon_intensity):
        self._timestep_timestamps.append(timestep_timestamp)
        self._timestep_occupancies.append(timestep_occupancy)
        self._timestep_carbon_intensities.append(timestep_carbon_intensity)

    def print_summary(self, summary_file, additional_description, total_simulated_time, timestepinsec, total_real_time, summary_dir=None, print_console=True):
        self._avg_jobs_completed = self._jobs_finished + (self._jobs_started - self._jobs_finished)/2
        self._avg_energy_per_job = self._safe_divide(self._total_energy_consumed, self._avg_jobs_completed)
        self._avg_carbon_per_job = self._safe_divide(self._total_carbon_consumed, self._avg_jobs_completed)
        self._avg_occupancy      = self._safe_divide(self._sum_occupancy, (total_simulated_time/timestepinsec))
        summary_lines = self._format_summary_lines(total_simulated_time, total_real_time) #, job_length_stats

        self._emit_summary_lines(summary_lines, print_console=print_console)
        
        if summary_file == True:
            output_dir = summary_dir or self._run_dir
            os.makedirs(output_dir, exist_ok=True)

            summary_path = os.path.join(output_dir, 'summary.txt')
            with open(summary_path, 'a') as outfile:
                for line in summary_lines:
                    outfile.write(f'{line}\n')
                outfile.write(f'\n')

            self._plot_occupancy_and_carbon_intensity(output_dir)



    def comparison(self, baseline_logger, run_seed, actual_duration_s, baseline_duration_s):
        percentage_of_baseline_jobs_completed = self._safe_divide(self._jobs_finished, baseline_logger._jobs_finished) * 100
        carbon_saved_g = baseline_logger._total_carbon_consumed - self._total_carbon_consumed
        carbon_saved_percentage = (carbon_saved_g / baseline_logger._total_carbon_consumed) * 100 if baseline_logger._total_carbon_consumed > 0 else 0
        energy_saved_kwh = baseline_logger._total_energy_consumed - self._total_energy_consumed
        cpu_time_difference = self._cumulative_cpu_time - baseline_logger._cumulative_cpu_time
        logger.info(f"Base c: {baseline_logger._total_carbon_consumed} Actual c: {self._total_carbon_consumed} Base cpu: {baseline_logger._cumulative_cpu_time} Actual cpu: {self._cumulative_cpu_time}")
        carbon_per_cpu_hour_baseline = baseline_logger._total_carbon_consumed/ baseline_logger._cumulative_cpu_time
        carbon_per_cpu_hour = self._total_carbon_consumed/self._cumulative_cpu_time
        carbon_per_cpu_hour_percentage = (carbon_per_cpu_hour_baseline - carbon_per_cpu_hour)/carbon_per_cpu_hour_baseline * 100 if carbon_per_cpu_hour_baseline > 0 else 0
        cpu_time_per_job = self._safe_divide(self._cumulative_cpu_time, self._jobs_finished)
        baseline_cpu_time_per_job = self._safe_divide(baseline_logger._cumulative_cpu_time, baseline_logger._jobs_finished)
        cpu_time_per_job_difference = cpu_time_per_job - baseline_cpu_time_per_job
        time_difference_s = actual_duration_s - baseline_duration_s
        avg_wait_actual = self._safe_divide(self._cumulative_wait_time, self._jobs_started)/3600
        avg_wait_baseline = baseline_logger._safe_divide(baseline_logger._cumulative_wait_time, baseline_logger._jobs_started)/3600
        wait_time_difference = avg_wait_actual - avg_wait_baseline

        return {
        "random_seed": run_seed,
        "percentage_of_baseline_jobs_completed": percentage_of_baseline_jobs_completed,
        "actual_total_carbon_g": self._total_carbon_consumed,
        "baseline_total_carbon_g": baseline_logger._total_carbon_consumed,
        "carbon_saved_kg": carbon_saved_g / 1e3,
        "carbon_saved_percentage": carbon_saved_percentage,
        "actual_total_energy_consumed": self._total_energy_consumed,
        "baseline_total_energy_consumed": baseline_logger._total_energy_consumed,
        "energy_saved_kwh": energy_saved_kwh,
        "actual_duration_seconds": actual_duration_s,
        "baseline_duration_seconds": baseline_duration_s,
        "time_difference_seconds": time_difference_s,
        "avg_wait_actual_hours": avg_wait_actual,
        "avg_wait_baseline_hours": avg_wait_baseline,
        "wait_time_difference": wait_time_difference,
        "actual_cumulative_cpu_time": self._cumulative_cpu_time,
        "baseline_cumulative_cpu_time": baseline_logger._cumulative_cpu_time,
        "cpu_time_difference": cpu_time_difference,
        "actual_cpu_time_per_job": cpu_time_per_job,
        "baseline_cpu_time_per_job": baseline_cpu_time_per_job,
        "cpu_time_per_job_difference": cpu_time_per_job_difference,
        "actual_cumulative_wait_time": self._cumulative_wait_time,
        "baseline_cumulative_wait_time": baseline_logger._cumulative_wait_time,
        "wait_time_difference": wait_time_difference,
        "carbon_per_cpu_hour": carbon_per_cpu_hour,
        "carbon_per_cpu_hour_baseline": carbon_per_cpu_hour_baseline,
        "carbon_per_cpu_hour_percentage": carbon_per_cpu_hour_percentage
        }

    def print_comparison(self, comparison, run_dir, print_console=True):
        lines = self._format_comparison_lines(comparison)
        os.makedirs(run_dir, exist_ok=True)
        with open(os.path.join(run_dir, 'carbon_savings_summary.txt'), 'w') as outfile:
            outfile.write('\n'.join(lines) + '\n')


        comparison_summary = [
            f'Percentage of baseline jobs completed: {comparison["percentage_of_baseline_jobs_completed"]:.2f} %',
            f'Carbon saved vs baseline: {comparison["carbon_saved_kg"]:.3f} kg',
            f'Time difference vs baseline: {comparison["time_difference_seconds"]/3600:.2f} hours',
            f'Energy saved vs baseline: {comparison["energy_saved_kwh"]:.3f} kWh',
            f'CPU time per job difference vs baseline: {comparison["cpu_time_per_job_difference"]/3600:.2f} hours',
        ]
        self._emit_summary_lines(comparison_summary, print_console=print_console)

    def _format_comparison_lines(self, comparison):
        return [
        f'Carbon Savings Summary',
        f'=======================',
        f'',
        f'Random seed used             : {comparison["random_seed"]}',
        f'Percentage of baseline jobs completed: {comparison["percentage_of_baseline_jobs_completed"]:.2f} %',
        f'',
        f'Actual total carbon consumed  : {comparison["actual_total_carbon_g"]/1e3:.3f} kg',
        f'Baseline total carbon consumed: {comparison["baseline_total_carbon_g"]/1e3:.3f} kg',
        f'Carbon saved                  : {comparison["carbon_saved_kg"]:.3f} kg',
        f'Carbon saved percentage         : {comparison["carbon_saved_percentage"]:.2f} %',
        f'Carbon saved per CPU hour       : {comparison["carbon_per_cpu_hour"]:.3e} g/kWh',
        f'Carbon saved per CPU hour (baseline): {comparison["carbon_per_cpu_hour_baseline"]:.3e} g/kWh',
        f'Carbon saved per CPU hour percentage: {comparison["carbon_per_cpu_hour_percentage"]:.2f} %',
        f'',
        f'Actual run duration            : {comparison["actual_duration_seconds"]/3600:.2f} hours',
        f'Baseline run duration          : {comparison["baseline_duration_seconds"]/3600:.2f} hours',
        f'Time difference (actual - base): {comparison["time_difference_seconds"]/3600:.2f} hours',
        f'',
        f'Actual average wait time per job: {comparison["avg_wait_actual_hours"]:.2f} hours',
        f'Baseline average wait time per job: {comparison["avg_wait_baseline_hours"]:.2f} hours',
        f'Wait time difference (actual - base): {comparison["wait_time_difference"]:.2f} hours',
        f''
        f'Actual total energy consumed   : {comparison["actual_total_energy_consumed"]:.3f} kWh',
        f'Baseline total energy consumed: {comparison["baseline_total_energy_consumed"]:.3f} kWh',
        f'Energy saved                    : {comparison["energy_saved_kwh"]:.3f} kWh',
        f'',
        f'Actual cumulative CPU time      : {comparison["actual_cumulative_cpu_time"]/3600:.2f} hours',
        f'Baseline cumulative CPU time    : {comparison["baseline_cumulative_cpu_time"]/3600:.2f} hours',
        f'CPU time difference            : {comparison["cpu_time_difference"]/3600:.2f} hours',

        f'CPU time per job (actual)        : {comparison["actual_cpu_time_per_job"]/3600:.2f} hours',
        f'CPU time per job (baseline)      : {comparison["baseline_cpu_time_per_job"]/3600:.2f} hours',
        f'CPU time per job difference      : {comparison["cpu_time_per_job_difference"]/3600:.2f} hours'        '',
        ]
        

    def _create_summary(self, total_simulated_time, total_real_time):
        return {
            "simulation_parameters": self._simulation_parameters,
            "duration": {
                "simulated_seconds": total_simulated_time,
                "simulated_hours": total_simulated_time/3600,
                "real_seconds": total_real_time,
                "real_minutes": total_real_time/60,
            },
            "jobs": {
                "started": self._jobs_started,
                "finished": self._jobs_finished,
                "average_completed": self._avg_jobs_completed,
                "total_cores_used": self._jobs_total_cores_used,
            },
            "cpu": {
                "total_core_seconds": self._cumulative_cpu_time,
                "total_core_hours": self._cumulative_cpu_time/3600,
                "average_core_hours": self._safe_divide((self._cumulative_cpu_time/3600), self._jobs_total_cores_used),
            },
            "occupancy": {
                "average_fraction": self._avg_occupancy,
                "average_percent": self._avg_occupancy*100,
            },
            "energy": {
                "total_kwh": self._total_energy_consumed,
                #"peaktime_kwh": self._peaktime_energy_consumed,
                "average_per_job_wh": self._avg_energy_per_job*1e3,
            },
            "carbon": {
                "total_g": self._total_carbon_consumed,
                "total_kg": self._total_carbon_consumed/1e3,
                #"peaktime_g": self._peaktime_carbon_consumed,
                #"peaktime_kg": self._peaktime_carbon_consumed/1e3,
                "average_per_job_g": self._avg_carbon_per_job,
                #"peaktime_percent": self._safe_divide(self._peaktime_carbon_consumed, self._total_carbon_consumed) * 100,
            },
        }



    def _format_summary_lines(self, total_simulated_time, total_real_time): 
        summary_lines = [
            f'Data centre: {self._site_id}',
            f'========',
            f'Summary',
            f'========',
            f'',
            f'Total Simulated-time Duration      : {total_simulated_time/3600:4.1f} hours',
            f'Total Real-time Duration           : {total_real_time/60:4.1f} minutes',
            f'',
            f'Jobs Generated                     : {self._jobs_generated}',
            f'Jobs Started                       : {self._jobs_started}',
            f'Jobs Finished                      : {self._jobs_finished}',
            f'',
            f'Total CPU duration                 : {self._cumulative_cpu_time/3600:6.1f} hours',
            f'Average CPU duration               : {self._safe_divide((self._cumulative_cpu_time/3600), self._jobs_total_cores_used):4.2f} hours',
            f'Average Occupancy of all clusters  : {(self._avg_occupancy*100):3.1f} %',
            f'',
            f'Total energy consumed by compute   : {self._total_energy_consumed:3.2f} kWh',
           # f'Peaktime (5-9pm) energy consumption: {self._peaktime_energy_consumed:3.2f} kWh',
            f'Average energy consumption per job : {self._avg_energy_per_job*1e3:3.2f} Wh',
            f'',
            f'Estimated CO2e emissions           : {self._total_carbon_consumed/1e3:.3f} kg',
            #f'Estimated Peaktime CO2e emissions  : {self._peaktime_carbon_consumed/1e3:.3f} kg',
            f'Average CO2e emissions per job     : {self._avg_carbon_per_job:.3f} g',
            #f'Peaktime CO2e emissions percentage : {self._safe_divide(self._peaktime_carbon_consumed, self._total_carbon_consumed)*100:.3f} %',
            ''
        ]

        if self._site_job_totals:
            summary_lines.extend(self._format_site_job_breakdown('Jobs generated by site', self._site_job_totals, 'jobs'))

        if self._site_job_started_totals:
            summary_lines.extend(self._format_site_job_breakdown('Jobs started by site', self._site_job_started_totals, 'started'))

        if self._site_job_finished_totals:
            summary_lines.extend(self._format_site_job_breakdown('Jobs finished by site', self._site_job_finished_totals, 'finished'))

        return summary_lines


    def _emit_summary_lines(self, summary_lines, print_console=True):
        for line in summary_lines:
            if print_console:
                print(line)
            logger.info(f'[{self._site_id}] {line}')


    def _safe_divide(self, numerator, denominator):
        if denominator == 0:
            return 0.0
        return numerator / denominator


    def _format_site_job_breakdown(self, title, site_totals, unit_label):
        lines = [
            title,
            '-' * len(title),
        ]
        total_jobs = sum(site_totals.values())
        for site_id, job_count in sorted(site_totals.items()):
            percentage = self._safe_divide(job_count, total_jobs) * 100
            lines.append(f'{site_id:<30}: {job_count:>8} {unit_label} ({percentage:5.1f} %)')
        lines.append('')
        return lines


    def _plot_occupancy_and_carbon_intensity(self, output_dir):
        if not self._timestep_timestamps:
            return

        os.makedirs(output_dir, exist_ok=True)

        fig, ax_occupancy = plt.subplots(figsize=(12, 5))
        ax_carbon = ax_occupancy.twinx()

        occupancy_percent = [value * 100 for value in self._timestep_occupancies]
        occupancy_line = ax_occupancy.plot(
            self._timestep_timestamps,
            occupancy_percent,
            color='#1D9E75',
            linewidth=1.8,
            label='Occupancy (%)',
        )
        carbon_line = ax_carbon.plot(
            self._timestep_timestamps,
            self._timestep_carbon_intensities,
            color='#D85A30',
            linewidth=1.6,
            alpha=0.9,
            label='Carbon intensity (gCO2e/kWh)',
        )

        ax_occupancy.set_title(f'Occupancy and carbon intensity over time - {self._site_id}')
        ax_occupancy.set_xlabel('Time')
        ax_occupancy.set_ylabel('Occupancy (%)', color='#1D9E75')
        ax_carbon.set_ylabel('Carbon intensity (gCO2e/kWh)', color='#D85A30')
        ax_occupancy.tick_params(axis='y', labelcolor='#1D9E75')
        ax_carbon.tick_params(axis='y', labelcolor='#D85A30')
        ax_occupancy.xaxis.set_major_formatter(mdates.DateFormatter('%d %H:%M'))
        ax_occupancy.xaxis.set_major_locator(mdates.AutoDateLocator())
        fig.autofmt_xdate()

        lines = occupancy_line + carbon_line
        labels = [line.get_label() for line in lines]
        ax_occupancy.legend(lines, labels, loc='upper left', fontsize=8)
        ax_occupancy.grid(True, axis='both', linestyle='--', alpha=0.25)

        plt.tight_layout()
        plot_path = os.path.join(output_dir, 'occupancy_and_carbon_intensity.png')
        plt.savefig(plot_path, dpi=150)
        plt.close(fig)
        logger.info(f'Occupancy and carbon intensity plot saved to {plot_path}')
