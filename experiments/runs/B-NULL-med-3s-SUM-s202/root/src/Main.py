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


logger = Logging.get_logger()

if __name__ == '__main__':
    
    run_seed = random.randint(0, 2**32 - 1)
    logger.info(f"Run seed: {run_seed}")

    project_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
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
    baseline_config, baseline_cluster_configs = Simulation.baseline_config(config, cluster_configs, run_dir)


    logger.info("Running baseline simulation with no carbon savings policy") 
    print(f"Running baseline simulation with no carbon savings policy")
    random.seed(run_seed)
    np.random.seed(run_seed)
    with open(os.devnull, 'w') as devnull:
        with contextlib.redirect_stdout(devnull):
            baseline_sim = Simulation(baseline_config, baseline_cluster_configs)
            baseline_sim.start()

    logger.info("Running actual simulation")
    print(f"Running actual simulation")
    random.seed(run_seed)
    np.random.seed(run_seed)
    sim = Simulation(config, cluster_configs)
    sim.start()

    comparison = sim.compare_to_baseline(baseline_sim, run_seed)
    sim.print_comparison(comparison, run_dir)
    print(f'Simulation Finished. Check logs directory for output')

    sys.exit(0)
    #sim2 = Simulation('eveningclock') # Clock down the node at 5pm and up at 9pm
    #sim2.start()
