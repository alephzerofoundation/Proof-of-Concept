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

import asyncio
import logging
import multiprocessing
import random
import os

import psutil

from aleph.data_structures import Poset, UserDB
from aleph.crypto import CommonRandomPermutation
from aleph.network import Network, tx_listener
from aleph.actions import create_unit
from aleph.utils import timer
import aleph.const as consts


class Process:
    '''
    This class represents a single member of the committee in the Aleph protocol.

    :param int n_processes: the committee size
    :param int process_id: the id of the process
    :param string secret_key: the private key of the current process
    :param string public_key: the public key of the current process
    :param list addresses: the list of length n_processes containing addresses (host, port) of all committee members
    :param list public_keys: the list of public keys of all committee members
    :param tuple tx_receiver_address: address pair (host, port) on which the process should listen for incoming transactions
    :param object userDB: initial state of user accounts
    :param object tx_source: method used for listening for incomming transactions
    :param string gossip_strategy: name of the gossip strategy to be used by the process
    '''


    def __init__(self, n_processes, process_id, secret_key, public_key, addresses, public_key_list, tx_receiver_address, userDB=None,
                tx_source=tx_listener, gossip_strategy='unif_random'):
        self.n_processes = n_processes
        self.process_id = process_id
        self.gossip_strategy = gossip_strategy

        self.secret_key = secret_key
        self.public_key = public_key

        self.public_key_list = public_key_list
        self.addresses = addresses
        self.ip = addresses[process_id][0]
        self.port = addresses[process_id][1]

        self.tx_source = tx_source
        self.tx_receiver_address = tx_receiver_address
        self.prepared_txs = []

        self.crp = CommonRandomPermutation([pk.to_hex() for pk in public_key_list])

        self.poset = Poset(self.n_processes, self.process_id, self.crp, use_tcoin = consts.USE_TCOIN)

        self.create_delay = consts.CREATE_DELAY

        # step size for adaptively changing create_delay
        self.step_size = consts.STEP_SIZE

        self.userDB = userDB
        if self.userDB is None:
            self.userDB = UserDB()

        self.keep_syncing = True
        self.tx_source = tx_source

        # units that have not yet been linearly ordered
        self.unordered_units = []

        # hashes of units in linear order
        self.linear_order = []

        # list of units (from least recent to most recent) created by out process
        self.our_units = []

        # we number all the syncs performed by process with unique ids (both outcoming and incoming)
        self.sync_id = 0

        # remember when did we last (sync_id) synced with a given process
        self.last_synced_with_process = [-1] * self.n_processes

        # initialize logger
        self.logger = logging.getLogger(consts.LOGGER_NAME)

        #initialize network
        self.network = Network(self, addresses, public_key_list, self.logger)


    def sign_unit(self, U):
        '''
        Signs the unit.
        :param Unit U: the unit to be signed.
        '''
        U.signature = self.secret_key.sign(U.bytestring())


    def process_txs_in_unit_list(self, list_U):
        '''
        For now this just counts the transactions in all the units in list_U.
        :param list list_U: the list of units containing the transactions to be counted
        :returns: The number of transactions
        '''
        n_txs = 0
        for U in list_U:
            n_txs += U.n_txs
        return n_txs


    def add_unit_and_extend_linear_order(self, U):
        '''
        Add a (compliant) unit to the poset, try to find a new timing unit and in the case of success, extend the linear order.
        :param Unit U: the unit to be added to the poset
        '''
        #NOTE: it is assumed at this point that U is not yet in the poset
        assert U.hash() not in self.poset.units, "A duplicate unit is being added to the poset."
        self.poset.add_unit(U)
        self.unordered_units.append(U)
        if self.poset.is_prime(U):

            with timer(self.process_id, 'attempt_timing'):
                if consts.PRECOMPUTE_POPULARITY:
                    self.poset.precompute_popularity_proof(U)
                new_timing_units = self.poset.attempt_timing_decision()
            timer.write_summary(where=self.logger, groups=[self.process_id])
            timer.reset(self.process_id)

            self.logger.info(f'prime_unit {self.process_id} | New prime unit at level {U.level} : {U.short_name()}')

            for U_timing in new_timing_units:
                self.logger.info(f'timing_new {self.process_id} | Timing unit at level {U_timing.level} established.')
            for U_timing in new_timing_units:
                with timer(self.process_id, f'linear_order_{U_timing.level}'):
                    units_to_order = []
                    updated_unordered_units = []
                    for V in self.unordered_units:
                        if self.poset.below(V, U_timing):
                            units_to_order.append(V)
                        else:
                            updated_unordered_units.append(V)

                    ordered_units = self.poset.break_ties(units_to_order)
                    self.linear_order += [W.hash() for W in ordered_units]
                    self.unordered_units = updated_unordered_units

                    printable_unit_hashes = ' '.join(W.short_name() for W in ordered_units)
                    n_txs = self.process_txs_in_unit_list(ordered_units)

                self.logger.info(f'add_linear_order {self.process_id} | At lvl {U_timing.level} added {len(units_to_order)} units and {n_txs} txs to the linear order {printable_unit_hashes}')
                timer.write_summary(where=self.logger, groups=[self.process_id])
                timer.reset(self.process_id)


    def add_unit_to_poset(self, U):
        '''
        Checks compliance of the unit U and adds it to the poset (unless already in the poset). Subsequently validates transactions using U.
        :param Unit U: the unit to be added
        :returns: boolean value: True if the unit was succesfully added or was already in the poset, False if the unit is not compliant
        '''

        if U.hash() in self.poset.units.keys():
            return True

        self.poset.prepare_unit(U)
        if self.poset.check_compliance(U):
            old_level = self.poset.level_reached

            self.add_unit_and_extend_linear_order(U)

            if self.poset.level_reached > old_level:
                self.logger.info(f"new_level {self.process_id} | Level {self.poset.level_reached} reached")

        else:
            return False

        return True

    def choose_process_to_sync_with(self):
        '''
        Choses a process with which to sync using the relevant strategy.
        :returns: the id of the process chosen
        '''
        if self.gossip_strategy == 'unif_random':
            sync_candidates = list(range(self.n_processes))
            sync_candidates.remove(self.process_id)
        elif self.gossip_strategy == 'non_recent_random':
            # this threshold is more or less arbitrary
            threshold = self.n_processes//3

            # pick all processes that we haven't synced with in the last (threshold) syncs
            sync_candidates = []
            for process_id in range(self.n_processes):
                if process_id == self.process_id:
                    continue
                last_sync = self.last_synced_with_process[process_id]
                if last_sync == -1  or  self.sync_id - last_sync >= threshold:
                    sync_candidates.append(process_id)
        else:
            assert False, "Non-supported gossip strategy."

        return random.choice(sync_candidates)

    def adjust_create_delay(self):
        '''
        Looks at the 3 last units created by our process and based on their levels modifies the create_delay.
        '''
        if len(self.our_units) >= 3:
            recent_levels = [U.level for U in self.our_units[-3:]]
            if recent_levels[2] == recent_levels[1]:
                # we have created two units on the same level, increase delay
                self.create_delay *= 1 + self.step_size
            elif recent_levels[0] <= recent_levels[2] - 2:
                # we are creating units too infrequently, reduce delay
                self.create_delay /= 1 + self.step_size


    def create_unit(self, txs):
        '''
        Attempts to create a new unit in the poset.
        :param list txs: the transactions to include in the unit
        :returns: A new unit if creation was successfull, None otherwise
        '''
        with timer(self.process_id, 'create_unit'):
            U = create_unit(self.poset, self.process_id, txs)

        return U


    async def create_add(self, txs_queue, server_started):
        '''
        A task that will keep creating new units.
        :param multiprocessing.Queue txs_queue: a queue of transactions to be added to units
        :param asyncio.Event server_started: a mutex to ensure that the basic connection server starts before we commence unit creation
        '''
        await server_started.wait()
        created_count, max_level_reached = 0, False
        while created_count != consts.UNITS_LIMIT and not max_level_reached:

            # log current memory consumption
            memory_usage_in_mib = (psutil.Process(os.getpid()).memory_info().rss)/(2**20)
            self.logger.info(f'memory_usage {self.process_id} | {memory_usage_in_mib:.4f} MiB')
            self.logger.info(f'max_units {self.process_id} | There are {len(self.poset.max_units)} maximal units just before create_unit')

            txs = self.prepared_txs


            new_unit = self.create_unit(txs)
            created_count += 1

            if new_unit is not None:

                with timer(self.process_id, 'create_unit'):
                    self.poset.prepare_unit(new_unit)
                    assert self.poset.check_compliance(new_unit), "A unit created by our process is not passing the compliance test!"
                    self.sign_unit(new_unit)

                self.add_unit_to_poset(new_unit)

                n_parents = len(new_unit.parents)
                self.logger.info(f"create_add {self.process_id} | Created a new unit {new_unit.short_name()} with {n_parents} parents")

                self.our_units.append(new_unit)
                if consts.ADAPTIVE_DELAY:
                    self.adjust_create_delay()

                if new_unit.level == consts.LEVEL_LIMIT:
                    max_level_reached = True

                if not txs_queue.empty():
                    self.prepared_txs = txs_queue.get()
                else:
                    self.prepared_txs = []
            else:
                self.logger.info(f'create_fail {self.process_id} | Failed to create a new unit')

            timer.write_summary(where=self.logger, groups=[self.process_id])
            timer.reset(self.process_id)

            await asyncio.sleep(self.create_delay)


        self.keep_syncing = False
        logger = logging.getLogger(consts.LOGGER_NAME)
        if max_level_reached:
            logger.info(f'create_stop {self.process_id} | process reached max_level {consts.LEVEL_LIMIT}')
        elif created_count == consts.UNITS_LIMIT:
            logger.info(f'create_stop {self.process_id} | process created {consts.UNITS_LIMIT} units')

        # dump the final poset to disc
        self.poset.dump_to_file(f'poset.dag')


    async def dispatch_syncs(self, server_started):
        '''
        A task that will keep initiating syncs with other processes.
        :param asyncio.Event server_started: an event to ensure that the basic connection server starts before we commence syncing
        '''
        await server_started.wait()

        sync_count = 0
        syncing_tasks = []
        while sync_count != consts.SYNCS_LIMIT and self.keep_syncing:
            sync_count += 1
            target_id = self.choose_process_to_sync_with()
            syncing_tasks.append(asyncio.create_task(self.network.sync(target_id)))
            await asyncio.sleep(consts.SYNC_INIT_DELAY)

        await asyncio.gather(*syncing_tasks)

        # give some time for other processes to finish
        await asyncio.sleep(3*consts.SYNC_INIT_DELAY + 2)

        logger = logging.getLogger(consts.LOGGER_NAME)
        logger.info(f'sync_stop {self.process_id} | keep_syncing is {self.keep_syncing}')


    async def start_listeners(self, server_started):
        '''
        A task that will start listeners for syncs from other processes.
        :param asyncio.Event server_started: an event to ensure that the basic connection server starts before we commence syncing
        '''
        await server_started.wait()

        listeners = [asyncio.create_task(self.network.listener(pid)) for pid in range(self.n_processes) if pid != self.process_id]
        await asyncio.gather(*listeners)


    async def run(self):
        '''
        A task to run the process.
        '''
        # start another process listening for incoming txs
        self.logger.info(f'start_process {self.process_id} | Starting a new process in committee of size {self.n_processes}')
        txs_queue = multiprocessing.Queue(1000)
        p = multiprocessing.Process(target=self.tx_source, args=(self.tx_receiver_address, txs_queue))
        try:
            p.start()

            server_started = asyncio.Event()
            server_task = asyncio.create_task(self.network.start_server(server_started))
            listener_task = asyncio.create_task(self.start_listeners(server_started))
            creator_task = asyncio.create_task(self.create_add(txs_queue, server_started))
            syncing_task = asyncio.create_task(self.dispatch_syncs(server_started))

            await asyncio.gather(syncing_task, creator_task)

            self.logger.info(f'listener_done {self.process_id} | Gathered results; canceling server and listeners')
            server_task.cancel()
            listener_task.cancel()
        finally:
            p.kill()

        self.logger.info(f'process_done {self.process_id} | Exiting program')
