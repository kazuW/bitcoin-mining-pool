from configparser import ConfigParser

class Settings:
    def __init__(self, config_file='config/config.ini'):
        self.config = ConfigParser()
        self.config.read(config_file)

    @property
    def rpc_host(self):
        return self.config.get('RPC', 'host')

    @property
    def rpc_port(self):
        return self.config.getint('RPC', 'port')

    @property
    def rpc_user(self):
        return self.config.get('RPC', 'user')

    @property
    def rpc_password(self):
        return self.config.get('RPC', 'password')

    @property
    def stratum_host(self):
        return self.config.get('Stratum', 'host')

    @property
    def stratum_port(self):
        return self.config.getint('Stratum', 'port')

    @property
    def database_path(self):
        return self.config.get('Database', 'path')