from swch_optimiser import SwchOptimiser

MINIMAL_RULE = r"""
    solve satisfy;
    """


def test_invalid_rule_reports_error_with_line_number():
    optimiser = SwchOptimiser(rule_app="this is not valid minizinc syntax;")

    assert optimiser.get_error() is not None
    assert "line no." in optimiser.get_error()


def test_valid_minimal_model_has_no_error():
    optimiser = SwchOptimiser(rule_app=MINIMAL_RULE)

    assert optimiser.get_error() is None


def test_solve_produces_a_result_and_actions_for_simple_scaling():
    rule = r"""
        constraint sys_pod_count_next >= 1;
        var int: loss = sum(p in 1..sys_pod_count_max)(bool2int(sys_mapping_next[p] != sys_mapping_actual[p]));
        solve minimize loss;
        """
    optimiser = SwchOptimiser(rule_app=rule, mslist=["svc"])
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
