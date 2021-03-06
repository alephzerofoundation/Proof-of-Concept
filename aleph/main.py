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
import sys

from optparse import OptionParser

from aleph.crypto.keys import SigningKey, VerifyKey
from aleph.data_structures import UserDB, Tx
from aleph.network import tx_listener, tx_source_gen
from aleph.process import Process

import aleph.const as consts


def _read_ip_addresses(ip_addresses_path):
    with open(ip_addresses_path, 'r') as f:
        return [line[:-1] for line in f]


def _read_signing_keys(signing_keys_path):
    with open(signing_keys_path, 'r') as f:
        hexes = [line[:-1].encode() for line in f]
        return [SigningKey(hexed) for hexed in hexes]


def _sort_and_get_my_pid(public_keys, signing_keys, my_ip, ip_addresses):
    ind = ip_addresses.index(my_ip)
    my_pk = public_keys[ind]

    pk_hexes = [pk.to_hex() for pk in public_keys]
    arg_sort = [i for i, _ in sorted(enumerate(pk_hexes), key = lambda x: x[1])]
    public_keys = [public_keys[i] for i in arg_sort]
    signing_keys = [signing_keys[i] for i in arg_sort]
    ip_addresses = [ip_addresses[i] for i in arg_sort]

    return public_keys.index(my_pk), public_keys, signing_keys, ip_addresses


def _log_consts():
    logger = logging.getLogger(consts.LOGGER_NAME)
    consts_names = ['N_PARENTS', 'USE_TCOIN', 'CREATE_DELAY', 'SYNC_INIT_DELAY',  'TXPU', 'LEVEL_LIMIT', 'UNITS_LIMIT']
    consts_values = []
    for const_name in consts_names:
        consts_values.append(f'{const_name}={consts.__dict__[const_name]}')
    logger.info('; '.join(consts_values))


async def main():
    '''
    A task to run as a single member of the Aleph committee.
    '''
    _log_consts()

    signing_keys = _read_signing_keys('signing_keys')
    ip_addresses = _read_ip_addresses('ip_addresses')
    with open('my_ip', 'r') as f:
        my_ip = f.readline().strip()

    assert len(ip_addresses) == len(signing_keys), 'number of hosts and signing keys dont match!!!'
    public_keys = [VerifyKey.from_SigningKey(sk) for sk in signing_keys]

    process_id, public_keys, signing_keys, ip_addresses = _sort_and_get_my_pid(public_keys, signing_keys, my_ip, ip_addresses)
    addresses = [(ip, consts.HOST_PORT) for ip in ip_addresses]

    sk, pk = signing_keys[process_id], public_keys[process_id]

    n_processes = len(ip_addresses)
    userDB = None

    recv_address = None
    if consts.TX_SOURCE == 'tx_source_gen':
        tx_source = tx_source_gen(consts.TX_LIMIT, consts.TXPU, process_id)
    else:
        tx_source = tx_listener

    process = Process(n_processes,
                      process_id,
                      sk, pk,
                      addresses,
                      public_keys,
                      recv_address,
                      userDB,
                      tx_source)

    await process.run()


if __name__ == '__main__':
    asyncio.run(main())
