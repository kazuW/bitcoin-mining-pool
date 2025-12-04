class MinerManager:
    def __init__(self):
        self.miners = {}

    def add_miner(self, miner_id):
        if miner_id not in self.miners:
            self.miners[miner_id] = {'status': 'active', 'shares': 0}
            return True
        return False

    def remove_miner(self, miner_id):
        if miner_id in self.miners:
            del self.miners[miner_id]
            return True
        return False

    def submit_share(self, miner_id, share):
        if miner_id in self.miners:
            self.miners[miner_id]['shares'] += 1
            return True
        return False

    def get_miner_status(self, miner_id):
        return self.miners.get(miner_id, None)

    def get_all_miners(self):
        return self.miners