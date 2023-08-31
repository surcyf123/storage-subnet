import os
import time
import argparse
import rocksdb
import bittensor as bt

def get_config():
    parser = argparse.ArgumentParser()
    parser.add_argument('--path_to_data', default='~/data_db', help='Data storage location for the miner.')
    parser.add_argument('--netuid', type=int, default=1, help="The chain subnet uid.")
    bt.subtensor.add_args(parser)
    bt.logging.add_args(parser)
    bt.wallet.add_args(parser)
    bt.axon.add_args(parser)
    config = bt.config(parser)
    config.full_path = os.path.expanduser(
        "{}/{}/{}/netuid{}/{}".format(
            config.logging.logging_dir,
            config.wallet.name,
            config.wallet.hotkey,
            config.netuid,
            'miner',
        )
    )
    if not os.path.exists(config.full_path): os.makedirs(config.full_path, exist_ok=True)
    return config

def main(config):
    bt.logging(config=config, logging_dir=config.full_path)
    bt.logging.info(f"Running miner for subnet: {config.netuid} on network: {config.subtensor.chain_endpoint} with config:")
    bt.logging.info(config)

    wallet = bt.wallet(config=config)
    subtensor = bt.subtensor(config=config)
    metagraph = subtensor.metagraph(config.netuid)

    if wallet.hotkey.ss58_address not in metagraph.hotkeys:
        bt.logging.error(f"Your miner is not registered. Run btcli register and try again.")
        exit()
    else:
        my_subnet_uid = metagraph.hotkeys.index(wallet.hotkey.ss58_address)
        bt.logging.info(f"Running miner on uid: {my_subnet_uid}")

    data_db = rocksdb.DB(config.path_to_data, rocksdb.Options(create_if_missing=True))

    def store(synapse):
        data_key = synapse.key.encode()
        data_value = synapse.data.encode()
        data_db.put(data_key, data_value)
        return synapse

    def retrieve(synapse):
        data_key = synapse.key.encode()
        synapse.data = data_db.get(data_key).decode()
        return synapse

    axon = bt.axon(wallet=wallet)

    axon.attach(
        forward_fn=store,
    ).attach(
        forward_fn=retrieve,
    )

    bt.logging.info(f"Serving axon on network: {config.subtensor.chain_endpoint} with netuid: {config.netuid}")
    axon.serve(netuid=config.netuid, subtensor=subtensor)

    bt.logging.info(f"Starting axon server on port: {config.axon.port}")
    axon.start()

    bt.logging.info(f"Starting main loop")
    step = 0
    while True:
        try:
            if step % 5 == 0:
                metagraph = subtensor.metagraph(config.netuid)
                log =  (f'Step:{step} | '
                        f'Block:{metagraph.block.item()} | '
                        f'Stake:{metagraph.S[my_subnet_uid]} | '
                        f'Rank:{metagraph.R[my_subnet_uid]}')
                bt.logging.info(log)
            step += 1
            time.sleep(1)
        except KeyboardInterrupt:
            axon.stop()
            bt.logging.success('Miner killed by keyboard interrupt.')
            break

if __name__ == "__main__":
    main(get_config())
