# swch_optimiser

A Python wrapper around [MiniZinc](https://www.minizinc.org/) for solving system reconfiguration problems: given the current mapping of pods (microservice instances) to nodes plus an application-specific rule set, `SwchOptimiser` finds an optimal next mapping (including scaling nodes/pods up or down) and turns the result into a list of concrete actions (`create_ms`, `destroy_ms`, `create_node`, `destroy_node`).

Application-specific constants, parameters, constraints, and the optimisation goal are written in MiniZinc and passed in as a self-contained rule string, which must also declare the shared system parameters (`sys_*`) that every rule set builds on — see [Usage](#usage). A single rule can also decide about several microservices at once by prefixing the system parameters with the microservice name (`<msname>_sys_*`) — see [Multiple microservices in one rule](#multiple-microservices-in-one-rule).

## Requirements

- Python 3.12+
- A working [MiniZinc](https://www.minizinc.org/) installation with the [Gecode](https://www.gecode.org/) solver available on your system (`minizinc --solvers` should list `Gecode`)

## Installation

To use the published package in your own project, add it to your `requirements.txt`:

```
swchoptimiser==0.2.0
```

then `pip install -r requirements.txt`. Note that the **PyPI distribution name** (`swchoptimiser`) is not the same as the **Python import name** (`swch_optimiser`, with an underscore) — you install one, but import the other:

```python
from swch_optimiser import SwchOptimiser
```

`pip` also pulls in the `minizinc` Python package automatically as a dependency — you don't need to list it separately. It does **not** install MiniZinc/Gecode themselves; see [Requirements](#requirements) above.

To work on this repository itself, it uses [Poetry](https://python-poetry.org/):

```bash
poetry install
```

## Usage

Every rule string you pass in must be **self-contained**: `SwchOptimiser` does not inject any system parameters for you, so the rule needs to declare the reserved `sys_*` inputs/outputs itself, in addition to your application-specific constants, parameters, constraints, and optimisation goal.

```python
from swch_optimiser import SwchOptimiser

rule = r"""
    % --- SYSTEM PARAMETERS: required by every rule ---
    int: sys_pod_count_max;
    int: sys_node_count_max;
    int: sys_node_count_actual;
    array[1..sys_pod_count_max] of int: sys_mapping_actual;
    var 1..sys_node_count_max: sys_node_count_next :: add_to_output;
    array[1..sys_pod_count_max] of var 0..sys_node_count_max: sys_mapping_next :: add_to_output;
    var 0..sys_pod_count_max: sys_pod_count_next = sum(p in 1..sys_pod_count_max)(sys_mapping_next[p] > 0);
    int: sys_pod_count_actual = sum(p in 1..sys_pod_count_max)(sys_mapping_actual[p] > 0);

    % --- APPLICATION CONSTANTS ---
    float: threshold_min_node_load;
    float: threshold_max_node_load;
    % --- APPLICATION PARAMETERS ---
    array[1..sys_node_count_actual] of float: node_load;

    % keep node count fixed unless your rule explicitly scales it
    constraint sys_node_count_next = sys_node_count_actual;
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

### Multiple microservices in one rule

When one decision covers several microservices (e.g. choosing which of several alternative services should run, or balancing pods between them), declare a separate set of system parameters for **each** microservice, prefixed with the microservice name: `<msname>_sys_<varname>`. The microservice name is everything before the first `_sys_` in the variable name, so names containing underscores (e.g. `audio_class`) are fine, but a name must not itself contain `_sys_`.

```python
rule = r"""
    % --- SYSTEM PARAMETERS OF "norain" ---
    int: norain_sys_pod_count_max;
    int: norain_sys_node_count_max;
    int: norain_sys_node_count_actual;
    array[1..norain_sys_pod_count_max] of int: norain_sys_mapping_actual;
    var 1..norain_sys_node_count_max: norain_sys_node_count_next :: add_to_output;
    array[1..norain_sys_pod_count_max] of var 0..norain_sys_node_count_max: norain_sys_mapping_next :: add_to_output;
    var 0..norain_sys_pod_count_max: norain_sys_pod_count_next = sum(p in 1..norain_sys_pod_count_max)(norain_sys_mapping_next[p] > 0);
    int: norain_sys_pod_count_actual = sum(p in 1..norain_sys_pod_count_max)(norain_sys_mapping_actual[p] > 0);

    % --- SYSTEM PARAMETERS OF "heavy" ---
    int: heavy_sys_pod_count_max;
    % ... same declarations as above, prefixed with "heavy_" ...

    % --- APPLICATION PART: refer to the prefixed variables ---
    constraint norain_sys_node_count_next = norain_sys_node_count_actual;
    constraint heavy_sys_node_count_next = heavy_sys_node_count_actual;
    constraint norain_sys_pod_count_next + heavy_sys_pod_count_next >= 1;
    % ... additional constraints and loss ...
    solve minimize loss;
    """

optimiser = SwchOptimiser(rule, mslist=["norain", "heavy"])
optimiser.add_input_system({
    "norain_sys_pod_count_max": 5,
    "norain_sys_node_count_max": 5,
    "norain_sys_node_count_actual": 5,
    "norain_sys_mapping_actual": [1, 0, 0, 0, 0],
    "heavy_sys_pod_count_max": 5,
    "heavy_sys_node_count_max": 5,
    "heavy_sys_node_count_actual": 5,
    "heavy_sys_mapping_actual": [0, 0, 0, 0, 0],
})
```

`generate_actions()` then produces `create_ms`/`destroy_ms` actions per microservice, with the action's `name` set to the prefix (`"norain"`, `"heavy"`). See [`examples/demo_fuelics_wastewater.py`](examples/demo_fuelics_wastewater.py) for a complete example.

Things to keep in mind:

- **Backward compatible:** if the rule handles only one microservice, nothing changes — keep using the plain `sys_*` names as shown above; the prefix is only needed when there are multiple microservices. In that case the action `name` is taken from `mslist[0]`.
- **Don't mix naming styles:** a rule must use either only plain `sys_*` names or only prefixed `<msname>_sys_*` names. Mixing them is reported by `get_error()` right after construction, listing the offending variables.
- **Node scaling:** `create_node`/`destroy_node` actions are derived from a single `<msname>_sys_node_count_actual`/`<msname>_sys_node_count_next` pair. If your rule scales nodes, constrain the node counts of all microservices to be equal (or keep them fixed, as above).

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
| `SwchOptimiser(rule: str, mslist: list = None)` | Builds the MiniZinc model from your self-contained `rule` string (see [Usage](#usage) — it must declare the `sys_*` — or, for multiple microservices, `<msname>_sys_*` — system parameters itself) and instantiates it against the Gecode solver. Any MiniZinc build error is captured, not raised — check `get_error()` afterward. |

### Input setup

| Call | Description |
|---|---|
| `add_input_system(system: dict)` | Sets the `sys_*` (or `<msname>_sys_*`) values (pod/node limits, actual mapping, etc.). |
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
| `generate_actions()` | Diffs actual vs. next mapping (and node count) into a list of action dicts: `create_ms`, `destroy_ms`, `create_node`, `destroy_node`. Handles both single-microservice (`sys_mapping_actual`/`sys_mapping_next`) and multi-microservice (`<name>_sys_mapping_actual`/`<name>_sys_mapping_next`) rule patterns; the older `sys_mapping_actual_<name>`/`sys_mapping_next_<name>` suffix pattern is still recognised. |
| `generate_actions_for_one_ms(ms="undefined_ms", mi="sys_mapping_actual", mf="sys_mapping_next", prefix="")` | Lower-level helper `generate_actions()` calls per microservice; usable directly if you want to diff a specific mapping pair yourself. Pass the microservice `prefix` when using prefixed names, so `<prefix>_sys_pod_count_max` is used as the pod limit. |
| `dump_actions(actions: list)` | Pretty-prints an actions list. |

### Introspection / debugging helpers

| Call | Description |
|---|---|
| `query_system_inputs()` | Dict of declared MiniZinc params matching the reserved `sys_*` / `<msname>_sys_*` input names. |
| `query_appspec_inputs()` | Dict of declared MiniZinc params that are *not* system params (i.e. your app's constants/metrics). |
| `query_outputs()` | Dict of declared MiniZinc output params matching reserved `sys_*` / `<msname>_sys_*` output names. |
| `get_system_input_parameter_values()` | Actual values you supplied for system inputs. |
| `get_appspec_input_parameter_values()` | Actual values you supplied for app-specific inputs. |
| `get_system_output_parameter_values()` | Solved values for system outputs (reads `reconfig_result.solution`). |
| `dump_extracted_parameters()` | Prints system inputs, system outputs, and appspec inputs as declared in the model (pre-solve). |
| `dump_system_input_parameter_values()` / `dump_appspec_input_parameter_values()` / `dump_system_output_parameter_values()` | Print counterparts of the `get_*` methods above. |

## License

MIT — see [LICENSE](LICENSE).
