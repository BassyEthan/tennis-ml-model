# Understanding Betting Odds

## Decimal Odds (Most Common)

**Format:** Single number (e.g., 2.92, 2.55)

### What They Mean:
- **2.92** = Bet $1, get back $2.92 total (profit = $1.92)
- **2.55** = Bet $1, get back $2.55 total (profit = $1.55)

### Profit Calculation:
- **Bet on Alcaraz at 2.92:**
  - Stake: $100
  - If wins: Receive $292 (profit = $192)
  - If loses: Lose $100

- **Bet on Norrie at 2.55:**
  - Stake: $100
  - If wins: Receive $255 (profit = $155)
  - If loses: Lose $100

## Converting to Implied Probability

**Formula:** Implied Probability = 1 / Decimal Odds

### Your Example:
- **Alcaraz (2.92):** 1 / 2.92 = **34.2%** chance (according to bookmaker)
- **Norrie (2.55):** 1 / 2.55 = **39.2%** chance (according to bookmaker)

**Total:** 34.2% + 39.2% = **73.4%**

Wait, that doesn't add up to 100%! That's because:

## The Bookmaker's Margin (Overround)

Bookmakers add a margin (usually 5-10%) to make profit:

- **Alcaraz:** 34.2% implied → "True" probability ≈ 34.2% / 1.27 = **26.9%**
- **Norrie:** 39.2% implied → "True" probability ≈ 39.2% / 1.27 = **30.9%**

The extra 27% is the bookmaker's margin spread across both outcomes.

## Value Betting

**Value exists when:** Your Model's Probability > Bookmaker's Implied Probability

### Example:
- **Bookmaker odds for Alcaraz:** 2.92 (34.2% implied)
- **Your model predicts:** 45% chance Alcaraz wins
- **Value:** 45% - 34.2% = **+10.8%** ✅ VALUE BET!

### Expected Value Calculation:
EV = (Your Probability × Odds) - 1
   = (0.45 × 2.92) - 1
   = 1.314 - 1
   = **+31.4%** expected profit per bet (long-term)

## Comparison: Your Example

| Player | Odds | Implied Prob | Your Model | Value |
|--------|------|--------------|------------|-------|
| Alcaraz | 2.92 | 34.2% | ? | ? |
| Norrie | 2.55 | 39.2% | ? | ? |

**If your model says:**
- Alcaraz has 40% chance → Value = +5.8% ✅
- Alcaraz has 30% chance → Value = -4.2% ❌ (no value)
- Norrie has 50% chance → Value = +10.8% ✅
- Norrie has 35% chance → Value = -4.2% ❌ (no value)

## Other Odds Formats (Reference)

### American Odds:
- **Positive (+192):** Bet $100 to win $192 (Alcaraz ~2.92)
- **Negative (-155):** Bet $155 to win $100 (Norrie would be ~1.64, but 2.55 ≈ +155)

### Fractional Odds (UK):
- **Alcaraz 2.92** = 48/25 ("forty-eight to twenty-five")
- **Norrie 2.55** = 31/20 ("thirty-one to twenty")

## Quick Decision Guide

1. **Get your model's prediction** (e.g., "Alcaraz 45% chance")
2. **Calculate implied probability** (1 / 2.92 = 34.2%)
3. **Find the difference** (45% - 34.2% = +10.8%)
4. **If positive and > 5%:** Consider it a value bet
5. **Check Kelly Criterion** for bet sizing

## Your Specific Case

**Alcaraz @ 2.92 vs Norrie @ 2.55**

The odds suggest:
- Bookmakers slightly favor **Norrie** (39.2% vs 34.2%)
- It's a relatively close match (both underdogs)
- Good odds for both players (both > 2.0)

**Action:** Check what your model predicts for each player. If your model strongly favors one player more than the odds suggest, you've found value!

