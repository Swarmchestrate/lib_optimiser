from swch_optimiser import SwchOptimiser

SYSTEM_PARAMS = r"""
    int: sys_pod_count_max;
    int: sys_node_count_max;
    int: sys_node_count_actual;
    array[1..sys_pod_count_max] of int: sys_mapping_actual;
    var 1..sys_node_count_max: sys_node_count_next :: add_to_output;
    array[1..sys_pod_count_max] of var 0..sys_node_count_max: sys_mapping_next :: add_to_output;
    var 0..sys_pod_count_max: sys_pod_count_next = sum(p in 1..sys_pod_count_max)(sys_mapping_next[p] > 0);
    int: sys_pod_count_actual = sum(p in 1..sys_pod_count_max)(sys_mapping_actual[p] > 0);
    """

MINIMAL_RULE = SYSTEM_PARAMS + "solve satisfy;"


def test_invalid_rule_reports_error_with_line_number():
    optimiser = SwchOptimiser(rule="this is not valid minizinc syntax;")

    assert optimiser.get_error() is not None
    assert "line no." in optimiser.get_error()


def test_valid_minimal_model_has_no_error():
    optimiser = SwchOptimiser(rule=MINIMAL_RULE)

    assert optimiser.get_error() is None


def test_solve_produces_a_result_and_actions_for_simple_scaling():
    rule = SYSTEM_PARAMS + r"""
        constraint sys_node_count_next = sys_node_count_actual;
        constraint sys_pod_count_next >= 1;
        var int: loss = sum(p in 1..sys_pod_count_max)(bool2int(sys_mapping_next[p] != sys_mapping_actual[p]));
        solve minimize loss;
        """
    optimiser = SwchOptimiser(rule=rule, mslist=["svc"])
    assert optimiser.get_error() is None

    optimiser.add_input_system({
        "sys_pod_count_max": 2,
        "sys_node_count_max": 1,
        "sys_node_count_actual": 1,
        "sys_mapping_actual": [1, 0],
    })
    optimiser.validate_inputs()

    result = optimiser.solve(time_limit_milliseconds=5000)

    assert optimiser.get_error() is None
    assert result is not None
    assert result.solution is not None
    assert isinstance(optimiser.generate_actions(), list)
