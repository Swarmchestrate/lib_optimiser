from swch_optimiser import SwchOptimiser

"""
rules in human readable format:

The containers must be orchestrated in lots to the corresponding edge device types and according to the
defined operational periods, as outlined below:
DAYTIME: from 07:00 am to 07:00 pm (Spanish local time)
First Lot → Orchestration deployed on Raspberry Pi 2 units.
- swarmchestrate-acquisition-fuelics
- swarmchestrate-acquisition-fuelics-gateway
Second Lot → Orchestration deployed on Raspberry Pi 5 units.
- swarmchestrate-processing
- swarmchestrate-ui

NIGHTTIME: from 07:00 pm to 07:00 am (Spanish local time)
Third Lot → Orchestration deployed on Raspberry Pi 2 units.
- swarmchestrate-acquisition-ecowitt
- swarmchestrate-acquisition-waft
Fourth Lot → Orchestration deployed on Raspberry Pi 5 units.
- swarmchestrate-processing
- swarmchestrate-synchronize

Each Raspberry PI unit can run at most one lot of containers.

DAYTIME SCALING
1. The orchestrator performs horizontal scaling (Energy-based scaling) of the First Lot of containers
on the Raspberry Pi 2 units by adjusting the number of running instances across the network,
while ensuring that each Raspberry Pi 2 unit runs only one lot.
2. The orchestrator performs horizontal scaling (Load-based scaling) of the Second Lot of
containers on the Raspberry Pi 5 units by modifying the number of active instances across the
network, while ensuring that each Raspberry Pi 5 unit runs only one lot.

- Initial state: Upon startup, the First Lot and the Second Lot are deployed. Specifically, one Raspberry Pi 2
unit runs the First Lot, while one Raspberry Pi 5 unit runs the Second Lot.
Minim Capacity Guarantee: the orchestrator ensures that at least one deployment of both First Lot and
Second Lot of containers remains active within the network. When the system needs to (re)establish this
baseline, both First Lot and Second Lot of containers are deployed on the edge device exhibiting the
lowest CPU workload.
- Load-based scaling (CPU): the orchestrator continuously monitors the average CPU workload of the
Raspberry PI 5 edge devices. When the sustained workload exceeds a predefined threshold, the
orchestrator deploys an additional lot of containers on the lowest CPU workload available edge device
(available means no lots of containers are deployed on the edge device). Conversely, when the sustained
workload falls below a lower threshold, the orchestrator removes the lot of containers, prioritizing the
device with the highest CPU workload. This mechanism maintains balanced CPU workload across the
network.
- Energy-based scaling (Sunlight forecast): every night, the orchestrator retrieves the sunlight forecast for
the defined geographic coordinates and based on the predicted total hours of sunlight, establishes a
scaling level for the upcoming day. According to this scaling level, the orchestrator deploys additional
container instances on the coolest available Raspberry Pi 2 units (as determined by CPU temperature),
while ensuring that both containers remain active on each Raspberry Pi 2 unit, with only one instance per
container. Pending to define whether if we can get the battery level or if we can request the real
time weather during the day (18/11/2025).

NIGHTTIME SCALING
1. The orchestrator performs horizontal scaling (Energy-based scaling) of the Third Lot of
containers on the Raspberry Pi 2 units by adjusting the number of running instances across the
network, while ensuring that each Raspberry Pi 2 unit runs only one lot.
2. The orchestrator performs horizontal scaling (Energy-based scaling) of Fourth Lot of containers
on the Raspberry Pi 5 units by modifying the number of active instances across the network,
while ensuring that each Raspberry Pi 5 unit runs only one lot.

- Initial state: Upon startup, the Third Lot and the Fourth Lot are deployed. Specifically, one Raspberry Pi 2
unit runs the Third Lot, while one Raspberry Pi 5 unit runs the Fourth Lot.
- Minim Capacity Guarantee: the orchestrator ensures that at least one deployment of both Third Lot and
Fourth Lot of containers remains active within the network. When the system needs to (re)establish this
baseline, both Third Lot and Fourth Lot of containers are deployed on the edge device exhibiting the
lowest CPU workload.
- Energy-based scaling (Sunlight forecast): every night, the orchestrator retrieves the sunlight forecast for
the defined geographic coordinates and based on the predicted total hours of sunlight, establishes a
scaling level for the upcoming day. According to this scaling level, the orchestrator deploys additional
container instances on the coolest available Raspberry Pi 2 ad Raspberry Pi 5 units (as determined by
CPU temperature), while ensuring that both containers remain active on each Raspberry Pi 2 unit, with
only one instance per container and only one container instance per Raspberry Pi 5 unit. Pending to
define whether if we can get the battery level or if we can request the real time weather during the
day (18/11/2025).

Input metrics:
- CPU workload (cpu_workload): average CPU workload (0–100 %) measured on Raspberry PI 5 edge
devices that are running any lot of containers. It is aggregated over a 60-second window to avoid reacting
to short spikes. This aggregated value is used to decide when to scale up or down.
- Sunlight forecast (sunlight_forecast): total predicted hours of sunlight for the defined geographic
coordinates during a daytime. This value is used to determine the scaling level for the upcoming day in
the energy-based scaling mechanism. Pending to define whether if we can get the battery level or if
we can request the real time weather during the day (18/11/2025).

Energy-based scaling
Scale method: during the nighttime the scale level for the upcoming day is determined by the total
sunlight hours prediction. When the daytime of the next day arrives, the orchestrator scales the
corresponding number of container instances that matches the device scaling percentage.
e.g: In a network of n Raspberry Pi 2 edge device, if the scale level is determined to 3 the orchestrator
scales the corresponding containers to n*50/100 devices (take the integer part of the division)
Consideration: if by any reason, the scale level can’t be calculated, the scale level is set to 1.
Scale level table: The following table defines the scaling level based on the predicted total hours of
sunlight during daytime and the corresponding edge device scaling percentage.

TABLE:
"SCALE LEVEL", "TOTAL SUNLIGHT HOURS", "DEVICE SCALING"
1, T < 2, 0%
2, 2 < T < 4, 25%
3, 4 < T < 6, 50%
4, 6 < T < 8, 75%
5, T > 8, 100%
"""

