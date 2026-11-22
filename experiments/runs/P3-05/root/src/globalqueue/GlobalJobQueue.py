import json
import os
from collections import defaultdict, deque
from util import Logging

logger = Logging.get_logger()

class GlobalJobQueue:

    _MAX_ROUTING_LOGS = 20
    def __init__(self, routing_policy):
        self._global_queue = deque()
        self._site_list = {}
        self._jobs_routed_logged = 0
        self._routed_counts = defaultdict(int)
        self._executed_at_origin = defaultdict(int)
        self._moved_to_another_site = defaultdict(int)
        self._jobs_routed = 0
        self._routing_policy = routing_policy

    def set_local_schedulers(self, site_list):
        self._site_list = site_list

    def submit_job(self, job):
        self._global_queue.append(job)
        return job

    def get_jobs(self):
        return list(self._global_queue)

    def has_jobs(self):
        return bool(self._global_queue)

    def get_routing_counts(self):
        return dict(self._routed_counts)

    def update(self):
        if hasattr(self._routing_policy, "prepare"):
            self._routing_policy.prepare(self._site_list)
        while self.has_jobs():
            job = self._global_queue.popleft()
            if getattr(job, 'force_origin', False):
                destination = self._site_list.get(job.origin_site)
                if destination is None:
                    raise ValueError(f"Force origin: No cluster returned for job {job.name} with origin_site {getattr(job, 'origin_site', None)}")
            else:
                destination = self._routing_policy.choose_scheduler(job, self._site_list)
                if destination is None:
                    raise ValueError(f"Routing policy: No cluster returned for job {job.name} with origin_site {getattr(job, 'origin_site', None)}")
            origin_site = getattr(job, "origin_site", None)
            destination_site_id = getattr(destination, "site_id", None)
            self._routed_counts[job.origin_site] += 1
            self._jobs_routed += 1

            if origin_site == destination_site_id:
                self._executed_at_origin[origin_site] += 1
            else:
                self._moved_to_another_site[origin_site] += 1

            if self._jobs_routed_logged < self._MAX_ROUTING_LOGS:
                logger.info(f"Routed job %s (origin_site=%s) to cluster %s", job.name, getattr(job, "origin_site", None), getattr(destination, "site_id", None))
                self._jobs_routed_logged += 1
                if self._jobs_routed_logged >= self._MAX_ROUTING_LOGS:
                    logger.info("Maximum number of job routing logs reached. Further routing logs will be suppressed.")


            destination.submit_job(job)

    def get_origin_execution_counts(self):
        return dict(self._executed_at_origin)

    def get_moved_to_another_site_counts(self):
        return dict(self._moved_to_another_site)      

    def write_summary(self, output_dir):
        origin_counts = self.get_origin_execution_counts()
        moved_counts = self.get_moved_to_another_site_counts()
        os.makedirs(output_dir, exist_ok=True)
        known_sites = list(self._site_list.keys())
        counts = self.get_routing_counts()
        lines = [
            'Routing Summary',
            '================',
            '',
            f'Routing policy      : {self._routing_policy.__class__.__name__}',
            f'Known sites          : {", ".join(known_sites) if known_sites else "none"}',
            f'Total jobs routed    : {self._jobs_routed}',
            '',
        ]
        for site_id in known_sites:
            routed = counts.get(site_id, 0)
            local = origin_counts.get(site_id, 0)
            moved = moved_counts.get(site_id, 0)
            lines.append(f'  {site_id}:')
            lines.append(f'      Jobs routed           : {routed}')
            lines.append(f'      Executed locally      : {local}')
            lines.append(f'      Moved to another site : {moved}')
            lines.append('')

        with open(os.path.join(output_dir, 'routing_summary.txt'), 'w') as outfile:
            for line in lines:
                outfile.write(f'{line}\n')
 
        for line in lines:
            logger.info(line)
