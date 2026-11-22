import numpy as np
import os
from util import Logging
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

logger = Logging.get_logger()

class SubmitImmediately:
    @property
    def held_jobs(self):
        return 0
    
    def submit_job(self, job, current_time, release_target=None):
        # Immediately submit the job to the cluster
        if release_target:
            release_target.submit_job(job)
    def update(self, current_time, current_CI, submit_target=None):
        return []

class SustainableQueue:
    def __init__(self, config, carbon_intensity_data=None):
        self._max_wait_hours = 24
        self._mid_wait_hours = 12
        self._short_wait_hours = 6
        self._max_occupancy = 0.9
        self._waiting_line = []
        self._history = []
        self._released_jobs = 0
        self._release_counts = {
            'Deadline Forced':        0,
            'High Carbon (<75th)':    0,
            'Medium Carbon (<50th)':  0,
            'Low Carbon (<25th)':     0,
        }
        self._total_wait_hours = {
            'Deadline Forced':        0.0,
            'High Carbon (<75th)':    0.0,
            'Medium Carbon (<50th)':  0.0,
            'Low Carbon (<25th)':     0.0,
        }
        self._max_wait_seen = 0.0
        self._held_for_capacity = 0
        self.site_id = config.get("site_id")

        ci_values = []
        if carbon_intensity_data:
            ci_values = [float(row[1]) for row in carbon_intensity_data if row[1] !='']

        if ci_values:
            self._low_ci = float(np.percentile(ci_values, 25))
            self._mid_ci = float(np.percentile(ci_values, 50))
            self._high_ci = float(np.percentile(ci_values, 75))
            logger.info(f"Carbon Intensity thresholds set for {self.site_id}: Low={self._low_ci}, Mid={self._mid_ci}, High={self._high_ci}")
        else:
            self._low_ci = self._mid_ci = self._high_ci = None
            logger.warning(f"No valid carbon intensity data provided for {self.site_id}. Temporal shifting disabled.")

    @property
    def held_jobs(self):
        return len(self._waiting_line)
    
    def submit_job(self, job, current_time, release_target=None):
        #Used to prevent jobs being set directly to cluster
        self._waiting_line.append({'time_arrived': current_time, 'job': job, 'release_target': release_target})
    
    def update(self, current_time, current_CI, submit_target=None):
        self._history.append({'time': current_time, 'ci': current_CI, 'held': len(self._waiting_line)})
        release_now = []
        wait_longer = []

        projected_occupancy = {}

        potential_releases = []
        for item in self._waiting_line:
            hours_waiting = (current_time - item['time_arrived']).total_seconds() / 3600.0
            if hours_waiting >= self._max_wait_hours:
                item['reason'] = 'Deadline Forced'
                potential_releases.append((item, True)) #capactiy exempt 
            elif hours_waiting >= self._mid_wait_hours and current_CI <= self._high_ci:
                item['reason'] = 'High Carbon (<75th)'
                potential_releases.append((item, False))
            elif hours_waiting >= self._short_wait_hours and current_CI <= self._mid_ci:
                item['reason'] = 'Medium Carbon (<50th)'
                potential_releases.append((item, False))
            elif current_CI <= self._low_ci:
                item['reason'] = 'Low Carbon (<25th)'
                potential_releases.append((item, False))
            else:
                wait_longer.append(item)

        potential_releases.sort(key=lambda pair: not pair[1]) #capacity exempt jobs are sorted first

        for item, capacity_exempt in potential_releases:
            target = item.get('release_target') or submit_target
            if target is None:
                release_now.append(item)
                continue

            target_id = id(target)
            if target_id not in projected_occupancy:
                projected_occupancy[target_id] = target.cluster_occupancy()

            job_share = self._job_occupancy_share(item['job'], target)

            if capacity_exempt or projected_occupancy[target_id] + job_share <= self._max_occupancy:
                release_now.append(item)
                projected_occupancy[target_id] += job_share
            else:
                self._held_for_capacity += 1
                wait_longer.append(item)

        self._waiting_line = wait_longer

        for item in release_now:
            hours_waited = (current_time - item['time_arrived']).total_seconds() / 3600.0
            reason = item['reason']
            self._release_counts[reason] += 1
            self._total_wait_hours[reason] += hours_waited
            if hours_waited > self._max_wait_seen:
                self._max_wait_seen = hours_waited
            target = item.get('release_target') or submit_target
            target.submit_job(item['job'])
            self._released_jobs += 1

        return [item['job'] for item in release_now]

    def _job_occupancy_share(self, job, target):
        total_cores = target.get_number_of_cores()
        return job.cores_req / total_cores if total_cores > 0 else 0.0

    
    def write_summary(self, output_dir, site_id=None):
        os.makedirs(output_dir, exist_ok=True)
        total_released = sum(self._release_counts.values())
        still_held = len(self._waiting_line)
        lines=[        
            'Temporal Shifting Summary (SustainableQueue)',
            '============================================',
            '',
            f'Site                  : {site_id or "unknown"}',
            f'CI thresholds         : low={self._low_ci:.1f}, mid={self._mid_ci:.1f}, high={self._high_ci:.1f}',
            f'Max wait (hours)      : {self._max_wait_hours}',
            f'Jobs still held at end: {still_held}',
            f'Total jobs released   : {total_released}',
            '',
            'Release breakdown:',
        ]
        for reason, count in self._release_counts.items():
            if total_released > 0:
                pct = count / total_released * 100
                avg_wait = self._total_wait_hours[reason] / count if count > 0 else 0.0
            else:
                pct = 0.0
                avg_wait = 0.0
            lines.append(f'  {reason:<30}: {count:>6} jobs ({pct:5.1f}%)  '
                        f'avg wait {avg_wait:.1f}h')

        lines += [
            '',
            f'Overall avg wait (released jobs): '
            f'{sum(self._total_wait_hours.values()) / total_released:.1f}h'
            if total_released > 0 else 'Overall avg wait: n/a',
            f'Longest wait seen     : {self._max_wait_seen:.1f}h',
        ]

        filepath = os.path.join(output_dir, 'temporal_shifting_summary.txt')
        with open(filepath, 'w') as f:
            for line in lines:
                f.write(f'{line}\n')

        for line in lines:
            logger.info(line)

        if not self._history:
            return

        timestamps = [h['time'] for h in self._history]
        ci_values  = [h['ci']   for h in self._history]
        queue_lens = [h['held'] for h in self._history]

        fig, ax1 = plt.subplots(figsize=(12, 5))

        ax1.set_xlabel('Simulation time')
        ax1.set_ylabel('Carbon intensity (gCO₂/kWh)', color='tab:orange')
        ax1.plot(timestamps, ci_values, color='tab:orange', linewidth=1.2, label='Carbon intensity')
        ax1.tick_params(axis='y', labelcolor='tab:orange')
        ax1.xaxis.set_major_formatter(mdates.DateFormatter('%d/%m %H:%M'))
        ax1.xaxis.set_major_locator(mdates.AutoDateLocator())

        ax2 = ax1.twinx()
        ax2.set_ylabel('Jobs held in queue', color='tab:blue')
        ax2.fill_between(timestamps, queue_lens, alpha=0.25, color='tab:blue')
        ax2.plot(timestamps, queue_lens, color='tab:blue', linewidth=1.0, label='Queue length')
        ax2.tick_params(axis='y', labelcolor='tab:blue')

        # CI threshold lines
        ax1.axhline(self._low_ci,  color='tab:green',  linestyle='--', linewidth=0.8, label=f'Low CI ({self._low_ci:.0f})')
        ax1.axhline(self._mid_ci,  color='tab:olive',  linestyle='--', linewidth=0.8, label=f'Mid CI ({self._mid_ci:.0f})')
        ax1.axhline(self._high_ci, color='tab:red',    linestyle='--', linewidth=0.8, label=f'High CI ({self._high_ci:.0f})')

        lines_a, labels_a = ax1.get_legend_handles_labels()
        lines_b, labels_b = ax2.get_legend_handles_labels()
        ax1.legend(lines_a + lines_b, labels_a + labels_b, loc='upper right', fontsize=8)

        fig.suptitle(f'Temporal shifting — {site_id or "unknown"}', fontsize=11)
        fig.autofmt_xdate()
        plt.tight_layout()
        plt.savefig(os.path.join(output_dir, 'temporal_shifting_queue.png'), dpi=150)
        plt.close(fig)
        logger.info(f'Temporal shifting plot saved to {output_dir}/temporal_shifting_queue.png')
        if total_released > 0:
            fig2, axes = plt.subplots(1, 2, figsize=(12, 5))
            fig2.suptitle(f'Job release breakdown — {site_id or "unknown"}', fontsize=11)

            reasons = list(self._release_counts.keys())
            counts  = [self._release_counts[r] for r in reasons]
            percentages    = [c / total_released * 100 for c in counts]
            avg_waits = [
                self._total_wait_hours[r] / self._release_counts[r]
                if self._release_counts[r] > 0 else 0.0
                for r in reasons
            ]
            colours = ['tab:red', 'tab:orange', 'tab:olive', 'tab:green']

            # --- left: job counts per release reason ---
            ax = axes[0]
            bars = ax.bar(reasons, counts, color=colours[:len(reasons)])
            ax.set_title('Jobs released per condition')
            ax.set_ylabel('Number of jobs')
            ax.set_xticks(range(len(reasons)))
            ax.set_xticklabels(reasons, rotation=20, ha='right', fontsize=8)
            for bar, pct in zip(bars, percentages):
                ax.text(bar.get_x() + bar.get_width() / 2,
                        bar.get_height() + max(counts) * 0.01,
                        f'{pct:.1f}%', ha='center', va='bottom', fontsize=8)

            # --- right: average wait time per release reason ---
            ax = axes[1]
            bars = ax.bar(reasons, avg_waits, color=colours[:len(reasons)])
            ax.set_title('Average wait time per condition')
            ax.set_ylabel('Hours')
            ax.set_xticks(range(len(reasons)))
            ax.set_xticklabels(reasons, rotation=20, ha='right', fontsize=8)
            for bar, val in zip(bars, avg_waits):
                ax.text(bar.get_x() + bar.get_width() / 2,
                        bar.get_height() + max(avg_waits) * 0.01,
                        f'{val:.1f}h', ha='center', va='bottom', fontsize=8)

            plt.tight_layout()
            plt.savefig(os.path.join(output_dir, 'temporal_shifting_breakdown.png'), dpi=150)
            plt.close(fig2)
            logger.info(f'Release breakdown plot saved to {output_dir}/temporal_shifting_breakdown.png')

class TemporalShiftingFactory:
    def create_temporal_policy(policy_name, site_id=None, carbon_intensity_data=None):
        policies = {
            "sustainable_queue": lambda: SustainableQueue(config={"site_id": site_id}, carbon_intensity_data=carbon_intensity_data),
            "submit_immediately": lambda: SubmitImmediately(),
            "none": lambda: SubmitImmediately(),  # Default to SubmitImmediately if no policy is specified
        }

        try:
            return policies[policy_name]()
        except KeyError:
            raise ValueError(f"Unknown temporal shifting policy: {policy_name}")