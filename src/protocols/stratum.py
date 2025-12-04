class StratumProtocol:
    def __init__(self):
        self.methods = {
            "mining.subscribe": self.subscribe,
            "mining.authorize": self.authorize,
            "mining.submit": self.submit,
            "mining.get_job": self.get_job,
        }

    def subscribe(self, params):
        # Handle subscription request from miner
        return {"id": params[0], "result": ["mining_pool", "1.0"], "error": None}

    def authorize(self, params):
        # Handle authorization request from miner
        return {"id": params[0], "result": True, "error": None}

    def submit(self, params):
        # Handle share submission from miner
        return {"id": params[0], "result": True, "error": None}

    def get_job(self, params):
        # Handle job request from miner
        return {"id": params[0], "result": {"job_id": "job1", "data": "00000000"}, "error": None}

    def handle_message(self, message):
        # Process incoming messages from miners
        method = message.get("method")
        params = message.get("params", [])
        if method in self.methods:
            return self.methods[method](params)
        return {"error": "Method not found"}