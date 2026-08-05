from swch_optimiser import SwchOptimiser

"""
rules in human readable format:

- minimum number of pods is 1
- if the load is below a certain threshold and we have more than 1 pod, we should scale down (remove a pod)
- if the load is above a certain threshold and we have less than max pods, we should scale up (add a pod)
- a node cannot host more than two pods
- node can be scaled up when there are not enough nodes to host the existing pods (e.g., all nodes reached its maximum capacity)
"""

rule = r"""
    % --- SYSTEM PARAMETERS: DO NOT CHANGE THE FOLLOWING LINES, YOU CAN REFER TO THESE VARIABLES ---
    % --- INPUTS ---
    int: sys_pod_count_max; % hard limit for the number of pods (must be >= actual pod count)
    int: sys_node_count_max; % hard limit for the number of nodes (must be >= actual node count)
    int: sys_node_count_actual; % number of nodes currently existing in the system
    array[1..sys_pod_count_max] of int: sys_mapping_actual; % 0: non-existent, otherwise node index
    % --- OUTPUTS ---
    var 1..sys_node_count_max: sys_node_count_next :: add_to_output;
    array[1..sys_pod_count_max] of var 0..sys_node_count_max: sys_mapping_next :: add_to_output; % 0: non-existent, otherwise node index
    % --- AUXILIARY VARIABLES
    var 0..sys_pod_count_max: sys_pod_count_next = sum(p in 1..sys_pod_count_max)(sys_mapping_next[p] > 0);
    int: sys_pod_count_actual = sum(p in 1..sys_pod_count_max)(sys_mapping_actual[p] > 0);
    % --- SYSTEM PARAMETERS ENDS HERE ---    

    % --- APPLICATION CONSTANTS ---
    float: threshold_min_node_load;
    float: threshold_max_node_load;
    % --- APPLICATION CONSTANTS ENDS HERE ---

    % --- APPLICATION PARAMETERS: SHOULD MATCH WITH NAMES IN MONITORING SPECIFICATION ---
    array[1..sys_node_count_actual] of float: node_load;
    % --- APPLICATION PARAMETERS ENDS HERE ---

    % --- DERIVED PARAMETERS WHICH MAKES CONSTRAINTS AND OPTIMISATION GOAL EASIER TO BE EXPRESSED ---
    int: sys_node_count_used = sum(n in 1..sys_node_count_max)(exists(p in 1..sys_pod_count_max)(sys_mapping_actual[p] = n));
    float: avg_load_on_used_nodes =
        if sys_node_count_used > 0 then
            sum(n in 1..sys_node_count_max where exists(p in 1..sys_pod_count_max)(sys_mapping_actual[p] = n))(node_load[n]) /
            int2float(sys_node_count_used)
        else
            threshold_min_node_load + (threshold_max_node_load - threshold_min_node_load) / 2
        endif;
    % --- DERIVED PARAMETERS ENDS HERE ---
    
    % --- LIST OF CONSTRAINTS: WHAT ARE THE CONDITIONS WHICH HAS TO BE SATISFIED FOR THE MAPPING---
    % 1) Minimum number of pods is 1
    constraint sys_pod_count_next >= 1;

    % 2) Max number of pods per node is 2 (non-zero values must differ)
    constraint forall(n in 1..sys_node_count_max) (
        sum(p in 1..sys_pod_count_max)(bool2int(sys_mapping_next[p] = n)) <= 2 
    );

    % 3) Considering node scaling in mapping: Each pod can only be mapped to node (index between 1 and sys_node_count_next) or be non-existent (0)
    constraint forall(p in 1..sys_pod_count_max) (
        (sys_mapping_next[p] = 0) \/ 
        (sys_mapping_next[p] >= 1 /\ sys_mapping_next[p] <= sys_node_count_next)
    );

    % 4) Scale Up nodes: when pods do not fit on existing nodes (2 pods/node)
    constraint (sys_pod_count_next > sys_node_count_actual * 2) ->
                (sys_node_count_next > sys_node_count_actual /\
                 sys_node_count_next * 2 >= sys_pod_count_next);

    % 5) Scale Down nodes: when pods may fit to fewer nodes
    constraint (sys_pod_count_next <= (sys_node_count_actual - 1 ) * 2) /\
               (sys_node_count_next > 1) -> 
                sys_node_count_next < sys_node_count_actual;
    
    % 6) Scale Up pods: If load > threshold_max_node_load and initial count < max_pods and there is node capacity, new count must be greater than initial
    constraint (avg_load_on_used_nodes > threshold_max_node_load /\
                sys_pod_count_actual < sys_pod_count_max /\ 
                sys_pod_count_actual < sys_node_count_max * 2) -> 
                sys_pod_count_next = sys_pod_count_actual + 3;

    % 7) Scale Down pods: If load < threshold_min_node_load and initial count > 1, new count must be less than initial
    constraint (avg_load_on_used_nodes < threshold_min_node_load /\ 
                sys_pod_count_actual > 1) -> 
                sys_pod_count_next = sys_pod_count_actual - 3;
    % --- LIST OF CONSTRAINTS ENDS HERE ---

    % --- OPTIMISATION GOAL: DEFINITION OF THE LOSS FUNCTION TO BE MINIMIZED ---
    % We define a loss function that captures the cost of changes from the initial mapping to the final mapping.
    % The loss is composed of:
    % - a high loss for migrating pods (to encourage stability)
    % - a moderate loss for changing the pod count (to avoid unnecessary scaling)
    % - a lower loss for utilizing higher temperature nodes (to prefer cooler nodes when changes are necessary)
    % The solver will try to minimize this loss.
    var int: loss =
        % high loss for scaling nodes
        % 1000*abs(sys_node_count_next - sys_node_count_actual) +
        % moderate loss for migrating pods
        100*sum(p in 1..sys_pod_count_max)(bool2int(sys_mapping_next[p] != sys_mapping_actual[p]))+
        % low loss for changing pod count
        10*abs(sys_pod_count_actual - sys_pod_count_next);
        % --- OPTIMISATION GOAL ENDS HERE ---

    % --- SOLVE THE OPTIMISATION PROBLEM: DO NOT CHANGE THE FOLLOWING LINE ---
    solve minimize loss;
    """

input_system = {}
#SYSTEM PARAMETERS
#Limits for pods and nodes
input_system["sys_pod_count_max"] = 14
input_system["sys_node_count_max"] = 10
input_system["sys_node_count_actual"] = 3
#Actual mapping of pods to nodes (initial state)
input_system["sys_mapping_actual"] = [1, 1, 2, 2, 3, 0, 0, 0, 0, 0, 0, 0, 0, 0]  # nodes 1-6 full (2 pods each), node 7 unused

#APPLICATION PARAMETERS
#Constants
input_constants = {}
input_constants["threshold_min_node_load"] = 40.0
input_constants["threshold_max_node_load"] = 70.0
#Actual monitoring metrics
input_metrics = {}
input_metrics["node_load"] = [30.0, 30.0, 30.0]  # one value per actual node (nodes 1-3)

if __name__ == "__main__":

    mslist = ["soundprocessing"]
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
    reconfig_result = optimiser.solve(time_limit_milliseconds=None, verbose=True)
    elapsed_time = optimiser.time_taken()
    print(f"OPTIMISER finished.\tTime taken: {elapsed_time} milliseconds.")

    print("\nAPPSPEC INPUT PARAMETER VALUES:")
    optimiser.dump_appspec_input_parameter_values()
    print("SYSTEM INPUT PARAMETER VALUES:")
    optimiser.dump_system_input_parameter_values()

    if reconfig_result == None or reconfig_result.solution is None:
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




