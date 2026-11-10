#!/usr/bin/env python3

# SPDX-License-Identifier: Apache-2.0
# ========================================================================
# Copyright 2023-2026 Deutsches Elektronen Synchrotron DESY 
#                     and the University of Glasgow
# Authors: Dwayne Spiteri and Gordon Stewart.
# 
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
# 
#     http://www.apache.org/licenses/LICENSE-2.0
# 
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
# The main repository houses LICENSE and NOTICE files for your infromation 
# ========================================================================

import contextlib
import sys

from simulation.Simulation import Simulation
from util import Logging
import json
import os
import logging
import numpy as np
import random


# Main.py - entry point for a paired ORACLE-D run.
#   1. Generates a random seed.
#   2. Loads configs/config.json and the individual site configurations it lists.
#      The default config simulates one week with 600-second (10-minute) timesteps and enables three
#      sites: Scotland (Scot.json), University of Manchester (UoM.json) and Rutherford Appleton
#      Laboratory (RAL.json).
#   3. Runs a baseline simulation using immediate job submission and origin-site routing.
#   4. Runs a policy simulation using the configured scheduling settings.
#   5. Uses the same random seed for both runs so they generate comparable (identical) workloads.
#   6. Compares the baseline and policy results, then writes a carbon-savings summary.
logger = Logging.get_logger()

if __name__ == '__main__':
    
    # Generate this run's random seed. It is reused for both the baseline and policy simulations and is
    # written to carbon_savings_summary.txt.
    seed_override = os.environ.get("ORACLE_SEED")
    run_seed = (
        int(seed_override)
        if seed_override is not None
        else random.randint(0, 2**32 - 1)
    )

    logger.info(f"Run seed: {run_seed}")

    project_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    # Load the main configuration (simulation window, timestep, routing policy, list of site files, output).
    with open(project_dir + '/configs/config.json') as f:
        config = json.load(f)

    output_cfg = config.setdefault("output", {})
    verbosity_raw = output_cfg.get("verbosity")
    config["output"]["verbosity"] = Logging.normalize_verbosity(verbosity_raw)

    if config["output"].get("debug", False):
        logging_level = logging.DEBUG
    else:
        logging_level = logging.INFO

    run_dir = Logging.create_run_directory(config)
    with open(os.path.join(run_dir, 'multi_site_config.json'), 'w') as outfile:
        json.dump(config, outfile, indent=4)
        outfile.write('\n')

    Logging.configure_logger(logger, logging_level, run_dir)
    logger.info(f'Writing run output to {run_dir}')

    if verbosity_raw != config["output"]["verbosity"]:
        logger.warning(f"Invalid verbosity value '{verbosity_raw}', defaulting to 'high'")


    # Load the individual site configurations (cluster hardware, carbon-intensity file, jobs, temporal policy).
    config_dir = os.path.dirname(os.path.abspath(os.path.join(project_dir, 'configs/config.json')))
    resolved_sites = []
    for site_path in config["sites"]:
        with open(os.path.join(config_dir, site_path)) as site_file:
            resolved_sites.append(json.load(site_file))
    config["sites"] = resolved_sites
 
    # Reshape each site into the per-cluster config dict Simulation expects.
    cluster_configs = []
    for site in config["sites"]:
        cluster_configs.append({
            "site_id": site["site_id"],
            "cluster": site["cluster"],
            "carbon_intensity": site["carbon_intensity"],
            "jobs": site["jobs"],
            "savings_policy": site.get("savings_policy", "none"),
            "temporal_shifting": site.get("temporal_shifting", config["Simulation"].get("temporal_shifting", {"policy": "none"}))
        })
    # Baseline = the same sites and workload, but origin-site routing and immediate job submission.
    baseline_config, baseline_cluster_configs = Simulation.baseline_config(config, cluster_configs, run_dir)


    # Run the baseline simulation (its console output is suppressed).
    logger.info("Running baseline simulation with no carbon savings policy") 
    print(f"Running baseline simulation with no carbon savings policy")
    random.seed(run_seed)
    np.random.seed(run_seed)
    with open(os.devnull, 'w') as devnull:
        with contextlib.redirect_stdout(devnull):
            baseline_sim = Simulation(baseline_config, baseline_cluster_configs)
            baseline_sim.start()

    # Run the policy simulation with the configured routing / temporal-shifting settings. Re-seeding with the
    # same seed reproduces the baseline's job stream, so the two runs are comparable.
    logger.info("Running actual simulation")
    print(f"Running actual simulation")
    random.seed(run_seed)
    np.random.seed(run_seed)
    sim = Simulation(config, cluster_configs)
    sim.start()

    # Compare the policy run with the baseline and write carbon_savings_summary.txt to the run directory.
    comparison = sim.compare_to_baseline(baseline_sim, run_seed)
    sim.print_comparison(comparison, run_dir)
    print(f'Simulation Finished. Check logs directory for output')

    sys.exit(0)
    #sim2 = Simulation('eveningclock') # Clock down the node at 5pm and up at 9pm
    #sim2.start()
