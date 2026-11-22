# SPDX-License-Identifier: Apache-2.0
# Copyright 2023-2026 Deutsches Elektronen Synchrotron DESY 
#                     and the University of Glasgow
# Authors: Dwayne Spiteri and Gordon Stewart.
# For more information about rights and fair use please refer to src/Main.py.
# For full detailed and legal infomration please read the LICENSE and NOTICE
#    files in the main directory 
# ===========================================================================

import json
import sys
import os
from datetime import datetime, timedelta

from dataclasses import dataclass
from cluster.Cluster import Cluster
from cluster.ClusterLoader import load_cluster_inventory
from datalogger.DataLogger import DataLogger
from jobs.JobScheduler import JobScheduler
from jobs.TemporalShifting import TemporalShiftingFactory
from globalqueue.GlobalJobQueue import GlobalJobQueue
from simulation.Time import SimulationTime
from util import Logging
from globalqueue.RoutingPolicies import RoutingPolicyFactory


logger = Logging.get_logger()

@dataclass
class Site:
    site_id: str
    cluster: Cluster
    data_logger: DataLogger
    run_dir: str
    ci_threshold: float
    ci_segment_start: str
    ci_segment_end: str
    job_scheduler: JobScheduler = None
    finished: bool = False
    finish_reason: str = None
    finish_sim_seconds: float = None


