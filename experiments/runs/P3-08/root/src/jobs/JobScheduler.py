# SPDX-License-Identifier: Apache-2.0
# Copyright 2023-2026 Deutsches Elektronen Synchrotron DESY 
#                     and the University of Glasgow
# Authors: Dwayne Spiteri and Gordon Stewart.
# For more information about rights and fair use please refer to src/Main.py.
# For full detailed and legal infomration please read the LICENSE and NOTICE
#    files in the main directory 
# ===========================================================================

from jobs.VOJobFactory import VOJobFactory, GridPPJobFactory, ATLASJobFactory, LHCbJobFactory
from jobs.TemporalShifting import SubmitImmediately
from util import Logging

logger = Logging.get_logger()

class JobScheduler():
    @property
    def site_id(self):
        return self._site_id
    
    def __init__(self, simulation_time, cluster_to_submit_job_to, initial_job_mix={'ATLAS':10,'LHCb':5},
                  regular_incoming_jobs=[[{'ATLAS':1,'LHCb':2},3600]], site_id=None, job_router=None, temporal_shifter=None):
        self._simulation_time = simulation_time
        self._cluster = cluster_to_submit_job_to
        self._site_id = site_id
        
        self._submit_target = job_router if job_router is not None else self._cluster
        # Load in the job mixed
        self._initial_job_mix = initial_job_mix
        self._regular_incoming_jobs = regular_incoming_jobs
        self._regular_incoming_last_cycle = []

        self._total_jobs_generated = sum(self._initial_job_mix.values()) if self._initial_job_mix else 0

        self._temporal_shifter = temporal_shifter if temporal_shifter is not None else SubmitImmediately()
        logger.info(f"JobScheduler for site {self._site_id} initialized with temporal shifter: {type(self._temporal_shifter).__name__}")
        # Create the job factories
        self._basic_job     = VOJobFactory('VO-Basic-', origin_site=self._site_id)
        self._gridpp_job    = GridPPJobFactory('GridPP-', origin_site=self._site_id)
        self._atlas_prod    = ATLASJobFactory('ATLAS-Prod-', origin_site=self._site_id)
        self._lhcb_prod     = LHCbJobFactory('LHCb-Prod-', origin_site=self._site_id)

        self._gridpp_hourly = GridPPJobFactory('GridPP-Hourly', origin_site=self._site_id)
        self._atlas_hourly  = ATLASJobFactory('ATLAS-Hourly-', origin_site=self._site_id)
        self._lhcb_hourly   = LHCbJobFactory('LHCb-Hourly-', origin_site=self._site_id)

        # Seed the cluster with initial jobs
        # Format for initial jobs is a dictionary of {'VO1':jobs, 'VO2':jobs, [...]}
        if self._initial_job_mix != None:
            for VO, amount in self._initial_job_mix.items():
                for _ in range(amount):
                    if VO == 'ATLAS':
                        job = self._atlas_prod.create_job()
                    elif VO == 'LHCb':
                        job = self._lhcb_prod.create_job()
                    elif VO == 'GridPP':
                        job = self._gridpp_job.create_job()
                    else:
                        job = self._basic_job.create_job()
                    job.submit_time = self._simulation_time.get_current_datetime()
                    job.force_origin = True
                    self._submit_target.submit_job(job)        

        if self._regular_incoming_jobs:
            self._regular_incoming_last_cycle = [0 for _ in self._regular_incoming_jobs]

    def submit_job(self, job):
        current_time = self._simulation_time.get_current_datetime()
        self._temporal_shifter.submit_job(job, current_time, release_target=self._cluster)

    def get_carbon_intensity(self):
        return self._cluster.get_current_carbon_intensity()

    def has_running_jobs(self):
        return self._cluster.has_running_jobs()

    def has_queued_jobs(self):
        return self._cluster.has_queued_jobs()

    def cluster_occupancy(self):
        return self._cluster.cluster_occupancy()

    def get_number_of_cores(self):
        return self._cluster.get_number_of_cores()

    def update(self):
        # Jobs to be submitted while the simulation is ongoing
        # Format for regular jobs is a tuple of a dictionary of [{'VO1':jobs per X seconds, 'VO2':jobs per X seconds, [...]}, X]
        current_time = self._simulation_time.get_current_datetime()
        current_CI = self._cluster.get_current_carbon_intensity()
        self._temporal_shifter.update(current_time, current_CI, submit_target=self._cluster)
        
        if self._regular_incoming_jobs != None:
            for index, job_schedule in enumerate(self._regular_incoming_jobs):
                if len(job_schedule) != 2:
                    raise TypeError("The type of list in this list of lists should be a tuple of [ {VO : jobs_per_cycle}, cycle_in_sec ]")

                dict_VO_jobs_per_cycle = job_schedule[0]
                cycle = job_schedule[1]
                # Check to see if multiples of cycle number number of seconds have gone by.
                timediff = self._simulation_time.get_current_datetime() - self._simulation_time.get_start_datetime()
                cyclespassed = int(timediff.total_seconds() // cycle)
                
                if cyclespassed <= self._regular_incoming_last_cycle[index]:
                    continue

                self._regular_incoming_last_cycle[index] = cyclespassed
                if cyclespassed > 0:
                    for VO, amount in dict_VO_jobs_per_cycle.items():
                        for _ in range(amount):
                            if VO == 'ATLAS':
                                job = self._atlas_hourly.create_job()
                            elif VO == 'LHCb':
                                job = self._lhcb_hourly.create_job()
                            elif VO == 'GridPP':
                                job = self._gridpp_hourly.create_job()
                            else:
                                job = self._basic_job.create_job()
                            job.submit_time = current_time
                            self._submit_target.submit_job(job)
                        self._total_jobs_generated += amount  