from swch_optimiser import SwchOptimiser

"""
rules in human readable format:

- if the node temperature is above a certain threshold, do not assign pods to that node
- if the average load across nodes with pods is above a certain threshold, scale up (add more pods)
- if the average load across nodes with pods is below a certain threshold, scale down (remove pods)
- always keep at least one pod running
- never assign more than one pod to the same node 
Based on the node_temp metrics, we decide which nodes can be assigned pods:
- if the node_temp is above the threshold_node_temperature, we consider it "too hot" and do not assign pods to that node
- if the node_temp is below the threshold_node_temperature, we consider it "cool enough" and can assign pods to that node
Based on the node_load metrics, we decide whether to scale up or down:
- if the average load across nodes with pods is above threshold_max_node_load, we scale up (add more pods)
- if the average load across nodes with pods is below threshold_min_node_load, we scale down (remove pods)

"""

rule = r"""
    % --- APPLICATION CONSTANTS ---
    float: threshold_node_temperature;
    float: threshold_min_node_load;
    float: threshold_max_node_load;
    % --- APPLICATION CONSTANTS ENDS HERE ---

    % --- APPLICATION PARAMETERS: SHOULD MATCH WITH NAMES IN MONITORING SPECIFICATION ---
    array[1..sys_node_count_max] of float: node_temp;
    array[1..sys_node_count_max] of float: node_load;
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

    % 2) Max number of pods per node is 1 (non-zero values must differ)
    constraint forall(i, j in 1..sys_pod_count_max where i < j)(
        sys_mapping_next[i] = 0 \/ sys_mapping_next[j] = 0 \/ sys_mapping_next[i] != sys_mapping_next[j]
    );

    % 3) Temperature Rule: No pod can be assigned to a node exceeding temp threshold
    constraint forall(p in 1..sys_pod_count_max) (
        sys_mapping_next[p] > 0 -> node_temp[sys_mapping_next[p]] < threshold_node_temperature
    );
    
    % 4) Scale Up: If load > threshold_max_node_load and initial count < max_pods, new count must be greater than initial
    constraint (avg_load_on_used_nodes > threshold_max_node_load /\ sys_pod_count_actual < sys_pod_count_max) -> sys_pod_count_next > sys_pod_count_actual;

    % 5) Scale Down: If load < threshold_min_node_load and initial count > 1, new count must be less than initial
    constraint (avg_load_on_used_nodes < threshold_min_node_load /\ sys_pod_count_actual > 1) -> sys_pod_count_next < sys_pod_count_actual;
    % --- LIST OF CONSTRAINTS ENDS HERE ---

    % --- OPTIMISATION GOAL: DEFINITION OF THE LOSS FUNCTION TO BE MINIMIZED ---
    % We define a loss function that captures the cost of changes from the initial mapping to the final mapping.
    % The loss is composed of:
    % - a high loss for migrating pods (to encourage stability)
    % - a moderate loss for changing the pod count (to avoid unnecessary scaling)
    % - a lower loss for utilizing higher temperature nodes (to prefer cooler nodes when changes are necessary)
    % The solver will try to minimize this loss.
    var int: loss =
        % high loss for migrating pods
        1000*sum(p in 1..sys_pod_count_max)(bool2int(sys_mapping_next[p] != sys_mapping_actual[p]))+
        % moderate loss for changing pod count
        100*abs(sys_pod_count_actual - sys_pod_count_next) +
        % low loss for utilising higher temperature nodes
        10*sum(p in 1..sys_pod_count_max where sys_mapping_next[p]>0)(round(node_temp[sys_mapping_next[p]]));
    % --- OPTIMISATION GOAL ENDS HERE ---

    % --- SOLVE THE OPTIMISATION PROBLEM: DO NOT CHANGE THE FOLLOWING LINE ---
    solve minimize loss;
    """

input_system = {}
#SYSTEM PARAMETERS
#Limits for pods and nodes
input_system["sys_pod_count_max"] = 5
input_system["sys_node_count_max"] = 5
input_system["sys_node_count_actual"] = 3
#Actual mapping of pods to nodes (initial state)
input_system["sys_mapping_actual"] = [1, 2, 3, 0, 0]

#APPLICATION PARAMETERS
#Constants
input_constants = {}
input_constants["threshold_node_temperature"] = 80.0
input_constants["threshold_min_node_load"] = 20.0
input_constants["threshold_max_node_load"] = 80.0
#Actual monitoring metrics
input_metrics = {}
input_metrics["node_temp"] = [10.0, 50.0, 90.0, 70.0, 10.0]
input_metrics["node_load"] = [90.0, 10.0, 70.0, 90.0, 10.0]


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
    reconfig_result = optimiser.solve(time_limit_milliseconds=1000)
    elapsed_time = optimiser.time_taken()
    print(f"OPTIMISER finished.\tTime taken: {elapsed_time} milliseconds.")

    print("\nAPPSPEC INPUT PARAMETER VALUES:")
    optimiser.dump_appspec_input_parameter_values()
    print("SYSTEM INPUT PARAMETER VALUES:")
    optimiser.dump_system_input_parameter_values()

    if reconfig_result.solution is None:
        print(f"OUT: no feasible mapping produced. Solver status: {reconfig_result.status}")
    else:
        print("SYSTEM OUTPUT PARAMETER VALUES:")
        optimiser.dump_system_output_parameter_values()

        actions = optimiser.generate_actions()
        print("\nLIST OF ACTIONS:")
        optimiser.dump_actions(actions)




