'''
    This is a Proof-of-Concept implementation of Aleph Zero consensus protocol.
    Copyright (C) 2019 Aleph Zero Team
    
    This program is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License as published by the Free Software Foundation, either version 3 of the License, or
    (at your option) any later version.
    This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU General Public License for more details.
    
    You should have received a copy of the GNU General Public License
    along with this program. If not, see <http://www.gnu.org/licenses/>.
'''

import random
from itertools import product
from .dag import DAG
from aleph.data_structures import Poset, Unit



def forking_processes_in_lower_cone(dag, node):
    '''
    :returns: the list of all process_ids of processes that can be proved forking in dag given the lower cone of node.
    '''
    cone = dag.nodes_below(node)
    forkers = []
    for process_id in range(dag.n_processes):
        cone_restricted_to_process_id = [node for node in cone if dag.pid(node) == process_id]
        maximal_per_process = dag.compute_maximal_from_subset(cone_restricted_to_process_id)
        if len(maximal_per_process) > 1:
            forkers.append(process_id)
    return forkers



def check_forker_muting(dag, parents):
    '''
    Checks whether the forker_muting rule is satisfied by a node with specified parents in dag.
    See also the comment regarding forker_muting in poset.py.
    '''
    all_forkers_with_evidence = []
    for U in parents:
        all_forkers_with_evidence.extend(forking_processes_in_lower_cone(dag, U))
    all_forkers_with_evidence = set(all_forkers_with_evidence)
    return all(dag.pid(U) not in all_forkers_with_evidence for U in parents)



def check_distinct_parent_processes(dag, parents):
    '''
    Checks whether all parents are created by different processes.
    '''
    return len(parents) == len(set(dag.pid(parent) for parent in parents))


def check_expand_primes(dag, node_self_predecessor, node_parents):
    '''
    Checks whether the expand_primes rules is satisfied for a given node. See the comment under check_expand_primes in poset.py.
    '''
    level = dag.levels[node_self_predecessor]
    prime_units = dag.prime_units_by_level[level]
    visible_prime_units = set()
    for parent in node_parents:
        if dag.levels[parent] > level:
            level = dag.levels[parent]
            prime_units = dag.prime_units_by_level[level]
            visible_prime_units = set()
        new_visible_prime_units = set()
        for prime_unit in prime_units:
            if dag.is_reachable(prime_unit, parent):
                new_visible_prime_units.add(prime_unit)
        if new_visible_prime_units <= visible_prime_units:
            return False
        visible_prime_units.update(new_visible_prime_units)
    return True


def check_introduce_new_fork(dag, pid, self_predecessor):
    '''
    Checks whether a node is forking. Only the pid and the self_predecessor of the node are required to check this.
    '''
    assert self_predecessor is not None
    return self_predecessor not in dag.maximal_units_per_process(pid)



def check_new_unit_correctness(dag, new_unit_pid, new_unit_parents, forkers):
    '''
    Check whether the new unit does not introduce a diamond structure.
    :returns: the self_predecessor of new_unit if adding new_unit is correct and False otherwise.
    '''

    self_predecessor = dag.self_predecessor(new_unit_pid, new_unit_parents)

    if self_predecessor is None:
        return False

    parent_ids = set()
    for parent in new_unit_parents:
        if dag.pid(parent) in parent_ids:
            return False
        parent_ids.add(dag.pid(parent))

    if new_unit_pid not in forkers and check_introduce_new_fork(dag, new_unit_pid, self_predecessor):
        return False

    return self_predecessor


#======================================================================================================================


def generate_random_nonforking(n_processes, n_units, file_name = None):
    '''
    Generate a random non-forking poset with n_processes processes and optionally save it to file_name.
    :param int n_processes: the number of processes in poset
    :param int n_units: the number of units in the process beyond n_processes initial units,
                        hence the total number of units is (n_processes + n_units)
    :returns: a DAG instance
    '''
    process_heights = [0] * n_processes
    dag = DAG(n_processes)
    for process_id in range(n_processes):
        dag.add(generate_unit_name(0, process_id), process_id, [])

    for _ in range(n_units):
        process_id = random.choice(range(n_processes))
        all_but_process_id = [i for i in range(n_processes) if i != process_id]
        parent_processes = [process_id] + random.sample(all_but_process_id , 1)
        unit_height = process_heights[process_id] + 1
        unit_name = generate_unit_name(unit_height, process_id)
        dag.add(unit_name, process_id, [generate_unit_name(process_heights[i], i) for i in parent_processes])
        process_heights[process_id] += 1

    if file_name:
        dag_to_file(dag, file_name)
    return dag



