# Bitcoin Mining Pool

This project implements a Bitcoin mining pool using the Stratum protocol with **100% ckpool-solo compatibility**. It serves as a relay between miners and Bitcoin Core, managing connections, job distribution, and share submissions.

## Features

- ✅ **100% ckpool-solo compatible** hash calculations
- ✅ **BitAxe miner support** with proper endianness handling
- ✅ Stratum protocol implementation for miner communication
- ✅ Connection management for multiple miners
- ✅ Job distribution and share submission handling
- ✅ Integration with Bitcoin Core via JSON-RPC
- ✅ Comprehensive test suite with real-world validation
- ✅ Production-ready performance and error handling

## Project Structure

```
bitcoin-mining-pool
├── src
│   ├── main.py                # Entry point for the application
│   ├── config                 # Configuration settings
│   │   ├── __init__.py
│   │   └── settings.py
│   ├── core                   # Core functionality
│   │   ├── __init__.py
│   │   ├── pool.py            # Pool management
│   │   ├── stratum_server.py   # Stratum server implementation
│   │   └── bitcoin_rpc.py     # Bitcoin Core RPC management
│   ├── protocols              # Protocol definitions
│   │   ├── __init__.py
│   │   └── stratum.py         # Stratum protocol implementation
│   ├── miners                 # Miner connection management
│   │   ├── __init__.py
│   │   ├── connection.py       # Miner connection logic
│   │   └── manager.py         # Miner management
│   ├── utils                  # Utility functions
│   │   ├── __init__.py
│   │   ├── logging.py         # Logging setup
│   │   └── helper.py          # Helper functions
│   └── database               # Database operations
│       ├── __init__.py
│       ├── models.py          # Database models
│       └── operations.py      # Database operations
├── config
│   └── config.ini             # Configuration file
├── tests                      # Unit tests
│   ├── __init__.py
│   ├── test_stratum.py        # Tests for Stratum protocol
│   ├── test_pool.py          # Tests for Pool class
│   ├── test_coinbasetx.py    # Coinbase transaction tests
│   ├── test_diff.py          # Difficulty tests
│   └── test_script_pubkey.py # Script and pubkey tests
├── ckpool_compatibility_test.py  # ckpool-solo compatibility validation
├── stratum_protocol_test.py      # Stratum protocol implementation tests
├── integration_test_suite.py     # Complete integration tests
├── run_tests.py                   # Test runner for all tests
├── requirements.txt           # Required packages
├── setup.py                   # Setup script
└── README.md                  # Project documentation
```

## Installation

1. Clone the repository:
   ```
   git clone <repository-url>
   cd bitcoin-mining-pool
   ```

2. Install the required packages:
   ```
   pip install -r requirements.txt
   ```

3. Configure the `config/config.ini` file with your Bitcoin Core RPC details and other settings.

## Testing

This mining pool includes a comprehensive test suite to ensure **100% compatibility with ckpool-solo**:

### Quick Test
Run all tests with the integrated test runner:
```bash
python run_tests.py
```

### Individual Test Categories

1. **ckpool-solo Compatibility Test** (validates hash calculations):
   ```bash
   python run_tests.py --test compat
   ```

2. **Stratum Protocol Test** (validates protocol implementation):
   ```bash
   python run_tests.py --test stratum
   ```

3. **Complete Integration Test** (validates entire system):
   ```bash
   python run_tests.py --test integration
   ```

### Test Results Expected
When all tests pass, you should see:
```
🎉 ALL TESTS PASSED!
✅ Bitcoin Mining Pool is 100% compatible with ckpool-solo
✅ Ready for production use with BitAxe miners
✅ All hash calculations match ckpool-solo exactly
✅ Stratum protocol fully implemented
```

## Usage

To start the mining pool server, run the following command:
```
python src/main.py
```

This will initialize the mining pool and start the Stratum server, allowing miners to connect and begin mining.

### BitAxe Miner Configuration
For BitAxe miners, use these settings:
- **Pool URL**: `stratum+tcp://your-pool-ip:port`
- **Wallet Address**: Your Bitcoin address (bc1..., 1..., or 3...)
- **Password**: Any value (typically 'x')

### Verified Compatibility
✅ **BitAxe Miners**: Fully tested and compatible  
✅ **ckpool-solo**: 100% hash calculation compatibility  
✅ **Stratum Protocol**: Complete implementation

## Contributing

Contributions are welcome! Please open an issue or submit a pull request for any enhancements or bug fixes.

## License

This project is licensed under the MIT License. See the LICENSE file for more details.