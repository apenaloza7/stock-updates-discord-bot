# StockUpdates

A Discord bot that delivers real-time stock market updates to your server. Built for a Raspberry Pi, but runs anywhere Python does.

---

## What It Does

Tracks your watchlist and posts price updates at configurable intervals during market hours. Shows daily change, 52-week context, and pre/post market prices when applicable. Can also generate charts and compare multiple tickers side-by-side.

The bot only sends updates Monday through Friday, 4 AM to 8 PM Eastern — covering pre-market, regular hours, and after-hours trading.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         Discord Server                          │
└─────────────────────────────────────────────────────────────────┘
                                 ▲
                                 │ Discord API
                                 │
┌─────────────────────────────────────────────────────────────────┐
│                          StockUpdates Bot                       │
│  ┌───────────────┐  ┌───────────────┐  ┌───────────────┐       │
│  │   Scheduler   │  │   Commands    │  │    Cache      │       │
│  │               │  │               │  │   (60s TTL)   │       │
│  │ - Intervals   │  │ - !check      │  │               │       │
│  │ - Trading hrs │  │ - !chart      │  │ Reduces API   │       │
│  │ - Weekday chk │  │ - !compare    │  │ calls         │       │
│  └───────┬───────┘  └───────┬───────┘  └───────┬───────┘       │
│          │                  │                  │                │
│          └──────────────────┼──────────────────┘                │
│                             ▼                                   │
│                    ┌───────────────┐                           │
│                    │   yfinance    │                           │
│                    │   (Yahoo)     │                           │
│                    └───────────────┘                           │
└─────────────────────────────────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────┐
│                        stocks.json                              │
│  - channel_id: where updates get posted                        │
│  - stocks: ["AAPL", "MSFT", ...]                               │
│  - interval_minutes: 15 | 30 | 60 | 120 | 240                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## Data Flow

```
┌──────────┐     ┌──────────┐     ┌──────────┐     ┌──────────┐
│  Timer   │────>│  Check   │────>│  Fetch   │────>│   Post   │
│  fires   │     │  trading │     │  stock   │     │  embed   │
│          │     │  hours   │     │  data    │     │          │
└──────────┘     └──────────┘     └──────────┘     └──────────┘
                      │                │
                      │ Skip if        │ Uses cache if
                      │ weekend or     │ data < 60s old
                      │ outside 4a-8p  │
                      ▼                ▼
                   [silent]        [yfinance]
```

---

## Features

**Scheduled Updates**
- Configurable intervals: 15 minutes, 30 minutes, 1 hour, 2 hours, or 4 hours
- Respects market hours (Mon-Fri, 4 AM - 8 PM ET)
- Shows pre-market and after-hours prices when outside regular session

**Price Context**
- Daily change in dollars and percentage
- 52-week high/low context ("Near 52w high", "23% off 52w high", etc.)
- Color-coded indicators for up/down days

**Analysis Tools**
- Compare up to 5 stocks side-by-side (price, change, P/E, market cap)
- Generate price charts for any timeframe (1 day to 5 years)

**Efficiency**
- 60-second cache prevents redundant API calls
- Lightweight enough to run on a Raspberry Pi

---

## Commands

| Command | Description |
|---------|-------------|
| `!check` | Show current prices for all watched stocks |
| `!check AAPL` | Show current price for a specific ticker |
| `!addstock AAPL` | Add a ticker to the watchlist |
| `!removestock AAPL` | Remove a ticker from the watchlist |
| `!stocks` | List all tickers in the watchlist |
| `!compare AAPL MSFT GOOGL` | Compare 2-5 stocks side-by-side |
| `!chart AAPL 1mo` | Generate a price chart (1d/5d/1mo/3mo/6mo/1y/5y) |
| `!setinterval 30m` | Set update frequency (15m/30m/1h/2h/4h) |
| `!setchannel` | Set the current channel for automatic updates |
| `!help` | Show all available commands |
| `!ping` | Check if the bot is responsive |

---

## Setup

### Prerequisites

- Python 3.11+
- A Discord bot token
- The bot invited to your server with `Send Messages` and `Embed Links` permissions

### Installation

```bash
# Clone the repo
Clone the repo

# Install dependencies
pip install -r requirements.txt

# Create your config file
cp stocks.example.json stocks.json

# Set your Discord token
export DISCORD_TOKEN="your-token-here"

# Run
python bot.py
```

### Configuration

Edit `stocks.json` to set your Discord channel ID and initial watchlist:

```json
{
  "channel_id": null,
  "stocks": [],
  "interval_minutes": 60
}
```

Or just use `!setchannel` and `!addstock` commands after starting the bot.

---

## Docker Deployment

For running on a Raspberry Pi or any Docker host:

```yaml
version: "3.8"
services:
  bot:
    image: python:3.11-slim
    container_name: stock-bot
    volumes:
      - .:/app
    working_dir: /app
    environment:
      - DISCORD_TOKEN=your-token-here
      - TZ=America/New_York
    command: >
      sh -c "apt-get update && 
             apt-get install -y --no-install-recommends gcc libffi-dev && 
             pip install --no-cache-dir -r requirements.txt && 
             python bot.py"
    restart: always
```

```bash
docker-compose up -d
```

---

## Tech Stack

| Component | Purpose |
|-----------|---------|
| [discord.py](https://discordpy.readthedocs.io/) | Discord API wrapper |
| [yfinance](https://github.com/ranaroussi/yfinance) | Yahoo Finance market data |
| [matplotlib](https://matplotlib.org/) | Chart generation |
| [pytz](https://pythonhosted.org/pytz/) | Timezone handling |

---

## Project Structure

```
stockUpdates/
├── bot.py                 # Main bot logic
├── requirements.txt       # Python dependencies
├── stocks.json           # Runtime config (gitignored)
├── stocks.example.json   # Config template
├── docker-compose.yaml   # Container deployment
└── README.md
```

---

## License

Do whatever you want with it. No warranty, no guarantees, not financial advice.
