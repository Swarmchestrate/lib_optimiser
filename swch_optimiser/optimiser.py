from pathlib import Path
import datetime
from platform import node
import sys
import time

from minizinc import Instance, Model, Solver
from minizinc.error import MiniZincError

class SwchOptimiser:

    gecode = None
    model = None
    instance = None

    rule = None
    mslist = None
    error = None

    input_system = None
    input_constants = None
    input_metrics = None
    all_inputs = None

    reconfig_inputs = None
    reconfig_result = None
    elapsed_time = 0

    system_input_params_set = {
        "sys_node_count_max",
        "sys_pod_count_max",
        "sys_mapping_actual",
        "sys_node_count_actual"
    }
    system_outputs_params_set = {
        "sys_mapping_next",
        "sys_node_count_next",
        "sys_nodes_to_destroy"
    }
    
    def __init__(self, rule: str = None, mslist: list = None):
        """Initialize the SwchOrchInterpreter instance."""
        self.rule = rule
        self.mslist = mslist

        self.gecode = Solver.lookup("gecode")
        self.model = Model()
        self.model.add_string(self.rule)
        try:
            self.instance = Instance(self.gecode, self.model)
            self.error = self._check_system_naming()
        except MiniZincError as e:
            self.error = self._format_minizinc_error(e)

    def _check_system_naming(self):
        """A rule must use only one naming style for its system variables: either all
        plain ("sys_<varname>") or all microservice-prefixed ("<msname>_sys_<varname>")."""
        plain, prefixed = [], []
        for key in list(self.instance.input) + list(self.instance.output):
            split = self._split_system_key(key, self.system_input_params_set | self.system_outputs_params_set)
            if split is not None:
                (prefixed if split[0] else plain).append(key)
        if plain and prefixed:
            return ("Error: system variables must use only one naming style, either \"sys_<varname>\" "
                    "or \"<msname>_sys_<varname>\".\n"
                    f"\tplain: {', '.join(plain)}\n"
                    f"\tprefixed: {', '.join(prefixed)}")
        return None

    def _format_minizinc_error(self, err: MiniZincError) -> str:
        import re as _re
        location = getattr(err, "location", None)
        message = str(err)

        # Resolve line number: prefer location object, fall back to parsing
        # the raw message text (MiniZinc embeds it as "filename:lineno:" or
        # "filename:lineno.col-col:").
        line_no = None
        if location is not None:
            lines_attr = getattr(location, "lines", None)
            if lines_attr and lines_attr[0] > 0:
                line_no = lines_attr[0]

        if line_no is None:
            match = _re.search(r":(\d+)(?:\.\d+-\d+)?:", message)
            if match:
                line_no = int(match.group(1))

        if line_no is None:
            return f"Error: {message}"

        output = f"Error: {message} in line no. {line_no}\n"

        # Resolve the erroneous source line: try location.file first (for
        # .mzn files on disk), then fall back to the in-memory rule string.
        source_line = None
        file_path = getattr(location, "file", None) if location is not None else None
        if file_path is not None:
            try:
                file_lines = Path(str(file_path)).read_text().splitlines()
                if 1 <= line_no <= len(file_lines):
                    source_line = file_lines[line_no - 1]
            except Exception:
                pass

        if source_line is None and isinstance(self.rule, str):
            rule_lines = self.rule.splitlines()
            if 1 <= line_no <= len(rule_lines):
                source_line = rule_lines[line_no - 1]

        if source_line is not None:
            output += f"{line_no:>4}: {source_line}\n"
            columns = getattr(location, "columns", (0, 0)) if location is not None else (0, 0)
            if columns and columns[0] > 0:
                pointer = " " * (6 + columns[0] - 1) + "^"
                output += f"{pointer}\n"

        return output

    def get_error(self):
        return self.error

    def _split_system_key(self, key: str, param_set: set):
        """Split a system parameter name into (ms_prefix, base_name).
        The microservice name is everything before the first "_sys_" in the name
        ("audio_class_sys_mapping_actual" -> ("audio_class", "sys_mapping_actual")).
        A name starting with "sys_" has no microservice prefix and the prefix is "".
        Returns None if the key is not a system parameter of the given set."""
        idx = key.find("_sys_")
        if idx > 0:
            prefix, base = key[:idx], key[idx+1:]
        elif key.startswith("sys_"):
            prefix, base = "", key
        else:
            return None
        for param_name in param_set:
            if base.startswith(param_name):
                return (prefix, base)
        return None

    def _is_system_key(self, key: str, param_set: set):
        return self._split_system_key(key, param_set) is not None

    def _get_by_base_name(self, values: dict, base_name: str, param_set: set):
        """Return the value of the first key whose base name (prefix stripped) equals base_name."""
        for key, value in values.items():
            split = self._split_system_key(key, param_set)
            if split is not None and split[1] == base_name:
                return value
        return None

    def add_input_system(self, system: dict):
        self.input_system = system
        return

    def add_input_constants(self, constants: dict):
        self.input_constants = constants
        return
    
    def add_input_metrics(self, metrics: dict):
        self.input_metrics = metrics
        return

    def validate_inputs(self):
        #FIXME: implement validation of inputs (e.g., cross-check parameters with rule)
        self.all_inputs = {**(self.input_system or {}), **(self.input_constants or {}), **(self.input_metrics or {})}
        return

    def dump_extracted_parameters(self):
        print("\tSYSTEM inputs:")
        model_params = self.query_system_inputs()
        for param_name, param_info in model_params.items():
            print(f"\t\t{param_name}: {param_info}")
        print("\tSYSTEM outputs:")
        model_params = self.query_outputs()
        for param_name, param_info in model_params.items():
            print(f"\t\t{param_name}: {param_info}")
        print("\tAPPSPEC inputs:")
        model_params = self.query_appspec_inputs()
        for param_name, param_info in model_params.items():
            print(f"\t\t{param_name}: {param_info}")

    def query_system_inputs(self):
        all_inputs = self.instance.input        
        system_inputs = {}
        for key, value in all_inputs.items():
            if self._is_system_key(key, self.system_input_params_set):
                system_inputs[key] = value
        return system_inputs
    
    def query_appspec_inputs(self):
        all_inputs = self.instance.input
        appspec_inputs = {}
        for key, value in all_inputs.items():
            if not self._is_system_key(key, self.system_input_params_set):
                appspec_inputs[key] = value
        return appspec_inputs

    def query_outputs(self):
        all_outputs = self.instance.output
        system_outputs = {}
        for key, value in all_outputs.items():
            if self._is_system_key(key, self.system_outputs_params_set):
                system_outputs[key] = value
        return system_outputs

    def get_appspec_input_parameter_values(self):
        appspec_input_values = {}
        for param_name in self.all_inputs:
            if not self._is_system_key(param_name, self.system_input_params_set):
                appspec_input_values[param_name] = self.all_inputs[param_name]
        return appspec_input_values
    
    def dump_appspec_input_parameter_values(self):
        appspec_input_values = self.get_appspec_input_parameter_values()
        for param_name, param_value in appspec_input_values.items():
            print(f"\t\t{param_name}: {param_value}")

    def get_system_input_parameter_values(self):
        system_input_values = {}
        for param_name in self.all_inputs:
            if self._is_system_key(param_name, self.system_input_params_set):
                system_input_values[param_name] = self.all_inputs[param_name]
        return system_input_values

    def dump_system_input_parameter_values(self):
        system_input_values = self.get_system_input_parameter_values()
        for param_name, param_value in system_input_values.items():
            print(f"\t\t{param_name}: {param_value}")

    def get_system_output_parameter_values(self):
        system_output_values = {}
        for param_name, param_value in vars(self.reconfig_result.solution).items():
            if self._is_system_key(param_name, self.system_outputs_params_set):
                system_output_values[param_name] = param_value
        return system_output_values
    
    def dump_system_output_parameter_values(self):
        system_output_values = self.get_system_output_parameter_values()
        for param_name, param_value in system_output_values.items():
            print(f"\t\t{param_name}: {param_value}")

    def solve(self, time_limit_milliseconds=None, verbose=False):
        time_limit = None
        if time_limit_milliseconds is not None:
            time_limit = datetime.timedelta(milliseconds=time_limit_milliseconds)
        for key, value in (self.all_inputs or {}).items():
            self.instance[key] = value

        start_time = time.perf_counter()
        try:
            self.reconfig_result = self.instance.solve(time_limit=time_limit, verbose=verbose)
            self.error = None
        except MiniZincError as e:
            self.error = self._format_minizinc_error(e)
        end_time = time.perf_counter()

        self.elapsed_time = int((end_time - start_time) * 1000)
        return self.reconfig_result

    def time_taken(self):
        return self.elapsed_time
    
    def generate_actions(self):
        mapping_inputs = {}
        for key in self.query_system_inputs():
            prefix, base = self._split_system_key(key, self.system_input_params_set)
            if base.startswith("sys_mapping_actual"):
                mapping_inputs[key] = (prefix, base)
        mapping_outputs = {key for key in self.query_outputs()
                           if self._split_system_key(key, self.system_outputs_params_set)[1].startswith("sys_mapping_next")}

        node_count_actual = self._get_by_base_name(self.get_system_input_parameter_values(), "sys_node_count_actual", self.system_input_params_set)
        node_count_next = self._get_by_base_name(self.get_system_output_parameter_values(), "sys_node_count_next", self.system_outputs_params_set)
        actions = []

        if node_count_actual is not None and node_count_next is not None:
            #handle node scaling case
            if node_count_next > node_count_actual:
                for nodeid in range(node_count_actual+1, node_count_next+1):
                    actions.append(dict(action="create_node", name="", nodeid=nodeid))
            elif node_count_next < node_count_actual:
                for nodeid in range(node_count_next+1, node_count_actual+1):
                    actions.append(dict(action="destroy_node", name="", nodeid=nodeid))

        #the base model always declares the plain "sys_mapping_actual"/"sys_mapping_next"
        #pair, so their presence alone doesn't tell us whether the app rule is using the
        #single-microservice or the multiple-microservices ("sys_mapping_actual_X") pattern;
        #only the presence of suffixed keys does
        suffixed_mapping_inputs = {key: pb for key, pb in mapping_inputs.items() if pb[1] != "sys_mapping_actual"}

        for mapping_actual_key, (prefix, base) in (suffixed_mapping_inputs or mapping_inputs).items():
            mapping_next_key = mapping_actual_key.replace("sys_mapping_actual", "sys_mapping_next")
            if mapping_next_key not in mapping_outputs:
                continue
            if base != "sys_mapping_actual":
                #multiple microservices mapping case ("sys_mapping_actual_X")
                ms = base[len("sys_mapping_actual_"):]
            elif prefix:
                #microservice-prefixed mapping case ("X_sys_mapping_actual")
                ms = prefix
            else:
                #single microservice mapping case
                ms = self.mslist[0] if self.mslist else "undefined_ms"
            actions.extend(self.generate_actions_for_one_ms(ms, mi=mapping_actual_key, mf=mapping_next_key, prefix=prefix))

        return actions

    def generate_actions_for_one_ms(self, ms: str = "undefined_ms", mi: str = "sys_mapping_actual", mf: str = "sys_mapping_next", prefix: str = ""):
        actions = []
        max_pods = self.input_system[prefix+"_sys_pod_count_max" if prefix else "sys_pod_count_max"]
        mapping_init = self.input_system[mi]
        mapping_next = self.reconfig_result[mf]
        for p in range(max_pods):
            if mapping_init[p] != mapping_next[p]:
                if mapping_init[p] == 0 and mapping_next[p] > 0:
                    actions.append(dict(action="create_ms", name=ms, pod=p+1, node=mapping_next[p]))
                elif mapping_init[p] > 0 and mapping_next[p] == 0:
                    actions.append(dict(action="destroy_ms", name=ms, pod=p+1, node=mapping_init[p]))
                else:
                    actions.append(dict(action="destroy_ms", name=ms, pod=p+1, node=mapping_init[p]))
                    actions.append(dict(action="create_ms", name=ms, pod=p+1, node=mapping_next[p]))
        return actions
    
    def dump_actions(self, actions: list):
        for action in actions:
            name = "{:25s}".format("\""+action.get("name", "")+"\"")            
            if action["action"] == "create_ms":
                print(f"\tms {name} -> create a new pod on node \"{action['node']}\".")
            elif action["action"] == "destroy_ms":
                print(f"\tms {name} -> destroy the pod \"{action['pod']}\".")
            elif action["action"] == "create_node":
                print(f"\tvm {name} -> create new node \"{action['nodeid']}\".")
            elif action["action"] == "destroy_node":
                print(f"\tvm {name} -> destroy node \"{action['nodeid']}\".")
