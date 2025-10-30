# Tennis Betting Strategy Guide

## ⚠️ IMPORTANT WARNINGS

**Gambling involves risk. You can lose money.**
- Only bet what you can afford to lose
- Past performance doesn't guarantee future results
- Models are predictions, not certainties
- Bookmakers have margins that favor the house
- Always gamble responsibly

## How Value Betting Works

Value betting means betting when the bookmaker's odds imply a probability that's LOWER than your model's predicted probability.

### Example:
- **Bookmaker odds:** 2.50 (implies 40% chance player wins)
- **Your model prediction:** 50% chance player wins
- **Value:** +10% (your model thinks it's more likely than the odds suggest)
- **Expected Value:** (0.50 × 2.50) - 1 = +25% (expected profit over time)

## Getting Real-Time Odds

### Option 1: The Odds API (Recommended for Development)
1. Sign up at https://the-odds-api.com
2. Get free API key (500 requests/month free tier)
3. Set environment variable:
   ```bash
   export ODDS_API_KEY="your_api_key_here"
   ```
4. Restart your Flask app

### Option 2: Sportsbooks with Public APIs
- **Betfair API** - Has exchange odds (more accurate)
- **Sportradar** - Professional sports data (requires subscription)
- **OddsJam** - Aggregator with API access

### Option 3: Web Scraping (Legal Disclaimer Required)
- Scrape odds from legal sportsbooks
- Check legality in your jurisdiction
- Respect robots.txt and rate limits

## Kelly Criterion

The system calculates optimal bet sizing using the Kelly Criterion:

**Kelly Fraction = (Probability × Odds - 1) / (Odds - 1)**

- **Kelly 5%** = Bet 5% of your bankroll
- **Kelly 0%** = No value, don't bet
- **System caps at 25%** max (for safety)

**Example:**
- Bankroll: $1000
- Kelly: 10%
- Optimal bet: $100

## Strategy Tips

1. **Aggregate Model Predictions**
   - Use average of all 3 models for more reliable predictions
   - Or use the most confident model

2. **Minimum Value Threshold**
   - Only bet when value > 5% (bookmaker margin is typically 3-5%)
   - Filter out marginal value bets

3. **Bankroll Management**
   - Never bet more than Kelly suggests
   - Use fractional Kelly (0.5x or 0.25x) for conservatism
   - Have a stop-loss plan

4. **Diversification**
   - Don't put all bankroll on one match
   - Spread bets across multiple value opportunities

5. **Continuous Improvement**
   - Track your bets and results
   - Adjust model confidence based on actual outcomes
   - Recalibrate probabilities if systematic bias detected

## Risk Management

- **Model Uncertainty:** Your models have error rates - account for this
- **Odds Movement:** Odds change quickly, especially before match start
- **Injuries/Withdrawals:** Late-breaking news affects probabilities
- **Market Efficiency:** If you find value, others might too - odds may adjust

## Using the Value Betting Feature

1. Enter two players in the web app
2. Click "Find Value Bets" (new button)
3. System will:
   - Get your model predictions
   - Fetch current betting odds
   - Calculate value for each bet
   - Show recommendations with Kelly sizing
   - Highlight positive expected value opportunities

## Profitability Requirements

To be profitable long-term, you need:
- **Model accuracy > bookmaker's implied probability**
- **Enough value bets to overcome variance**
- **Bankroll management to survive losing streaks**
- **Discipline to follow the system**

**Example:**
- Model accuracy: 55%
- Finding 10%+ value bets
- Kelly sizing: 5-10% per bet
- Expected ROI: 5-15% per bet (over long term)

## Legal Considerations

- Check gambling laws in your jurisdiction
- Only use licensed, legal sportsbooks
- Ensure you're of legal gambling age
- Comply with tax reporting requirements
- Some jurisdictions restrict sports betting APIs

## Next Steps

1. Test with mock data/small bets first
2. Track all bets and outcomes
3. Monitor model performance vs actual results
4. Adjust predictions if systematic bias found
5. Scale gradually as confidence increases

