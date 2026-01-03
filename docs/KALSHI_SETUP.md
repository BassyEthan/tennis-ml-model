# Kalshi Integration Setup

## Prerequisites

- Kalshi account with API access
- Kalshi Access Key
- Kalshi Private Key file (`.txt`, `.pem`, or `.key` format)

## Setup Steps

### 1. Store Your Private Key

Place your Kalshi private key file in the `keys/` directory:

```bash
cp /path/to/your/kalshi-key.txt keys/kalshi_private_key.txt
chmod 600 keys/kalshi_private_key.txt
```

**Important:** The `keys/` directory is git-ignored. Never commit private keys!

### 2. Configure Environment Variables

Create `.env` file in project root:

```bash
# Kalshi Access Key
KALSHI_ACCESS_KEY=your_actual_access_key_here

# Path to private key
KALSHI_PRIVATE_KEY_PATH=keys/kalshi_private_key.txt

# Use demo API (sandbox) or production
KALSHI_BASE_URL=https://demo-api.kalshi.co
KALSHI_USE_PRODUCTION=false
```

### 3. For Production Trading

When ready for live trading, update `.env`:

```bash
KALSHI_BASE_URL=https://api.kalshi.com
KALSHI_USE_PRODUCTION=true
```

## Using the Kalshi Client

```python
from src.trading.kalshi_client import KalshiClient

# Initialize client (uses credentials from .env)
client = KalshiClient()

# Get portfolio balance
balance = client.get_portfolio_balance()

# Get markets
markets = client.get_markets(limit=50)

# Place an order
order = client.place_order(
    ticker="TENNIS-MATCH-12345-YES",
    side="yes",
    action="buy",
    count=10,
    price=50  # 50 cents = $0.50
)
```

## Security Best Practices

1. **Never commit credentials:**
   - `.env` is git-ignored
   - `keys/*.txt`, `keys/*.pem`, `keys/*.key` are git-ignored

2. **Start with demo/sandbox:**
   - Test with `KALSHI_BASE_URL=https://demo-api.kalshi.co`
   - Verify everything works before switching to production

3. **Protect private key file:**
   ```bash
   chmod 600 keys/kalshi_private_key.txt
   ```

## Troubleshooting

### "Private key not found"
- Check that the file exists at the path specified in `KALSHI_PRIVATE_KEY_PATH`
- Verify the path is correct (can be relative or absolute)

### "Failed to load private key"
- Ensure the file is in PEM format
- Check that the file isn't corrupted

### "KALSHI_ACCESS_KEY not provided"
- Set the environment variable or add it to `.env`
- Restart your application after changing `.env`