def generate_random_forking(n_processes, n_units, n_forkers, file_name = None):
    '''
    Generates a random poset with n_processes processes, of which n_forkers are forking and saves it to file_name.
    There are no "diamonds" within forking processes, in other words the forking processes can only create trees.
    :param int n_processes: the number of processes in poset
    :param int n_forkers: the number of forking processes
    :param int n_units: the number of units in the process beyond the n_processes initial units,
                        hence the total number of units is (n_processes + n_units)
    :returns: a DAG instance
    '''
    forkers = random.sample(range(n_processes), n_forkers)
    node_heights = {}
    dag = DAG(n_processes)

    for process_id in range(n_processes):
        unit_name = generate_unit_name(0, process_id)
        dag.add(unit_name, process_id, [])
        node_heights[unit_name] = 0

    while len(dag) < n_processes + n_units:
        process_id = random.choice(range(n_processes))
        new_unit_first_parent = random.choice([U for U in dag if dag.pid(U) == process_id])
        new_unit_parents = [new_unit_first_parent] + [random.choice(list(dag.nodes.keys()))]
        self_predecessor = check_new_unit_correctness(dag, process_id, new_unit_parents, forkers)
        if not self_predecessor:
            continue
        new_unit_height = node_heights[self_predecessor] + 1
        new_unit_neighbours = nodes_by_process_height(dag, node_heights, process_id, new_unit_height)
        new_unit_no = len(new_unit_neighbours)
        if new_unit_no > 0:
            #make sure this is a real fork, not just an old one under a different name
            spork = False
            for n in new_unit_neighbours:
                if dag.nodes[n] == new_unit_parents:
                    spork = True
            if spork:
                continue
        unit_name = generate_unit_name(new_unit_height, process_id, new_unit_no)
        dag.add(unit_name, process_id, new_unit_parents)
        node_heights[unit_name] = new_unit_height

    if file_name:
        dag_to_file(dag, file_name)

    return dag


def generate_random_compliant_unit(dag, n_processes, process_id = None):
    '''
    Generates a random compliant unit created by a given process_id (or random process if no process_id provided).
    :param DAG dag: the dag of interest
    :param int n_processes: the number of processes in dag
    :param int process_id: the process_id of the unit creator
    :returns: a pair (node, parents) -- the name of the new unit and its list of parents
    '''
    if process_id is None:
        process_id = random.choice(range(n_processes))
    maximal_nodes = []
    for process_gen_id in range(n_processes):
        maximal_nodes.extend(dag.maximal_units_per_process(process_gen_id))
    unit_pairs = list(product(maximal_nodes, repeat=2))

    random.shuffle(unit_pairs)

    for U1, U2 in unit_pairs:
        new_unit_parents = [U1, U2]
        self_predecessor = dag.self_predecessor(process_id, new_unit_parents)
        if self_predecessor is None:
            continue

        if check_introduce_new_fork(dag, process_id, self_predecessor):
            continue

        if not check_expand_primes(dag, self_predecessor, new_unit_parents):
            continue

        if not check_forker_muting(dag, new_unit_parents):
            continue

        if not check_distinct_parent_processes(dag, new_unit_parents):
            continue

        return generate_unused_name(dag, process_id), new_unit_parents

    return None



