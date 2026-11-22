from cluster.Cluster import Cluster
from jobs.JobScheduler import JobScheduler
from util import Logging

logger = Logging.get_logger()

class OriginSiteRouting:
    def choose_scheduler(self, job, clusters):
        if job is None or clusters is None:
            return None

        if type(clusters) is dict:
            return clusters.get(getattr(job, "origin_site", None))

        origin_site = getattr(job, "origin_site", None)
        for cluster in clusters:
            cluster_site_id = getattr(cluster, "site_id", getattr(cluster, "_site_id", None))
            if cluster_site_id == origin_site:
                return cluster
        return None


class CapacityAwareCIRouting:
    def __init__(self, k=0.0, simulation_time=None):
        self._ci_store = {}
        self._occupancy_store = {}
        self._routing_scores = {}
        self._k = k
        self._simulation_time = simulation_time 

    def prepare(self, schedulers):
        scheduler_list = schedulers.values() if isinstance(schedulers,dict) else schedulers
        for scheduler in scheduler_list:
            carbon_intensity = scheduler.get_carbon_intensity()
            occupancy = scheduler.cluster_occupancy()
            routing_score = carbon_intensity * (occupancy ** self._k)
            self._ci_store[id(scheduler)] = carbon_intensity
            self._routing_scores[id(scheduler)] = routing_score
            self._occupancy_store[id(scheduler)] = occupancy

        for scheduler in scheduler_list:
            site_id = getattr(scheduler, 'site_id', getattr(scheduler, '_site_id', 'Unknown'))
            current_time = self._simulation_time.get_current_datetime()
            logger.info(f"[{current_time}] Scheduler {site_id} has carbon intensity: {self._ci_store[id(scheduler)]},"
                        f" occupancy: {self._occupancy_store[id(scheduler)]}, routing score: {self._routing_scores[id(scheduler)]}")
            
    def choose_scheduler(self, job, schedulers):
        if job is None or schedulers is None:
            return None
        scheduler_list = list(schedulers.values()) if isinstance(schedulers, dict) else list(schedulers)
        if not scheduler_list:
            return None

        chosen_site = None
        lowest_routing_score = None

        for scheduler in scheduler_list:
            routing_score = self._routing_scores.get(id(scheduler))
            if routing_score is None:
                continue
            if lowest_routing_score is None or routing_score < lowest_routing_score:
                lowest_routing_score = routing_score
                chosen_site = scheduler
        return chosen_site


class OriginCapacityAwareCIRouting:
    def __init__(self, k=0.0, simulation_time=None, origin_bias=1.0):
        self._ci_store = {}
        self._occupancy_store = {}
        self._routing_scores = {}
        self._k = k
        self._simulation_time = simulation_time
        self._origin_bias = origin_bias

    def prepare(self, schedulers):
        scheduler_list = schedulers.values() if isinstance(schedulers,dict) else schedulers
        for scheduler in scheduler_list:
            carbon_intensity = scheduler.get_carbon_intensity()
            occupancy = scheduler.cluster_occupancy()
            ci_occ_score = carbon_intensity * (occupancy ** self._k)
            self._ci_store[id(scheduler)] = carbon_intensity
            self._occupancy_store[id(scheduler)] = occupancy
            self._routing_scores[id(scheduler)] = ci_occ_score


    def choose_scheduler(self, job, schedulers):
        if job is None or schedulers is None:
            logger.error(f"choose_scheduler called with job={job is not None}, schedulers={schedulers is not None}")
            raise RuntimeError(f"HIT NULL INPUT: job is None={job is None}, schedulers is None={schedulers is None}")


        scheduler_list = (list(schedulers.values()) if isinstance(schedulers, dict) else list(schedulers))
        if not scheduler_list:
            raise RuntimeError(f"HIT EMPTY SCHEDULER LIST: schedulers={schedulers!r}")

        chosen_site = None
        lowest_routing_score = None
        origin_site = getattr(job, "origin_site", None)
        MAX_OCCUPANCY = 0.9

        for scheduler in scheduler_list:
            site_id = id(scheduler)
            occupancy = self._occupancy_store.get(site_id, 0.0)
            if occupancy >= MAX_OCCUPANCY:
                continue
            scheduler_site_id = getattr(scheduler,"site_id",getattr(scheduler, "_site_id", None))
            ci = self._ci_store.get(site_id)
            if ci is None:
                continue
            # Calculate the routing score using the current occupancy.
            routing_score = ci * (occupancy ** self._k)
            # Apply origin-site preference
            if origin_site is not None and scheduler_site_id == origin_site:
                routing_score *= self._origin_bias
            if (lowest_routing_score is None or routing_score < lowest_routing_score):
                lowest_routing_score = routing_score
                chosen_site = scheduler

        if chosen_site is None:
            origin_scheduler = None
            if origin_site is not None:
                for scheduler in scheduler_list:
                    scheduler_site_id = getattr(scheduler, "site_id", getattr(scheduler, "_site_id", None))
                    if scheduler_site_id == origin_site:
                        origin_scheduler = scheduler
                        break

            if origin_scheduler is not None and self._occupancy_store.get(id(origin_scheduler), 0.0) < 1.0:
                chosen_site = origin_scheduler
            else:
                least_occupied = None
                least_occupancy = None
                for scheduler in scheduler_list:
                    occ = self._occupancy_store.get(id(scheduler), 0.0)
                    if least_occupancy is None or occ < least_occupancy:
                        least_occupancy = occ
                        least_occupied = scheduler
                chosen_site = least_occupied


        if chosen_site is not None:
            # Update occupancy
            site_id = id(chosen_site)
            total_cores = chosen_site.get_number_of_cores()
            job_share = (job.cores_req / total_cores if total_cores > 0 else 0.0)
            self._occupancy_store[site_id] = (self._occupancy_store.get(site_id, 0.0) + job_share)

        return chosen_site
    
class RoutingPolicyFactory:
    def create_routing_policy(policy_name, simulation_time=None, routing_config=None):
        routing_config = routing_config or {}
        k = routing_config.get("k", 0.0)
        origin_bias = routing_config.get("origin_bias", 1.0)
        policies = {
            "origin_site": lambda: OriginSiteRouting(),
            "capacity_aware_CI": lambda: CapacityAwareCIRouting(k=k, simulation_time=simulation_time),
            "origin_capacity_aware_CI": lambda: OriginCapacityAwareCIRouting(k=k, simulation_time=simulation_time, origin_bias=origin_bias),
        }

        try:
            return policies[policy_name]()
        except KeyError:
            raise ValueError(f"Invalid routing policy name: {policy_name}")
        