from swch_optimiser import SwchOptimiser

"""
rules in human readable format:

- when the requests/sec are above a fixed threshold (e.g. 10 req/s) scale up.
- When the requests/sec are below a fixed threshold (e.g. 10 req/s) scale down.

- If expected_rainfall < 10
    scale “no rain” to 1
    scale “average rain” to 0
    scale “heavy rain” to 0
- Else if expected_rainfall < 50
    scale “no rain” to 0
    scale “average rain” to 1
    scale “heavy rain” to 0
- Else
    scale “no rain” to 0
    scale “average rain” to 0
    scale “heavy rain” to 1
- End If

- always keep one instance of the pods ("no rain", "average rain", "heavy rain") running
- never keep instances of pods belonging to more than one of the three categories ("no rain", "average rain", "heavy rain")
  which means, only one of the three categories can be active at the same time, but it can be active on multiple nodes (for scaling up)

Based on the expected_rainfall metrics, we decide which category of pods to run:
- if the expected_rainfall is below this threshold, we consider it "no rain"
- if the expected_rainfall is between node_rain_no_threshold and node_rain_average_threshold, we consider it "average rain"
- if the expected_rainfall is above node_rain_average_threshold, we consider it "heavy rain"

Based on the actual_requestpersec metrics, we decide how many pods to run:
- if the actual_requestpersec is below node_requestpersec_threshold_min, we scale down (reduce the number of active pods)
- if the actual_requestpersec is above node_requestpersec_threshold_max, we scale up (increase the number of active pods)

"""

