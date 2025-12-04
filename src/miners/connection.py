from asyncio import StreamReader, StreamWriter

class MinerConnection:
    def __init__(self, reader: StreamReader, writer: StreamWriter):
        self.reader = reader
        self.writer = writer
        self.address = writer.get_extra_info('peername')

    async def send(self, message: dict):
        self.writer.write((json.dumps(message) + '\n').encode())
        await self.writer.drain()

    async def receive(self):
        line = await self.reader.readline()
        return json.loads(line.decode().strip())

    def close(self):
        self.writer.close()