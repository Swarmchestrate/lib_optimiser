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

    rule_sys = """
    % --- SYSTEM PARAMETERS: DO NOT CHANGE, ONLY REFER TO THESE VARIABLES ---
    % --- INPUTS ---
    int: sys_pod_count_max; % hard limit for the number of pods (must be >= actual pod count)
    int: sys_node_count_max; % hard limit for the number of nodes (must be >= actual node count)
    int: sys_node_count_actual; % number of nodes currently existing in the system
    array[1..sys_pod_count_max] of int: sys_mapping_actual; % 0: non-existent, otherwise node index
    % --- OUTPUTS ---
    var 1..sys_node_count_max: sys_node_count_next :: add_to_output;
    array[1..sys_pod_count_max] of var 0..sys_node_count_max: sys_mapping_next :: add_to_output; % 0: non-existent, otherwise node index
    % --- SYSTEM PARAMETERS ENDS HERE ---

    var 0..sys_pod_count_max: sys_pod_count_next = sum(p in 1..sys_pod_count_max)(sys_mapping_next[p] > 0);
    int: sys_pod_count_actual = sum(p in 1..sys_pod_count_max)(sys_mapping_actual[p] > 0);
    """

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
    
    def __init__(self, rule_app: str = None, mslist: list = None):
        """Initialize the SwchOrchInterpreter instance."""
        self.rule = self.rule_sys + rule_app
        self.mslist = mslist

        self.gecode = Solver.lookup("gecode")
        self.model = Model()
        self.model.add_string(self.rule)
        try:
            self.instance = Instance(self.gecode, self.model)
            self.error = None   
        except MiniZincError as e:
            self.error = self._format_minizinc_error(e)

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
            for param_name in self.system_input_params_set:
                if key.startswith(param_name):
                    system_inputs[key] = value
        return system_inputs
    
    def query_appspec_inputs(self):
        all_inputs = self.instance.input
        appspec_inputs = {}
        for key, value in all_inputs.items():
            for param_name in self.system_input_params_set:
                if key.startswith(param_name):
                    break
            else:
                appspec_inputs[key] = value
        return appspec_inputs

    def query_outputs(self):
        all_outputs = self.instance.output
        system_outputs = {}
        for key, value in all_outputs.items():
            for param_name in self.system_outputs_params_set:
                if key.startswith(param_name):
                    system_outputs[key] = value
                    break
        return system_outputs

    def get_appspec_input_parameter_values(self):
        appspec_input_values = {}
        for param_name in self.all_inputs:
            for system_input_param in self.system_input_params_set:
                if param_name.startswith(system_input_param):
                    break
            else:
                appspec_input_values[param_name] = self.all_inputs[param_name]
        return appspec_input_values
    
    def dump_appspec_input_parameter_values(self):
        appspec_input_values = self.get_appspec_input_parameter_values()
        for param_name, param_value in appspec_input_values.items():
            print(f"\t\t{param_name}: {param_value}")

    def get_system_input_parameter_values(self):
        system_input_values = {}
        for param_name in self.all_inputs:
            for system_input_param in self.system_input_params_set:
                if param_name.startswith(system_input_param):
                    system_input_values[param_name] = self.all_inputs[param_name]
                    break
        return system_input_values

    def dump_system_input_parameter_values(self):
        system_input_values = self.get_system_input_parameter_values()
        for param_name, param_value in system_input_values.items():
            print(f"\t\t{param_name}: {param_value}")

    def get_system_output_parameter_values(self):
        system_output_values = {}
        for param_name, param_value in vars(self.reconfig_result.solution).items():
            for system_output_param in self.system_outputs_params_set:
                if param_name.startswith(system_output_param):
                    system_output_values[param_name] = param_value
                    break
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
        mapping_inputs = {key: value for (key, value) in self.query_system_inputs().items() if key.startswith("sys_mapping_actual")}
        mapping_outputs = {key: value for (key, value) in self.query_outputs().items() if key.startswith("sys_mapping_next")}

        node_count_actual = self.get_system_input_parameter_values().get("sys_node_count_actual", None)
        node_count_next = self.get_system_output_parameter_values().get("sys_node_count_next", None)
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
        suffixed_mapping_inputs = {key: value for key, value in mapping_inputs.items() if key != "sys_mapping_actual"}

        if not suffixed_mapping_inputs and ("sys_mapping_actual" in mapping_inputs) and ("sys_mapping_next" in mapping_outputs):
            #handle single microservice mapping case
            actions.extend(self.generate_actions_for_one_ms(self.mslist[0] if self.mslist else "undefined_ms", mi="sys_mapping_actual", mf="sys_mapping_next"))
        else:
            #handle multiple microservices mapping case (if there are multiple "sys_mapping_actual_X" and "sys_mapping_next_X" parameters)
            for mapping_actual_key in suffixed_mapping_inputs:
                mapping_next_key = mapping_actual_key.replace("sys_mapping_actual", "sys_mapping_next")
                if mapping_next_key in mapping_outputs:
                    ms = f"{mapping_actual_key.split('_')[-1]}"
                    actions.extend(self.generate_actions_for_one_ms(ms, mi=mapping_actual_key, mf=mapping_next_key))
        
        return actions

    def generate_actions_for_one_ms(self, ms: str = "undefined_ms", mi: str = "sys_mapping_actual", mf: str = "sys_mapping_next"):
        actions = []
        max_pods = self.input_system["sys_pod_count_max"]
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
