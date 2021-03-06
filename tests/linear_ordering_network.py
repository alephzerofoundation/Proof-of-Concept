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
import socket

from aleph.network import tx_source_gen
from aleph.process import Process
from aleph.crypto.keys import SigningKey, VerifyKey

import aleph.const as consts


async def main():
    n_processes = 20
    consts.USE_TCOIN = 0
    consts.UNITS_LIMIT = None
    consts.LEVEL_LIMIT = 100
    consts.N_PARENTS = n_processes

    processes = []
    host_ports = [8900+i for i in range(n_processes)]
    local_ip = socket.gethostbyname(socket.gethostname())
    addresses = [(local_ip, port) for port in host_ports]
    recv_addresses = [(local_ip, 9100+i) for i in range(n_processes)]

    signing_keys = [SigningKey() for _ in range(n_processes)]
    public_keys = [VerifyKey.from_SigningKey(sk) for sk in signing_keys]

    tasks = []
    userDB = None

    for process_id in range(n_processes):
        sk = signing_keys[process_id]
        pk = public_keys[process_id]
        new_process = Process(n_processes,
                      process_id,
                      sk, pk,
                      addresses,
                      public_keys,
                      None,
                      userDB,
                      tx_source_gen(batch_size=3, txpu=1, seed=process_id))
        processes.append(new_process)
        tasks.append(asyncio.create_task(new_process.run()))

    await asyncio.gather(*tasks)


if __name__ == '__main__':
    asyncio.run(main())