rule = r"""
    % --- SYSTEM PARAMETERS OF "norain": DO NOT CHANGE THE FOLLOWING LINES, YOU CAN REFER TO THESE VARIABLES ---
    % --- INPUTS ---
    int: norain_sys_pod_count_max; % hard limit for the number of pods (must be >= actual pod count)
    int: norain_sys_node_count_max; % hard limit for the number of nodes (must be >= actual node count)
    int: norain_sys_node_count_actual; % number of nodes currently existing in the system
    array[1..norain_sys_pod_count_max] of int: norain_sys_mapping_actual; % 0: non-existent, otherwise node index
    % --- OUTPUTS ---
    var 1..norain_sys_node_count_max: norain_sys_node_count_next :: add_to_output;
    array[1..norain_sys_pod_count_max] of var 0..norain_sys_node_count_max: norain_sys_mapping_next :: add_to_output; % 0: non-existent, otherwise node index
    % --- AUXILIARY VARIABLES
    var 0..norain_sys_pod_count_max: norain_sys_pod_count_next = sum(p in 1..norain_sys_pod_count_max)(norain_sys_mapping_next[p] > 0);
    int: norain_sys_pod_count_actual = sum(p in 1..norain_sys_pod_count_max)(norain_sys_mapping_actual[p] > 0);
    % --- SYSTEM PARAMETERS OF "norain" ENDS HERE ---

    % --- SYSTEM PARAMETERS OF "average": DO NOT CHANGE THE FOLLOWING LINES, YOU CAN REFER TO THESE VARIABLES ---
    % --- INPUTS ---
    int: average_sys_pod_count_max; % hard limit for the number of pods (must be >= actual pod count)
    int: average_sys_node_count_max; % hard limit for the number of nodes (must be >= actual node count)
    int: average_sys_node_count_actual; % number of nodes currently existing in the system
    array[1..average_sys_pod_count_max] of int: average_sys_mapping_actual; % 0: non-existent, otherwise node index
    % --- OUTPUTS ---
    var 1..average_sys_node_count_max: average_sys_node_count_next :: add_to_output;
    array[1..average_sys_pod_count_max] of var 0..average_sys_node_count_max: average_sys_mapping_next :: add_to_output; % 0: non-existent, otherwise node index
    % --- AUXILIARY VARIABLES
    var 0..average_sys_pod_count_max: average_sys_pod_count_next = sum(p in 1..average_sys_pod_count_max)(average_sys_mapping_next[p] > 0);
    int: average_sys_pod_count_actual = sum(p in 1..average_sys_pod_count_max)(average_sys_mapping_actual[p] > 0);
    % --- SYSTEM PARAMETERS OF "average" ENDS HERE ---

    % --- SYSTEM PARAMETERS OF "heavy": DO NOT CHANGE THE FOLLOWING LINES, YOU CAN REFER TO THESE VARIABLES ---
    % --- INPUTS ---
    int: heavy_sys_pod_count_max; % hard limit for the number of pods (must be >= actual pod count)
    int: heavy_sys_node_count_max; % hard limit for the number of nodes (must be >= actual node count)
    int: heavy_sys_node_count_actual; % number of nodes currently existing in the system
    array[1..heavy_sys_pod_count_max] of int: heavy_sys_mapping_actual; % 0: non-existent, otherwise node index
    % --- OUTPUTS ---
    var 1..heavy_sys_node_count_max: heavy_sys_node_count_next :: add_to_output;
    array[1..heavy_sys_pod_count_max] of var 0..heavy_sys_node_count_max: heavy_sys_mapping_next :: add_to_output; % 0: non-existent, otherwise node index
    % --- AUXILIARY VARIABLES
    var 0..heavy_sys_pod_count_max: heavy_sys_pod_count_next = sum(p in 1..heavy_sys_pod_count_max)(heavy_sys_mapping_next[p] > 0);
    int: heavy_sys_pod_count_actual = sum(p in 1..heavy_sys_pod_count_max)(heavy_sys_mapping_actual[p] > 0);
    % --- SYSTEM PARAMETERS OF "heavy" ENDS HERE ---

    % --- APPLICATION CONSTANTS ---
    float: threshold_max_norain;
    float: threshold_max_average;
    float: threshold_min_requestpersec;
    float: threshold_max_requestpersec;
    % --- APPLICATION CONSTANTS ENDS HERE ---

    % --- APPLICATION PARAMETERS: SHOULD MATCH WITH NAMES IN MONITORING SPECIFICATION ---
    float: expected_rainfall;
    float: actual_requestpersec;
    % --- APPLICATION PARAMETERS ENDS HERE ---

    % --- DERIVED PARAMETERS WHICH MAKES CONSTRAINTS AND OPTIMISATION GOAL EASIER TO BE EXPRESSED ---
    int: pod_count_max = min([norain_sys_pod_count_max, average_sys_pod_count_max, heavy_sys_pod_count_max]);
    int: pod_count_actual_total = norain_sys_pod_count_actual + average_sys_pod_count_actual + heavy_sys_pod_count_actual;
    var int: pod_count_next_total = norain_sys_pod_count_next + average_sys_pod_count_next + heavy_sys_pod_count_next;
    % --- DERIVED PARAMETERS ENDS HERE ---

    % --- LIST OF CONSTRAINTS: WHAT ARE THE CONDITIONS WHICH HAS TO BE SATISFIED FOR THE MAPPING---
    % 1) This rule never scales the node count, only where pods are placed
    constraint norain_sys_node_count_next = norain_sys_node_count_actual;
    constraint average_sys_node_count_next = average_sys_node_count_actual;
    constraint heavy_sys_node_count_next = heavy_sys_node_count_actual;
    
    % 1) Always keep at least one pod running total
    constraint pod_count_next_total >= 1;

    % 2) Only one category can be active at a time (mutual exclusion)
    constraint (norain_sys_pod_count_next > 0 /\ average_sys_pod_count_next = 0 /\ heavy_sys_pod_count_next = 0) \/
               (norain_sys_pod_count_next = 0 /\ average_sys_pod_count_next > 0 /\ heavy_sys_pod_count_next = 0) \/
               (norain_sys_pod_count_next = 0 /\ average_sys_pod_count_next = 0 /\ heavy_sys_pod_count_next > 0);

    % 3) Rainfall-based category selection
    % NORAIN
    % If expected_rainfall <= threshold_max_norain: only "no rain" pods active
    constraint expected_rainfall <= threshold_max_norain -> 
        (norain_sys_pod_count_next >= 1 /\ average_sys_pod_count_next = 0 /\ heavy_sys_pod_count_next = 0);
    
    % AVERAGE RAIN
    % If threshold_max_norain < expected_rainfall <= threshold_max_average: only "average rain" pods active
    constraint (expected_rainfall > threshold_max_norain /\ expected_rainfall <= threshold_max_average) -> 
        (norain_sys_pod_count_next = 0 /\ average_sys_pod_count_next >= 1 /\ heavy_sys_pod_count_next = 0);
    
    % HEAVY RAIN
    % If expected_rainfall >= threshold_max_average: only "heavy rain" pods active
    constraint expected_rainfall >= threshold_max_average -> 
        (norain_sys_pod_count_next = 0 /\ average_sys_pod_count_next = 0 /\ heavy_sys_pod_count_next >= 1);

    % 4) Scale Up based on requests/sec: only if current total pods are below max_pods
    constraint (actual_requestpersec > threshold_max_requestpersec /\ pod_count_next_total < pod_count_max) -> 
        pod_count_next_total > pod_count_actual_total;

    % 5) Scale Down based on requests/sec: only if initial total pods is > 1
    constraint (actual_requestpersec < threshold_min_requestpersec /\
               pod_count_actual_total > 1) -> 
        pod_count_next_total < pod_count_actual_total;
    % --- LIST OF CONSTRAINTS ENDS HERE ---

    % --- OPTIMISATION GOAL: DEFINITION OF THE LOSS FUNCTION TO BE MINIMIZED ---
    % We define a loss function that captures the cost of changes from the initial mapping to the final mapping.
    % The loss is composed of:
    % - A high loss for migrating pods in each category (to minimize unnecessary migrations)
    % - A smaller loss for changing total pod count (to minimize unnecessary scaling actions)
    var int: loss =
        % Penalty for migrating pods in each category
        1000 * (sum(p in 1..norain_sys_pod_count_max)(bool2int(norain_sys_mapping_next[p] != norain_sys_mapping_actual[p])) +
            sum(p in 1..average_sys_pod_count_max)(bool2int(average_sys_mapping_next[p] != average_sys_mapping_actual[p])) +
            sum(p in 1..heavy_sys_pod_count_max)(bool2int(heavy_sys_mapping_next[p] != heavy_sys_mapping_actual[p]))) +
        % Penalty for changing total pod count
        100 * abs(pod_count_actual_total - pod_count_next_total);
    % --- OPTIMISATION GOAL ENDS HERE ---

    % --- SOLVE THE OPTIMISATION PROBLEM: DO NOT CHANGE THE FOLLOWING LINE ---
    solve minimize loss;
    """