rule = r"""
    % --- APPLICATION CONSTANTS ---
    float: threshold_node_load_min;
    float: threshold_node_load_max;
    float: threshold_timestamp_7AM;
    float: threshold_timestamp_7PM;
    % --- APPLICATION CONSTANTS ENDS HERE ---

    % --- APPLICATION PARAMETERS: SHOULD MATCH WITH NAMES IN MONITORING SPECIFICATION ---
    float: timestamp_hour;
    array[1..sys_node_count_actual] of float: node_load;
    % --- APPLICATION PARAMETERS ENDS HERE ---

    % --- DERIVED PARAMETERS WHICH MAKES CONSTRAINTS AND OPTIMISATION GOAL EASIER TO BE EXPRESSED ---
    bool: is_daytime = (timestamp_hour >= threshold_timestamp_7AM /\ timestamp_hour < threshold_timestamp_7PM);
    bool: is_nighttime = (timestamp_hour < threshold_timestamp_7AM \/ timestamp_hour >= threshold_timestamp_7PM);
    int: sys_node_count_used = sum(n in 1..sys_node_count_actual)(exists(p in 1..sys_pod_count_max)(sys_mapping_actual[p] = n));
    float: avg_load_on_used_nodes =
        if sys_node_count_used > 0 then
            sum(n in 1..sys_node_count_actual where exists(p in 1..sys_pod_count_max)(sys_mapping_actual[p] = n))(node_load[n]) /
            int2float(sys_node_count_used)
        else
            threshold_node_load_min + (threshold_node_load_max - threshold_node_load_min) / 2
        endif;
    % --- DERIVED PARAMETERS ENDS HERE ---
 
    % --- LIST OF CONSTRAINTS: WHAT ARE THE CONDITIONS WHICH HAS TO BE SATISFIED FOR THE MAPPING---
    % 1) During nighttime (7PM-7AM), there must be no active pods
    constraint is_nighttime -> sys_pod_count_next = 0;

    % 2) During daytime (7AM-7PM), at least one pod must be active
    constraint is_daytime -> sys_pod_count_next >= 1;
    
    % 3) Max number of pods per node is 1 (non-zero values must differ)
    constraint forall(i, j in 1..sys_pod_count_max where i < j)(
        sys_mapping_next[i] = 0 \/ 
        sys_mapping_next[j] = 0 \/ 
        sys_mapping_next[i] != sys_mapping_next[j]);

    % 3b) Pods can only be mapped to existing nodes (1..sys_node_count_actual)
    constraint forall(p in 1..sys_pod_count_max where sys_mapping_next[p] > 0)(
        sys_mapping_next[p] <= sys_node_count_actual);

    % 4) Scale Up: If load > threshold_node_load_max and sys_pod_count_next < sys_pod_count_max and there are available nodes, new count must be greater than initial
    constraint (avg_load_on_used_nodes > threshold_node_load_max /\ 
                sys_pod_count_next < sys_pod_count_max /\
                sys_pod_count_next < sys_node_count_actual /\
                is_daytime) -> 
                sys_pod_count_next > sys_pod_count_actual;

    % 5) Scale Down: If load < threshold_node_load_min and sys_pod_count_actual > 1, new count must be less than initial
    constraint (avg_load_on_used_nodes < threshold_node_load_min /\ 
                sys_pod_count_actual > 1 /\ 
                is_daytime) -> 
                sys_pod_count_next < sys_pod_count_actual;
    % --- LIST OF CONSTRAINTS ENDS HERE ---

    % --- OPTIMISATION GOAL: DEFINITION OF THE LOSS FUNCTION TO BE MINIMIZED ---
    % We define a loss function that captures the cost of changes from the initial mapping to the final mapping.
    % The loss is composed of:
    % - a high loss for migrating pods (to encourage stability)
    % - a moderate loss for changing the pod count
    % - a loss for utilizing higher load nodes
    var int: loss =
        % loss for migrating pods
        1000*sum(p in 1..sys_pod_count_max)(bool2int(sys_mapping_next[p] != sys_mapping_actual[p]))+
        % loss for changing pod count
        100*abs(sys_pod_count_actual - sys_pod_count_next) +
        % loss for utilizing higher load nodes
        sum(p in 1..sys_pod_count_max where sys_mapping_next[p] > 0)(round(node_load[sys_mapping_next[p]]));
    % --- OPTIMISATION GOAL ENDS HERE ---

    % --- SOLVE THE OPTIMISATION PROBLEM: DO NOT CHANGE THE FOLLOWING LINE ---
    solve minimize loss;
    """

