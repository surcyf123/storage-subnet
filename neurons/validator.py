import os
import time
import torch
import random
import hashlib
import argparse
import rocksdb
import bittensor as bt
from concurrent.futures import ThreadPoolExecutor

def get_config():
    parser = argparse.ArgumentParser()
    parser.add_argument('--validator_db', default='~/validator_db', help='Validator DB cache location.')
    parser.add_argument('--netuid', type=int, default=1, help="The chain subnet uid.")
    bt.subtensor.add_args(parser)
    bt.logging.add_args(parser)
    bt.wallet.add_args(parser)
    config = bt.config(parser)
    config.full_path = os.path.expanduser(
        "{}/{}/{}/netuid{}/{}".format(
            config.logging.logging_dir,
            config.wallet.name,
            config.wallet.hotkey,
            config.netuid,
            'validator',
        )
    )
    if not os.path.exists(config.full_path): os.makedirs(config.full_path, exist_ok=True)
    return config

def validate_retrieval(validation_key, validation_data_hash, dendrite, metagraph):
    retrieve_responses = dendrite.query(
        metagraph.axons,
        storage.protocol.Retrieve(key=validation_key),
        deserialize=True,
    )
    score = 0
    computed_hash = hashlib.sha256(retrieve_responses.encode()).hexdigest()
    if computed_hash == validation_data_hash.decode():
        score = 1
    return score

def main(config):
    bt.logging(config=config, logging_dir=config.full_path)
    bt.logging.info(f"Running validator for subnet: {config.netuid} on network: {config.subtensor.chain_endpoint} with config:")
    bt.logging.info(config)

    wallet = bt.wallet(config=config)
    subtensor = bt.subtensor(config=config)
    dendrite = bt.dendrite(wallet=wallet)
    metagraph = subtensor.metagraph(config.netuid)
    hashes_db = rocksdb.DB(config.validator_db, rocksdb.Options(create_if_missing=True))

    if wallet.hotkey.ss58_address not in metagraph.hotkeys:
        bt.logging.error(f"Your validator is not registered. Run btcli register and try again.")
        exit()
    else:
        my_subnet_uid = metagraph.hotkeys.index(wallet.hotkey.ss58_address)
        bt.logging.info(f"Running validator on uid: {my_subnet_uid}")

    bt.logging.info("Building validation weights.")
    alpha = 0.9
    scores = torch.ones_like(metagraph.S, dtype=torch.float32)

    bt.logging.info("Starting validator loop.")
    step = 0
    with ThreadPoolExecutor() as executor:
        while True:
            try:
                validation_keys = [str(random.randint(0, 10000)) for _ in range(10)]
                validation_data_hashes = [hashes_db.get(rocksdb.ReadOptions(), key.encode()) for key in validation_keys]
                future_scores = [executor.submit(validate_retrieval, key, hash_val, dendrite, metagraph) for key, hash_val in zip(validation_keys, validation_data_hashes)]

                for i, future_score in enumerate(future_scores):
                    score = future_score.result()
                    scores[i] = alpha * scores[i] + (1 - alpha) * score

                if (step + 1) % 2 == 0:
                    weights = torch.nn.functional.normalize(scores, p=1.0, dim=0)
                    bt.logging.info(f"Setting weights: {weights}")
                    result = subtensor.set_weights(
                        netuid=config.netuid,
                        wallet=wallet,
                        uids=metagraph.uids,
                        weights=weights,
                        wait_for_inclusion=True
                    )
                    if result: bt.logging.success('Successfully set weights.')
                    else: bt.logging.error('Failed to set weights.')

                step += 1
                metagraph = subtensor.metagraph(config.netuid)
                time.sleep(bt.__blocktime__)

            except KeyboardInterrupt:
                bt.logging.success("Keyboard interrupt detected. Exiting validator.")
                exit()

if __name__ == "__main__":
    main(get_config())