def generate_random_violation(n_processes, n_correct_units, n_forkers, ensure, violate):
    '''
    Generates a dag that has a certain number of units that satisfy a prespecified set of rules, and the last unit is a violation.
    :param int n_processes: the number of processes in the dag
    :param int n_correct_units: the number of initial correct units (satisfying rules) that are supposed to be generated
    :param int n_forkers: the number of forking processes
    :param dict ensure: a dict of the form {property -> bool} that specifies the set of constraints that should be satisfied for all nodes in the poset
    :param dict violate: a dict of the form {property -> bool} that specifies how the last unit should violate the constraints
    :returns: A pair (dag, unit_list) the created dag, and the list of its nodes in topological order (with the last being the violation)
    '''
    forkers = random.sample(range(n_processes), n_forkers)
    node_heights = {}
    dag = DAG(n_processes)
    topological_list = []

    for process_id in range(n_processes):
        unit_name = generate_unit_name(0, process_id)
        dag.add(unit_name, process_id, [])
        node_heights[unit_name] = 0
        topological_list.append(unit_name)

    it = 0
    terminate_poset = False
    while not terminate_poset:
        it += 1
        assert it < 1000*(n_processes + n_correct_units), "The random process had troubles to terminate."
        assert len(dag) < 100*(n_processes + n_correct_units), "The random process had troubles to terminate."

        process_id = random.choice(range(n_processes))
        new_unit_first_parent = random.choice([U for U in dag if dag.pid(U) == process_id])
        new_unit_parents = [new_unit_first_parent] + [random.choice(list(dag.nodes.keys()))]
        self_predecessor = dag.self_predecessor(process_id, new_unit_parents)
        if self_predecessor is None:
            continue
        if process_id not in forkers and check_introduce_new_fork(dag, process_id, self_predecessor):
            continue

        property_table = {}
        property_table['forker_muting'] = check_forker_muting(dag, new_unit_parents)
        property_table['distinct_parents'] = check_distinct_parent_processes(dag, new_unit_parents)
        property_table['expand_primes'] = check_expand_primes(dag, self_predecessor, new_unit_parents)

        if len(dag) >= n_processes + n_correct_units and constraints_satisfied(violate, property_table):
            terminate_poset = True
        elif constraints_satisfied(ensure, property_table):
            pass
        else:
            #cannot add this node to graph
            continue

        new_unit_height = node_heights[self_predecessor] + 1
        new_unit_neighbours = nodes_by_process_height(dag, node_heights, process_id, new_unit_height)
        new_unit_no = len(new_unit_neighbours)
        if new_unit_no > 0:
            #make sure this is a real fork, not just an old one under a different name
            spork = False
            for n in new_unit_neighbours:
                if dag.nodes[n] == new_unit_parents:
                    spork = True
            if spork:
                continue
        unit_name = generate_unit_name(new_unit_height, process_id, new_unit_no)
        dag.add(unit_name, process_id, new_unit_parents)
        node_heights[unit_name] = new_unit_height
        topological_list.append(unit_name)


    return dag, topological_list


#======================================================================================================================


def generate_unit_name(unit_height, process_id, parallel_no = 0):
    '''
    Generate a new unit name deterministically depending on its process_id, height and how many other forks are there at this height.
    '''
    if parallel_no == 0:
        name = "%d,%d" % (unit_height, process_id)
    else:
        name = "%d,%d,%d" % (unit_height, process_id, parallel_no)
    return name

def generate_unused_name(dag, process_id):
    '''
    Generates a random string name for a node, that does not yet exist in dag.
    '''
    name = ""
    name_len = 0
    while str(process_id)+"-"+name in dag:
        name_len += 1
        name = ''.join(random.sample('ABCDEFGHIJKLMNOPQRSTUVWXYZ', name_len))

    return str(process_id)+"-"+name



def nodes_by_process_height(dag, node_heights, process_id, height):
    '''
    Finds nodes by process id and height.
    :param DAG dag: the considered dag
    :param dict node_heights: the dictionary of the form {node -> int} giving heights of nodes
    :param int process_id: the process_id of the process the nodes should be created by
    :param int height: the target height of the nodes
    :returns: the set of all nodes in the dag that are created by a specific process and have a specific height
    '''
    return [node for node in node_heights if (dag.pid(node) == process_id and height == node_heights[node])]


def constraints_satisfied(constraints, truth):
    '''
    Checks satisfaction of a set constraints.
    :param dict constraints: a dictionary of the form {property -> bool} that specifies the constraints
    :param dict truth: a dictionary of the form {property -> bool} that gives the values for the properties to check
    :returns: True or False depending on whether all constraints are satisfied.
    '''
    return all(truth[i] == constraints[i] for i in constraints)



#======================================================================================================================
#======================================================================================================================
#======================================================================================================================



def poset_from_dag(dag):
    '''
    Generates a poset from a given dag.
    :returns: a pair (poset, unit_dict), where unit_dict is a dict of the form {name_in_dag -> unit} binding units in the new poset with nodes in dag
    '''
    poset = Poset(n_processes = dag.n_processes, use_tcoin = False)
    unit_dict = {}

    for unit_name in dag.sorted():
        creator_id = dag.pid(unit_name)
        assert 0 <= creator_id <= dag.n_processes - 1, "Incorrect process id"

        assert unit_name not in unit_dict, "Duplicate unit name %s" % unit_name
        for parent in dag.parents(unit_name):
            assert parent in unit_dict, "Parent %s of unit %s not known" % (parent, unit_name)

        U = Unit(creator_id = creator_id, parents = [unit_dict[parent] for parent in dag.parents(unit_name)],
                txs = [])
        poset.prepare_unit(U)
        poset.add_unit(U)
        unit_dict[unit_name] = U

    return poset, unit_dict



