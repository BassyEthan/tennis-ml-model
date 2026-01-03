# Value Betting Guide

## How Value Betting Works

Value betting means betting when the bookmaker's odds imply a probability that's **LOWER** than your model's predicted probability.

**Example:**
- Bookmaker odds: 2.50 (implies 40% chance)
- Your model: 50% chance
- **Value: +10%** (expected profit over time)

## Getting Real-Time Odds

### The Odds API (Recommended)
1. Sign up at https://the-odds-api.com
2. Get free API key (500 requests/month free tier)
3. Set environment variable:
   ```bash
   export ODDS_API_KEY="your_api_key_here"
   ```

### Other Options
- **Betfair API** - Exchange odds
- **Sportradar** - Professional data (subscription required)

## Kelly Criterion

The system calculates optimal bet sizing:

**Kelly Fraction = (Probability × Odds - 1) / (Odds - 1)**

- **Kelly 5%** = Bet 5% of bankroll
- System caps at 25% max (for safety)

## Strategy Tips

1. **Minimum Value Threshold**: Only bet when value > 5%
2. **Bankroll Management**: Use fractional Kelly (0.5x) for conservatism
3. **Diversification**: Spread bets across multiple opportunities
4. **Track Results**: Monitor model performance vs actual outcomes

## Using the Value Betting Feature

1. Enter two players in the web app
2. Click "Find Value Bets"
3. System shows:
   - Model predictions vs bookmaker odds
   - Value percentages
   - Kelly sizing recommendations
   - Expected value calculations

## Legal Considerations

- Check gambling laws in your jurisdiction
- Only use licensed, legal sportsbooks
- Comply with tax reporting requirements