input_system = {}
#SYSTEM PARAMETERS
#Limits for pods and nodes
input_system["norain_sys_pod_count_max"] = 5
input_system["norain_sys_node_count_max"] = 5
input_system["norain_sys_node_count_actual"] = 5
input_system["average_sys_pod_count_max"] = 5
input_system["average_sys_node_count_max"] = 5
input_system["average_sys_node_count_actual"] = 5
input_system["heavy_sys_pod_count_max"] = 5
input_system["heavy_sys_node_count_max"] = 5
input_system["heavy_sys_node_count_actual"] = 5
#Actual mapping of pods to nodes (initial state)
input_system["norain_sys_mapping_actual"] = [1, 0, 0, 0, 0]
input_system["average_sys_mapping_actual"] = [0, 0, 0, 0, 0]
input_system["heavy_sys_mapping_actual"] = [0, 0, 0, 0, 0]

#APPLICATION PARAMETERS
#Constants
input_constants = {}
input_constants["threshold_max_norain"] = 10.0
input_constants["threshold_max_average"] = 50.0
input_constants["threshold_min_requestpersec"] = 20.0
input_constants["threshold_max_requestpersec"] = 80.0
#Actual monitoring metrics
input_metrics = {}
input_metrics["expected_rainfall"] = 40.0
input_metrics["actual_requestpersec"] = 90.0

if __name__ == "__main__":

    mslist = ["norain", "average", "heavy"]
    optimiser = SwchOptimiser(rule,mslist)
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

    if reconfig_result is None or reconfig_result.solution is None:
        if optimiser.get_error() is not None:
            print(f"\n{optimiser.get_error()}")
        else:
            print(f"OUT: no feasible mapping produced. Solver status: {reconfig_result.status}")
    else:
        print("SYSTEM OUTPUT PARAMETER VALUES:")
        optimiser.dump_system_output_parameter_values()

        actions = optimiser.generate_actions()
        print("\nLIST OF ACTIONS:")
        optimiser.dump_actions(actions)