def create_node_line(node, process_id, parents):
    '''
    Forms a line representing one node (of a dag) in the file.
    '''
    line = '%s %d' % (node, process_id)
    for parent in parents:
        line += ' ' + parent
    line += '\n'
    return line



def dag_to_file(dag, file_name):
    '''
    Saves a dag to a file in the "standard" format.
    '''
    topological_list = dag.sorted()
    with open(file_name, 'w') as f:
        f.write("format standard\n")
        f.write('%d\n' % dag.n_processes)
        for node in topological_list:
            f.write(create_node_line(node, dag.pid(node), dag.parents(node)))


def dag_from_poset(poset):
    '''
    Converts a poset into a dag.
    :returns: a pair (dag, unit_to_name), where unit_to_name is a dict of the form {unit -> name_in_dag} binding units in the dag with nodes in poset
    '''
    dag = DAG(poset.n_processes)
    unit_to_name = {}
    for _ in poset.units.items():
        for U_hash, U in poset.units.items():
            if U in unit_to_name:
                continue
            if all((unit_to_name[V] in dag) for V in U.parents):
                new_name = generate_unused_name(dag, U.creator_id)
                dag.add(new_name, U.creator_id, [unit_to_name[V] for V in U.parents])
                unit_to_name[U] = new_name

    return dag, unit_to_name


def read_dag_standard(poset_stream):
    '''
    Read a dag from stream in the standard format.
    :returns: a DAG
    '''
    lines = [line.decode('ascii') for line in poset_stream.readlines()]

    n_processes = int(lines[0])
    dag = DAG(n_processes)

    for line in lines[1:]:
        tokens = line.split()
        unit_name = tokens[0]
        creator_id = int(tokens[1])
        assert 0 <= creator_id <= n_processes - 1, "Incorrect process id"
        parents = tokens[2:]
        assert unit_name not in dag, "Duplicate unit name %s" % unit_name
        for parent in parents:
            assert parent in dag, "Parent %s of a unit %s not known" % (parent, unit_name)

        dag.add(unit_name, creator_id, parents)

    return dag


def read_dag_poset_dump(poset_stream):
    '''
    Read a dag from stream in the dump-nofork-level-timing format.
    :returns: a DAG
    '''
    _, process_id = _parse_line(poset_stream.readline())
    process_id = int(process_id)
    _, n_processes = _parse_line(poset_stream.readline())
    n_processes = int(n_processes)
    _, n_units = _parse_line(poset_stream.readline())
    n_units = int(n_units)

    dag = DAG(n_processes, no_forkers = True)

    for unit_no in range(n_units):
        name, creator_id = _parse_line(poset_stream.readline())
        assert name not in dag, f"Duplicate node name {name}"
        creator_id = int(creator_id)
        parents = _parse_line(poset_stream.readline())[1:]
        assert all(node in dag for node in parents), "Not all parent nodes present in dag."
        _, level = _parse_line(poset_stream.readline())
        level = int(level)
        _, is_timing = _parse_line(poset_stream.readline())
        is_timing = int(is_timing)
        dag.add(name, creator_id, parents, level_hint = level, aux_info = {'timing': is_timing})

    return dag


def dag_from_stream(poset_stream):
    '''
    Reads the dag from a binary input stream.
    :returns: a DAG
    '''
    token, file_format = _parse_line(poset_stream.readline())
    assert token == 'format', "The first line does not specify the format."

    if file_format == 'standard':
        return read_dag_standard(poset_stream)
    if file_format == 'dump-nofork-level-timing':
        return read_dag_poset_dump(poset_stream)

    assert False, f"Format {file_format} not supported."



def dag_from_file(file_name):
    '''
    Reads a dag from file.
    :returns: a DAG
    '''
    # read as binary file, to be consistent with what dag_from_stream expects
    with open(file_name, mode = 'rb') as poset_file:
        dag = dag_from_stream(poset_file)
    return dag


def _parse_line(line):
    return line.decode('ascii').strip().split()
