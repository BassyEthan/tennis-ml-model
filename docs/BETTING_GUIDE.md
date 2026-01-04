# Kalshi Trading Guide

## How Kalshi Trading Works

Kalshi is a prediction market platform where you can trade on the outcome of events. The system compares your model's predictions to Kalshi's market prices to find value opportunities.

**Example:**
- Kalshi price: 55 cents (implies 55% chance)
- Your model: 65% chance
- **Value: +10%** (expected profit over time)

## Getting Kalshi API Access

1. Sign up at https://kalshi.com
2. Get API credentials from your account settings
3. Set environment variables:
   ```bash
   export KALSHI_ACCESS_KEY="your_access_key_here"
   export KALSHI_PRIVATE_KEY_PATH="keys/kalshi_private_key.txt"
   export KALSHI_USE_PRODUCTION="true"  # or "false" for demo
   ```

## Value Calculation

The system calculates value by comparing:
- **Model Probability**: Your ML model's prediction (0-1)
- **Kalshi Probability**: Extracted from market prices (0-1)
- **Value = Model Prob - Kalshi Prob**

Positive value means your model thinks the outcome is more likely than Kalshi's price suggests.

## Expected Value (EV)

Expected Value = (Model Probability × Kalshi Odds) - 1.0

- **EV > 0**: Positive expected value trade
- **EV > 10%**: Strong value opportunity

## Using the Kalshi Scanner

Run the market scanner to find value opportunities:

```bash
python3 scripts/trading/scan_kalshi_markets.py --limit 5000 --debug
```

The scanner will:
1. Fetch tennis markets from Kalshi
2. Parse player names from market titles
3. Match players to your database
4. Generate model predictions
5. Compare to Kalshi prices
6. Identify value opportunities

## Strategy Tips

1. **Minimum Value Threshold**: Only trade when value > 5%
2. **Minimum Expected Value**: Require EV > 10% for strong opportunities
3. **Market Volume**: Consider market liquidity before trading
4. **Time Filtering**: Focus on markets within 48 hours
5. **Track Results**: Monitor model performance vs actual outcomes

## Legal Considerations

- Check gambling laws in your jurisdiction
- Kalshi is a registered prediction market platform
- Comply with tax reporting requirements
- Only trade with funds you can afford to lose