class Simulation():

    @staticmethod
    def baseline_config(config, cluster_configs, run_dir):
        baseline_run_dir = os.path.join(run_dir, 'baseline')
        os.makedirs(baseline_run_dir, exist_ok=True)

        baseline_config = dict(config)
        baseline_config["output"] = dict(config["output"])
        baseline_config["output"]["run_dir"] = baseline_run_dir
        baseline_config["Simulation"] = dict(config["Simulation"])
        baseline_config["Simulation"]["savings_policy"] = "none"
        baseline_config["output"]["verbosity"] = "low"
        baseline_config["Simulation"]["routing"] = {"policy": "origin_site"}

        baseline_cluster_configs = [{**cluster_config, "savings_policy": "none", "temporal_shifting": {"policy": "submit_immediately"}}
                                     for cluster_config in cluster_configs]
        return baseline_config, baseline_cluster_configs

    def __init__(self, config, cluster_configs):
        self._config = config
        self.desiredStartTime = config["Simulation"]["desired_starttime"] # STEVE '2018-01-01 00:30' : Starts at the simulation at a set time can be set to any time you wish in the format '2024-01-12 15:00'
        self._simulation_time = SimulationTime(config, self.desiredStartTime) #If you want this to be set to the current time, set desiredStartTime to None
        self._simulation_length = config["Simulation"]["simulation_length"] # Desired maximum length of the simulation in seconds. (For one year 365*24*3600)
        self._simulation_time._timestep_seconds = config["Simulation"]["timestep"] # Simulation time step in seconds. #Steve was using 200
        # Finds the half-hour time segment to which the start of the simulation belongs and the one after the end time.
        self._simulation_starting_segment = self._simulation_time.find_hh_segment(self._simulation_time._time)
        self._simulation_maxfinal_segment = self._simulation_time.find_hh_segment(self._simulation_time._time + timedelta(seconds=self._simulation_length), 'next')

        self.routing_policy_name = config["Simulation"]["routing"]["policy"]
        self._verbosity = config["output"]["verbosity"]
        self._run_dir = config["output"]["run_dir"]
        self._finished = False
        self._jobdescript = config["output"]["run_label"]
        self._finish_reason = None
        self._global_logger = None
        self._simtottime = None
               
        self._site_list = []
        for index, cluster_config in enumerate(cluster_configs, start=1):
            site = self._build_site(cluster_config, index)
            self._site_list.append(site)

        routing_policy = RoutingPolicyFactory.create_routing_policy(
            self.routing_policy_name,
            simulation_time=self._simulation_time,
            routing_config=config["Simulation"].get("routing", {}),
        )
        self._global_scheduler = GlobalJobQueue(routing_policy)

        for site, cluster_config in zip(self._site_list, cluster_configs):
            self._attach_job_scheduler(site, cluster_config)
        self._global_scheduler.set_local_schedulers({site.site_id: site.job_scheduler for site in self._site_list})
        self._global_scheduler.update()

        if self._verbosity in ["low", "medium", "high"]:
            for site, cluster_config in zip(self._site_list, cluster_configs):
                simulation_parameters = self._get_simulation_parameters(site, cluster_config)
                site.data_logger.set_simulation_parameters(simulation_parameters)
                simulation_parameters_text = self._format_simulation_parameters(simulation_parameters)
                logger.info('Created cluster %s with parameters:\n%s', site.site_id, simulation_parameters_text)
                self._write_simulation_parameters(site,simulation_parameters_text)
        print(f'Simulation Started. Good Luck')

        for site in self._site_list:
            # Apply one-time policies before the first simulation step.
            if site.cluster._energy_saving_try == 'cd':
                for worker_node in site.cluster._worker_nodes:
                    worker_node.clock_down()
            if site.cluster._energy_saving_try == 'cdcd':
                for worker_node in site.cluster._worker_nodes:
                    worker_node.clock_down()
                    worker_node.clock_down()


    def _build_site(self, cluster_config, index):
        site_id = cluster_config.get("site_id", cluster_config.get("site_id", f"cluster_{index}"))
        cluster_run_dir = os.path.join(self._run_dir, site_id)
        os.makedirs(cluster_run_dir, exist_ok=True )
        cluster_config = dict(cluster_config)  # Make a copy to avoid mutating the original
        cluster_config["output"] = dict(cluster_config.get("output", {}))  # Ensure output is a dict
        cluster_config["output"]["run_dir"] = cluster_run_dir
        cluster_config["output"]["verbosity"] = self._verbosity
        cluster_config["site_id"] = site_id

        with open(os.path.join(cluster_run_dir, 'cluster_config.json'), 'w') as outfile:
            json.dump(cluster_config, outfile, indent=4)
            outfile.write('\n')
        savings_policy = cluster_config.get("savings_policy", self._config["Simulation"].get("savings_policy", "none"))


        # Importing average data about the Carbon Intensity of the whole UK grid for the maxumum duration of the simulation.
        # Carbon Intensity data is in gCO2/kWh.
        if self._verbosity in ["medium", "high"]:
            logger.info('Loading in Carbon Intensity Data for cluster %s', site_id)
        datapath = cluster_config["carbon_intensity"]["folder"]
        datafile = cluster_config["carbon_intensity"]["filename"]
        #Convert start and end segment datetimes to format found in datafile. 
        datastart_str = datetime.strftime(self._simulation_starting_segment, '%Y-%m-%dT%H:%M:%S')
        datafinal_str = datetime.strftime(self._simulation_maxfinal_segment, '%Y-%m-%dT%H:%M:%S')
        
        linesofimport = []
        datarequired  = False
        with open(datapath+datafile) as file:
            for line in file.read().splitlines():
                line = line.split(',')

                if line[0] == datastart_str: # Ignores all lines before the one you want.
                    datarequired = True
                elif line[0] == datafinal_str: # Exit file after you have reached the end time value.
                    datarequired = False
                
                if datarequired == True: #Import data when you have found that date you want.
                    if line[1] == '': # If there is data missing
                        print("You are missing forecast CI data for cluster " + site_id + " for the time segment: " + line[0])
                        sys.exit
                    if line[2] == '': # If there is data missing
                        print("You are missing actual CI data for cluster " + site_id + " for the time segment: " + line[0])
                        sys.exit
                    linesofimport.append(line)    
                    
        CIntendata = linesofimport
        CIThresholdValue = cluster_config["carbon_intensity"]["high_CI_threshold"] #  200gCO2e/kWh - This roughly corresponds to what is labelled 'high' in the UK. For Germany I'll put this at 400



        # Create the cluster {WorkerNode[unstantiated WN of type WorkerNode]:amount[integer]}
        # Types of nodes you can currently use are {WorkerNode_h16, WorkerNode_h17, WorkerNode_d20, WorkerNode_d21, WorkerNode_d22, WorkerNode_a23},
        # the details of which can be accessed in node().system, node().cpu, and node().year.
        # You now pass the carbon data you need to estimate the amount of carbon used (manditory)
        # and a flag to set the option of how you will change the operation of the servers during runtime (none, cd1721, cdcd1721 and highforecast) (optional)

        # EXAMPLES
        # Glasgow Uni 
        # self._cluster = Cluster(self._simulation_time, {WorkerNode_h16:13,WorkerNode_h17:43, WorkerNode_d20:40, WorkerNode_d21:32, WorkerNode_d22:36}, self._CIntendata, 'none')
        # self._cluster = Cluster(self._simulation_time, {WorkerNode_d20:40, WorkerNode_d21:32, WorkerNode_d22:36, WorkerNode_d24:17}, self._CIntendata, 'none') # Future 1
        # self._cluster = Cluster(self._simulation_time, {WorkerNode_d20:40, WorkerNode_d21:32, WorkerNode_d22:36, WorkerNode_a24:17}, self._CIntendata, 'none') # Future 2
        # DESY

        inventory = load_cluster_inventory(
            cluster_config["cluster"]["inventory_csv"],
            cluster_config["cluster"]["frequency_csv"],
            cluster_name=cluster_config["cluster"]["cluster_name"],
            strict=cluster_config["cluster"]["strict"],
        )

        cluster = Cluster(cluster_config,
                                self._simulation_time,
                                inventory,
                                CIntendata,
                                cluster_config["savings_policy"],
                                CIThresholdValue) # Starting DESY
        print('')
        print('Site ID: ' + site_id)
        print('Cluster: ', end='')
        for node, cores in cluster._worker_node_inventory.items():
            n = node(self._simulation_time)
            print(n.hostname + ': ' + str(cores) + ' ', end='')
        print()
        print('Energy saving try: ' + cluster._energy_saving_try)
        print('CIThresholdValue: ' + str(CIThresholdValue))
        
        # Class to record statistics
        datalogger = DataLogger(cluster_config)
        cluster.set_datalogger_handlers(datalogger.job_submit, 
                                              datalogger.job_start, 
                                              datalogger.job_finish,
                                              datalogger.energy_and_carbon_consumed, 
                                              #datalogger.peaktime_energy_and_carbon_consumed,
                                              datalogger.sum_occupancy,
                                              datalogger.record_timestep_metrics )

        # Create a job scheduler to initially seed the cluster with jobs and provide jobs on a regular notice. Needs to know about this cluster
        # Format for initial jobs is a dictionary of {'VO1':jobs, 'VO2':jobs, [...]}
        # Format for regular jobs is a list  of lists of a dictionary of [[{'VO1':jobs per X seconds, 'VO2':jobs per X seconds, [...]}, X], [....] ]
        # self._jobScheduler = JobScheduler(self._simulation_time, self._cluster, {'GridPP':10} , None)
      

        return Site(
            site_id=site_id,
            cluster=cluster,
            data_logger=datalogger,
            run_dir=cluster_run_dir,
            ci_threshold=CIThresholdValue,
            ci_segment_start=datastart_str,
            ci_segment_end=datafinal_str,
        )

    def _attach_job_scheduler(self, site, cluster_config):
        if cluster_config["jobs"]["regular_incoming_mix"] == {}:
            jobs_refill = None
        else:
            jobs_refill = [[cluster_config["jobs"]["regular_incoming_mix"], cluster_config["jobs"]["incoming_timestep"]]]

        temporal_shifting_cfg = cluster_config.get("temporal_shifting", {})
        temporal_policy_name = temporal_shifting_cfg.get("policy", "none")
        temporal_policy = TemporalShiftingFactory.create_temporal_policy(
            policy_name=temporal_policy_name,
            site_id=site.site_id,
            carbon_intensity_data=site.cluster._carbondata,
        )

        job_scheduler = JobScheduler(self._simulation_time, site.cluster, cluster_config["jobs"]["initial_mix"],jobs_refill,
                                     site_id=site.site_id, job_router=self._global_scheduler, temporal_shifter=temporal_policy)
        jobs_summary = ''
        for vo, jobs in job_scheduler._initial_job_mix.items():
            jobs_summary += f'{vo}: {jobs} '
        if job_scheduler._regular_incoming_jobs:
            jobs_summary += 'then '
            for l1 in job_scheduler._regular_incoming_jobs:
                vos = l1[0]
                secs = l1[1]
                for vo, jobs in vos.items():
                    jobs_summary += f'{vo}: {jobs} '
                jobs_summary += f'per {secs/3600} hours '
        logger.info('Jobs: %s', jobs_summary)
        site.job_scheduler = job_scheduler    
                

    def _finalise(self, reason):
        #initiates all final logging once all sites have finished
        self._finished = True
        self._finish_reason = reason
        self._simtottime = self._simulation_time.get_current_datetime() - self._simulation_time.get_start_datetime()
        realtottime = datetime.now() - self._simulation_time.get_origin_datetime()
        for site in self._site_list:
            site.data_logger.set_jobs_generated(site.job_scheduler._total_jobs_generated)
            site.data_logger.print_summary(True, self._jobdescript, site.finish_sim_seconds, self._simulation_time.get_timestep(), 
                                           realtottime.total_seconds(), print_console = False)

            logger.info(f"Site {site.site_id} total jobs generated: {site.job_scheduler._total_jobs_generated}")
            dl = site.data_logger
            logger.info(f"Site {site.site_id} raw stats — "
                        f"energy: {dl._total_energy_consumed}, "
                        f"cpu_time: {dl._cumulative_cpu_time}, "
                        f"jobs_finished: {dl._jobs_finished}")
        self._global_logger = self._build_global_datalogger()
        self._global_logger.print_summary(True, self._jobdescript, self._simtottime.total_seconds(),
                                     self._simulation_time.get_timestep(), realtottime.total_seconds(),
                                     summary_dir=self._run_dir, print_console = True)
        self._global_scheduler.write_summary(self._run_dir)
        logger.info(f"Finish reason: {reason}")
        for site in self._site_list:
            shifter=site.job_scheduler._temporal_shifter
            logger.info(f'Site {site.site_id} temporal shifter: {type(shifter).__name__} has summary:{hasattr(shifter, "write_summary")}')
            if hasattr(shifter, 'write_summary'):
                shifter.write_summary(site.run_dir, site_id=site.site_id)
        if reason == 'no_jobs':
            if self._verbosity in ["medium", "high"]:
                logger.info(f'No more jobs across all clusters!')
                logger.info(f'Ending simulation at {self._simulation_time.get_current_datetime()}')
        elif reason == 'time_limit':
            if self._verbosity in ["medium", "high"]:
                logger.info(f'You have been running for a set amount of time! Time to stop')
                logger.info(f'Ending simulation at {self._simulation_time.get_current_datetime()}')


    def _build_global_datalogger(self):
        global_logger = DataLogger(self._config)
        global_logger._site_id = 'all_clusters'

        if not self._site_list:
            return global_logger

        dataloggers = [site.data_logger for site in self._site_list]
        global_logger._jobs_submitted = sum(datalogger._jobs_submitted for datalogger in dataloggers)
        global_logger._jobs_generated = sum(datalogger._jobs_generated for datalogger in dataloggers)
        global_logger._jobs_started = sum(datalogger._jobs_started for datalogger in dataloggers)
        global_logger._jobs_finished = sum(datalogger._jobs_finished for datalogger in dataloggers)
        global_logger._jobs_failed = sum(datalogger._jobs_failed for datalogger in dataloggers)
        global_logger._jobs_aborted = sum(datalogger._jobs_aborted for datalogger in dataloggers)
        global_logger._jobs_total_cores_used = sum(datalogger._jobs_total_cores_used for datalogger in dataloggers)
        global_logger._cumulative_cpu_time = sum(datalogger._cumulative_cpu_time for datalogger in dataloggers)
        global_logger._cumulative_wallclock_time = sum(datalogger._cumulative_wallclock_time for datalogger in dataloggers)
        global_logger._cumulative_wait_time = sum(datalogger._cumulative_wait_time for datalogger in dataloggers)
        global_logger._total_energy_consumed = sum(datalogger._total_energy_consumed for datalogger in dataloggers)
        global_logger._total_carbon_consumed = sum(datalogger._total_carbon_consumed for datalogger in dataloggers)
        global_logger._sum_occupancy = sum(datalogger._sum_occupancy for datalogger in dataloggers) / len(dataloggers)
        global_logger._site_job_totals = {
            site.site_id: site.job_scheduler._total_jobs_generated
            for site in self._site_list
        }
        global_logger._site_job_started_totals = {
            site.site_id: site.data_logger._jobs_started
            for site in self._site_list
        }
        global_logger._site_job_finished_totals = {
            site.site_id: site.data_logger._jobs_finished
            for site in self._site_list
        }
        return global_logger


    def future_jobs_expected(self):
        return any(site.job_scheduler._regular_incoming_jobs for site in self._site_list)

    def _write_simulation_parameters(self, site, simulation_parameters):
        run_dir = site.data_logger._run_dir
        if run_dir:
            with open(os.path.join(run_dir, 'parameters.txt'), 'w') as outfile:
                outfile.write(simulation_parameters)
                outfile.write('\n')

    def _get_simulation_parameters(self, site, cluster_config):
        cluster_inventory = {}
        for node, quantity in site.cluster._worker_node_inventory.items():
            worker_node = node(self._simulation_time)
            cluster_inventory[worker_node.hostname] = quantity

        regular_jobs = []
        if site.job_scheduler._regular_incoming_jobs:
            regular_jobs = [
                {
                    "job_mix": job_mix,
                    "incoming_timestep_seconds": secs,
                }
                for job_mix, secs in site.job_scheduler._regular_incoming_jobs
            ]

        return {
            "site_id": site.site_id,
            "start_time": str(self._simulation_time.get_start_datetime()),
            "max_end_time": str(self._simulation_time.get_start_datetime() + timedelta(seconds=self._simulation_length)),
            "simulation_length_seconds": self._simulation_length,
            "timestep_seconds": self._simulation_time.get_timestep(),
            "savings_policy": site.cluster._energy_saving_try,
            "carbon_intensity": {
                "file": f'{cluster_config["carbon_intensity"]["folder"]}{cluster_config["carbon_intensity"]["filename"]}',
                "segments": {
                    "start": site.ci_segment_start,
                    "end": site.ci_segment_end,
                },
                "high_CI_threshold": site.ci_threshold,
            },
            "cluster": {
                "worker_nodes": site.cluster.get_number_of_nodes(),
                "worker_cores": site.cluster.get_number_of_cores(),
                "worker_node_inventory": cluster_inventory,
            },
            "jobs": {
                "initial": site.job_scheduler._initial_job_mix,
                "regular_incoming": regular_jobs,
            },
        }


    def _format_simulation_parameters(self, simulation_parameters):
        carbon_intensity = simulation_parameters["carbon_intensity"]
        cluster = simulation_parameters["cluster"]
        jobs = simulation_parameters["jobs"]
        regular_jobs = 'none'
        if jobs["regular_incoming"]:
            regular_jobs = ', '.join(
                f'{vo}: {count} per {regular_job["incoming_timestep_seconds"]} seconds'
                for regular_job in jobs["regular_incoming"]
                for vo, count in regular_job["job_mix"].items()
            )

        return '\n'.join([
            f'Site ID: {simulation_parameters["site_id"]}',
            f'  start_time: {simulation_parameters["start_time"]}',
            f'  max_end_time: {simulation_parameters["max_end_time"]}',
            f'  simulation_length_seconds: {simulation_parameters["simulation_length_seconds"]}',
            f'  timestep_seconds: {simulation_parameters["timestep_seconds"]}',
            f'  savings_policy: {simulation_parameters["savings_policy"]}',
            f'  carbon_intensity_file: {carbon_intensity["file"]}',
            f'  carbon_intensity_segments: {carbon_intensity["segments"]["start"]} to {carbon_intensity["segments"]["end"]}',
            f'  high_CI_threshold: {carbon_intensity["high_CI_threshold"]}',
            f'  worker_nodes: {cluster["worker_nodes"]}',
            f'  worker_cores: {cluster["worker_cores"]}',
            f'  worker_node_inventory: {self._format_job_mix(cluster["worker_node_inventory"])}',
            f'  initial_jobs: {self._format_job_mix(jobs["initial"])}',
            f'  regular_incoming_jobs: {regular_jobs}',
        ])


    def _format_job_mix(self, job_mix):
        if not job_mix:
            return 'none'
        return ', '.join(f'{vo}: {jobs}' for vo, jobs in job_mix.items())

    def compare_to_baseline(self, baseline_simulation, run_seed):
        return self._global_logger.comparison(baseline_simulation._global_logger, run_seed,
                                                       self._simtottime.total_seconds(), baseline_simulation._simtottime.total_seconds())

    def print_comparison(self, comparison, run_dir, print_console=True):
        self._global_logger.print_comparison(comparison, run_dir, print_console=print_console)

       
    def start(self):
        while True:
            simtottime  = self._simulation_time.get_current_datetime() - self._simulation_time.get_start_datetime() # Simulated Time
            for site in self._site_list:
                if site.finished:
                    continue
            # Update the state of the scheduler
                site.job_scheduler.update()
            # Update the state of the cluster
            self._global_scheduler.update()

            for site in self._site_list:
                if site.finished:
                    continue
                site.cluster.update()
                # First end condition: When we have no jobs running and no more jobs to submit. Flag will be activate in the cluster update.
                if site.cluster._mission_accomplished == True:
                    if (not self._global_scheduler.has_jobs() and not self.future_jobs_expected() and
                    not site.job_scheduler._temporal_shifter.held_jobs>0):
                        site.finished = True
                        site.finish_reason = 'no_jobs'
                        site.finish_sim_seconds = simtottime.total_seconds()

            # Second end condition: When the configured simulation length has elapsed.
            if simtottime.total_seconds() >= self._simulation_length:
                for site in self._site_list:
                    if not site.finished:
                        site.finished = True
                        site.finish_reason = 'time_limit'
                        site.finish_sim_seconds = simtottime.total_seconds()

            if all(site.finished for site in self._site_list):
                self._finalise('all_clusters_finished')
                print(f'Simulation Finished. Check logs directory for output')
                return
            
            self._simulation_time.advance()             
            
