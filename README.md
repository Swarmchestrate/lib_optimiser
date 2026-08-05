# swch_optimiser

A Python wrapper around [MiniZinc](https://www.minizinc.org/) for solving system reconfiguration problems: given the current mapping of pods (microservice instances) to nodes plus an application-specific rule set, `SwchOptimiser` finds an optimal next mapping (including scaling nodes/pods up or down) and turns the result into a list of concrete actions (`create_ms`, `destroy_ms`, `create_node`, `destroy_node`).

Application-specific constraints and the optimisation goal are written in MiniZinc and passed in as a rule string; the library supplies the shared system parameters (`sys_*`) that every rule set builds on.

## Requirements

- Python 3.12+
- A working [MiniZinc](https://www.minizinc.org/) installation with the [Gecode](https://www.gecode.org/) solver available on your system (`minizinc --solvers` should list `Gecode`)

## Installation

This project uses [Poetry](https://python-poetry.org/):

```bash
poetry install
```

## Usage

```python
from swch_optimiser import SwchOptimiser

rule = r"""
    % --- APPLICATION CONSTANTS ---
    float: threshold_min_node_load;
    float: threshold_max_node_load;
    % --- APPLICATION PARAMETERS ---
    array[1..sys_node_count_actual] of float: node_load;

    constraint sys_pod_count_next >= 1;
    % ... additional constraints ...

    var int: loss = 100 * sum(p in 1..sys_pod_count_max)(bool2int(sys_mapping_next[p] != sys_mapping_actual[p]));
    solve minimize loss;
    """

optimiser = SwchOptimiser(rule, mslist=["my-service"])
if optimiser.get_error() is not None:
    raise SystemExit(optimiser.get_error())

optimiser.add_input_system({
    "sys_pod_count_max": 14,
    "sys_node_count_max": 10,
    "sys_node_count_actual": 3,
    "sys_mapping_actual": [1, 1, 2, 2, 3, 0, 0, 0, 0, 0, 0, 0, 0, 0],
})
optimiser.add_input_constants({
    "threshold_min_node_load": 40.0,
    "threshold_max_node_load": 70.0,
})
optimiser.add_input_metrics({
    "node_load": [30.0, 30.0, 30.0],
})
optimiser.validate_inputs()

result = optimiser.solve(time_limit_milliseconds=None)
if result is not None and result.solution is not None:
    for action in optimiser.generate_actions():
        print(action)
```

More complete, runnable examples for different use cases are in [`examples/`](examples/):

- `demo_nodescaling.py`
- `demo_fuelics_wastewater.py`
- `demo_innorenew_sound_processing.py`
- `demo_ust_forest_dt.py`

Run any of them with:

```bash
poetry run python examples/demo_nodescaling.py
```

## API reference

The public API is a single class, `SwchOptimiser`, exported from `swch_optimiser`.

### Constructor

| Call | Description |
|---|---|
| `SwchOptimiser(rule_app: str, mslist: list = None)` | Builds the MiniZinc model (`rule_sys` + your `rule_app`) and instantiates it against the Gecode solver. Any MiniZinc build error is captured, not raised — check `get_error()` afterward. |

### Input setup

| Call | Description |
|---|---|
| `add_input_system(system: dict)` | Sets the `sys_*` values (pod/node limits, actual mapping, etc.). |
| `add_input_constants(constants: dict)` | Sets app-specific constants (e.g. thresholds). |
| `add_input_metrics(metrics: dict)` | Sets app-specific live metrics (e.g. load, temperature). |
| `validate_inputs()` | Merges system + constants + metrics into `all_inputs`. **Must be called before `solve()`** — nothing validates parameters against the rule yet. |

### Solving

| Call | Description |
|---|---|
| `solve(time_limit_milliseconds=None, verbose=False)` | Assigns `all_inputs` onto the MiniZinc instance and solves. Returns the `minizinc.Result` (or `None` on error — check `get_error()`). Records elapsed time. |
| `time_taken()` | Milliseconds the last `solve()` call took. |
| `get_error()` | Returns the formatted error string from construction or solving, or `None`. |

### Reading back results / actions

| Call | Description |
|---|---|
| `generate_actions()` | Diffs actual vs. next mapping (and node count) into a list of action dicts: `create_ms`, `destroy_ms`, `create_node`, `destroy_node`. Handles both single-microservice (`sys_mapping_actual`/`sys_mapping_next`) and multi-microservice (`sys_mapping_actual_<name>`/`sys_mapping_next_<name>`) rule patterns. |
| `generate_actions_for_one_ms(ms="undefined_ms", mi="sys_mapping_actual", mf="sys_mapping_next")` | Lower-level helper `generate_actions()` calls per microservice; usable directly if you want to diff a specific mapping pair yourself. |
| `dump_actions(actions: list)` | Pretty-prints an actions list. |

### Introspection / debugging helpers

| Call | Description |
|---|---|
| `query_system_inputs()` | Dict of declared MiniZinc params matching the reserved `sys_*` input names. |
| `query_appspec_inputs()` | Dict of declared MiniZinc params that are *not* system params (i.e. your app's constants/metrics). |
| `query_outputs()` | Dict of declared MiniZinc output params matching reserved `sys_*` output names. |
| `get_system_input_parameter_values()` | Actual values you supplied for system inputs. |
| `get_appspec_input_parameter_values()` | Actual values you supplied for app-specific inputs. |
| `get_system_output_parameter_values()` | Solved values for system outputs (reads `reconfig_result.solution`). |
| `dump_extracted_parameters()` | Prints system inputs, system outputs, and appspec inputs as declared in the model (pre-solve). |
| `dump_system_input_parameter_values()` / `dump_appspec_input_parameter_values()` / `dump_system_output_parameter_values()` | Print counterparts of the `get_*` methods above. |

## License

MIT — see [LICENSE](LICENSE).