input_system = {}
#SYSTEM PARAMETERS
#Limits for pods and nodes
input_system["sys_pod_count_max"] = 5
#input_system["sys_pod_count_actual"] = 3
#input_system["sys_pod_count_next"] = input_system["sys_pod_count_actual"]
input_system["sys_node_count_max"] = 5
input_system["sys_node_count_actual"] = 4
input_system["sys_node_count_next"] = input_system["sys_node_count_actual"]
#Actual mapping of pods to nodes (initial state)
input_system["sys_mapping_actual"] = [1, 2, 3, 0, 0]  # nodes 1-3 have 1 pod each, nodes 4-5 unused

#APPLICATION PARAMETERS
#Constants
input_constants = {}
input_constants["threshold_timestamp_7AM"] = 7
input_constants["threshold_timestamp_7PM"] = 19
input_constants["threshold_node_load_min"] = 20.0
input_constants["threshold_node_load_max"] = 80.0
#Actual monitoring metrics
input_metrics = {}
input_metrics["timestamp_hour"] = 18
input_metrics["node_load"] = [90.0, 90.0, 90.0, 0.0]  # one value per actual node (nodes 1-4), node 5 unused

if __name__ == "__main__":

    mslist = ["ust_lot2"]
    optimiser = SwchOptimiser(rule, mslist)
    if optimiser.get_error() is not None:
        print(f"\n{optimiser.get_error()}")
        exit(1)

    print("\nMODEL INPUTS AND OUTPUTS (extracted):")
    optimiser.dump_extracted_parameters()

    optimiser.add_input_system(input_system)
    optimiser.add_input_constants(input_constants)
    optimiser.add_input_metrics(input_metrics)
    optimiser.validate_inputs()

    print("\nOPTIMISER started.")
    reconfig_result = optimiser.solve(time_limit_milliseconds=1000)
    elapsed_time = optimiser.time_taken()
    print(f"OPTIMISER finished.\tTime taken: {elapsed_time} milliseconds.")

    print("\nAPPSPEC INPUT PARAMETER VALUES:")
    optimiser.dump_appspec_input_parameter_values()
    print("SYSTEM INPUT PARAMETER VALUES:")
    optimiser.dump_system_input_parameter_values()

    if reconfig_result is None:
        print("RESULT: no feasible mapping produced. Solver did not return a result.")
    elif reconfig_result.solution is None:
        print(f"RESULT: no feasible mapping produced. Solver status: {reconfig_result.status}")
    else:
        print("SYSTEM OUTPUT PARAMETER VALUES:")
        optimiser.dump_system_output_parameter_values()

        actions = optimiser.generate_actions()
        print("\nLIST OF ACTIONS:")
        optimiser.dump_actions(actions)

 

