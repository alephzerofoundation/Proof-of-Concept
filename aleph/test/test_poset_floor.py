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

from aleph.data_structures import Unit, Poset
from aleph.utils import dag_utils
from aleph.utils.generic_test import generate_and_check_dag
import random

def create_poset_foundation(n_processes):
    '''
    Creates a layer of n_processes dealing units and adds them to a poset.
    :returns: the resulting poset
    '''
    poset = Poset(n_processes = n_processes, use_tcoin = False)
    empty_floor = [[] for _ in range(n_processes)]

    bottom_units_per_process = [Unit(creator_id = i, parents = [], txs = []) for i in range(n_processes)]
    for i in range(n_processes):
        poset.prepare_unit(bottom_units_per_process[i])
        poset.add_unit(bottom_units_per_process[i])
    return poset

def test_trivial_single_level():
    '''
    Tests floors for dealing units.
    '''
    n_processes = 4
    poset = create_poset_foundation(n_processes)
    for i in range(n_processes):
        checkedUnit = poset.max_units_per_process[i][0]
        for j in range(n_processes):
            assert checkedUnit.floor[j] == ([checkedUnit] if j == i else [])


def test_simple_tower():
    '''
    A simple manual test for floors.
    '''
    n_processes = 4
    poset = create_poset_foundation(n_processes)

    foundation_units = [unit[0] for unit in poset.max_units_per_process]

    U01 = Unit(creator_id = 0, parents = [foundation_units[0], foundation_units[1]], txs = [])
    poset.prepare_unit(U01)
    poset.add_unit(U01)
    U02 = Unit(creator_id = 0, parents = [U01, foundation_units[2]], txs = [])
    poset.prepare_unit(U02)
    poset.add_unit(U02)
    U03 = Unit(creator_id = 0, parents = [U02, foundation_units[3]], txs = [])
    poset.prepare_unit(U03)
    poset.add_unit(U03)
    for j in range(n_processes):
        assert U03.floor[j] == ([U03] if j == 0 else [foundation_units[j]])
    assert U02.floor == [[U02], [foundation_units[1]], [foundation_units[2]], []]
    assert U01.floor == [[U01], [foundation_units[1]], [], []]
    for i in range(n_processes):
        for j in range(n_processes):
            assert foundation_units[i].floor[j] == ([foundation_units[i]] if j == i else [])

def check_all_floors(dag):
    '''
    Given a dag, a poset is generated and the floor of every unit is tested against the implementation in DAG.
    '''
    poset, unit_dict = dag_utils.poset_from_dag(dag)
    for nodeU, U in unit_dict.items():
        for [tile, other] in zip(U.floor, [[unit_dict[nodeV] for nodeV in nodes] for nodes in dag.floor(nodeU)]):
            assert set(tile) == set(other)

def test_small_nonforking():
    generate_and_check_dag(
        checks= [check_all_floors],
        n_processes = 5,
        n_units = 50,
        repetitions = 30,
    )

def test_large_nonforking():
    generate_and_check_dag(
        checks= [check_all_floors],
        n_processes = 100,
        n_units = 200,
        repetitions = 1,
    )

def test_small_forking():
    n_processes = 5
    generate_and_check_dag(
        checks= [check_all_floors],
        n_processes = n_processes,
        n_units = 50,
        repetitions = 30,
        forking = lambda: random.randint(0, n_processes)
    )

def test_large_forking():
    n_processes = 100
    generate_and_check_dag(
        checks= [check_all_floors],
        n_processes = n_processes,
        n_units = 200,
        repetitions = 1,
        forking = lambda: random.randint(0, n_processes)
    )
