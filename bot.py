import os
import json
import asyncio
import time
import io
from datetime import datetime, timedelta
import discord
from discord.ext import commands, tasks
import yfinance as yf
import pytz
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

# Use environment variables for security
TOKEN = os.getenv('DISCORD_TOKEN')
CONFIG_FILE = os.path.join(os.path.dirname(__file__), 'stocks.json')

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix='!', intents=intents, help_command=None)

# Cache system to reduce API calls
_cache = {}  # {ticker: (data_dict, timestamp)}
CACHE_TTL = 60  # seconds

# Eastern timezone for trading hours
ET = pytz.timezone('America/New_York')

# Valid interval presets (in minutes)
INTERVAL_PRESETS = {
    '15m': 15,
    '30m': 30,
    '1h': 60,
    '2h': 120,
    '4h': 240
}


def get_cached_stock(ticker):
    """Get stock data from cache or fetch fresh."""
    ticker = ticker.upper()
    if ticker in _cache:
        data, ts = _cache[ticker]
        if time.time() - ts < CACHE_TTL:
            return data
    # Fetch fresh data
    data = _fetch_stock_data_raw(ticker)
    if data:
        _cache[ticker] = (data, time.time())
    return data


def clear_cache():
    """Clear the stock data cache."""
    global _cache
    _cache = {}


def load_config():
    """Load configuration from JSON file with defaults for new fields."""
    defaults = {
        "channel_id": None,
        "stocks": [],
        "interval_minutes": 60
    }
    try:
        with open(CONFIG_FILE, 'r') as f:
            config = json.load(f)
            # Merge with defaults to handle missing keys
            for key, value in defaults.items():
                if key not in config:
                    config[key] = value
            return config
    except (FileNotFoundError, json.JSONDecodeError):
        return defaults


def save_config(config):
    """Save configuration to JSON file."""
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config, f, indent=2)


def is_regular_hours():
    """Check if we're within regular market hours (9:30 AM - 4:00 PM ET)."""
    now = datetime.now(ET)
    market_open = now.replace(hour=9, minute=30, second=0, microsecond=0)
    market_close = now.replace(hour=16, minute=0, second=0, microsecond=0)
    return market_open <= now <= market_close


def is_trading_hours():
    """Check if we're within extended trading hours (4 AM - 8 PM ET, Mon-Fri)."""
    now = datetime.now(ET)
    # Mon=0, Fri=4
    if now.weekday() > 4:
        return False
    # 4 AM to 8 PM ET
    return 4 <= now.hour < 20


def get_52w_context(price, year_high, year_low):
    """Get 52-week context string."""
    if year_high is None or year_low is None or price is None:
        return None
    
    if year_high == 0:
        return None
        
    pct_off_high = ((year_high - price) / year_high) * 100
    pct_off_low = ((price - year_low) / year_low) * 100 if year_low > 0 else 0
    
    if pct_off_high < 3:
        return "Near 52w high"
    elif pct_off_low < 3:
        return "Near 52w low"
    else:
        return f"{pct_off_high:.0f}% off 52w high"


def _fetch_stock_data_raw(ticker):
    """Fetch stock data using yfinance (internal, use get_cached_stock instead)."""
    try:
        stock = yf.Ticker(ticker)
        fast_info = stock.fast_info
        
        current_price = fast_info.last_price
        previous_close = fast_info.previous_close
        
        if current_price is None or previous_close is None:
            return None
        
        change = current_price - previous_close
        change_percent = (change / previous_close) * 100
        
        # Get 52-week data
        year_high = getattr(fast_info, 'year_high', None)
        year_low = getattr(fast_info, 'year_low', None)
        
        # Get pre/post market prices from full info
        info = stock.info
        pre_market_price = info.get('preMarketPrice')
        post_market_price = info.get('postMarketPrice')
        
        # Determine which extended hours price to show
        extended_price = None
        extended_label = None
        if not is_regular_hours():
            now = datetime.now(ET)
            if now.hour < 9 or (now.hour == 9 and now.minute < 30):
                # Pre-market
                if pre_market_price:
                    extended_price = pre_market_price
                    extended_label = "Pre"
            else:
                # After-hours
                if post_market_price:
                    extended_price = post_market_price
                    extended_label = "AH"
        
        return {
            "ticker": ticker.upper(),
            "price": current_price,
            "change": change,
            "change_percent": change_percent,
            "year_high": year_high,
            "year_low": year_low,
            "fifty_two_week_context": get_52w_context(current_price, year_high, year_low),
            "extended_price": extended_price,
            "extended_label": extended_label,
            "market_cap": info.get('marketCap'),
            "pe_ratio": info.get('trailingPE'),
        }
    except Exception:
        return None


def get_stock_data(ticker):
    """Fetch stock data using cache."""
    return get_cached_stock(ticker)


def create_stock_embed(stocks_data):
    """Create a Discord embed for stock updates with enhanced format."""
    # Get current ET time for title
    now_et = datetime.now(ET)
    time_str = now_et.strftime("%I:%M %p ET")
    
    embed = discord.Embed(
        title=f"📈 Stock Update ({time_str})",
        timestamp=datetime.now(pytz.UTC),
        color=discord.Color.blue()
    )
    
    if not stocks_data:
        embed.description = "No stock data available."
        return embed
    
    lines = []
    for data in stocks_data:
        if data is None:
            continue
        
        ticker = data['ticker']
        
        # Color indicator
        emoji = "🟢" if data["change"] >= 0 else "🔴"
        sign = "+" if data["change"] >= 0 else ""
        
        # Build price line with optional extended hours price
        price_str = f"${data['price']:.2f}"
        if data.get('extended_price') and data.get('extended_label'):
            price_str += f"  ({data['extended_label']}: ${data['extended_price']:.2f})"
        
        # First line: ticker and price
        line = f"{emoji} **{ticker}** — {price_str}\n"
        
        # Second line: change and 52w context
        change_str = f"{sign}${data['change']:.2f} ({sign}{data['change_percent']:.2f}%)"
        context = data.get('fifty_two_week_context')
        if context:
            line += f"　　{change_str} · {context}"
        else:
            line += f"　　{change_str}"
        
        lines.append(line)
    
    embed.description = "\n\n".join(lines) if lines else "No valid stock data."
    return embed


async def fetch_all_stocks(tickers):
    """Fetch data for all stocks."""
    stocks_data = []
    for ticker in tickers:
        data = get_stock_data(ticker)
        stocks_data.append(data)
    return stocks_data


# Global reference to the scheduled task
scheduled_task = None


def get_next_interval_time(interval_minutes):
    """Calculate the next aligned interval time."""
    now = datetime.now(ET)
    
    # Round up to the next interval
    minutes_since_midnight = now.hour * 60 + now.minute
    intervals_passed = minutes_since_midnight // interval_minutes
    next_interval_minutes = (intervals_passed + 1) * interval_minutes
    
    next_time = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(minutes=next_interval_minutes)
    
    # If next time is past 8 PM, skip to 4 AM next trading day
    if next_time.hour >= 20:
        next_time = next_time.replace(hour=4, minute=0) + timedelta(days=1)
        # Skip weekends
        while next_time.weekday() > 4:
            next_time += timedelta(days=1)
    
    return next_time


async def run_scheduled_update():
    """The actual update logic."""
    config = load_config()
    channel_id = config.get("channel_id")
    stocks = config.get("stocks", [])
    
    if not channel_id or not stocks:
        return
    
    # Check trading hours
    if not is_trading_hours():
        return
    
    channel = bot.get_channel(channel_id)
    if not channel:
        return
    
    stocks_data = await fetch_all_stocks(stocks)
    embed = create_stock_embed(stocks_data)
    await channel.send(embed=embed)


async def scheduled_update_loop():
    """Main loop for scheduled updates with dynamic intervals."""
    await bot.wait_until_ready()
    
    while True:
        config = load_config()
        interval_minutes = config.get("interval_minutes", 60)
        
        # Calculate wait time until next interval
        next_time = get_next_interval_time(interval_minutes)
        now = datetime.now(ET)
        wait_seconds = (next_time - now).total_seconds()
        
        if wait_seconds > 0:
            print(f"Next update at {next_time.strftime('%I:%M %p ET')} (in {wait_seconds:.0f}s)")
            await asyncio.sleep(wait_seconds)
        
        # Run the update
        try:
            await run_scheduled_update()
        except Exception as e:
            print(f"Error in scheduled update: {e}")
        
        # Small delay to prevent rapid re-runs
        await asyncio.sleep(5)


def start_scheduled_task():
    """Start or restart the scheduled update task."""
    global scheduled_task
    if scheduled_task and not scheduled_task.done():
        scheduled_task.cancel()
    scheduled_task = asyncio.create_task(scheduled_update_loop())


@bot.event
async def on_ready():
    print(f'Logged in as {bot.user}')
    start_scheduled_task()


@bot.command()
async def ping(ctx):
    """Test command to check if bot is responsive."""
    await ctx.send('Pong!')


@bot.command(name='help')
async def help_command(ctx):
    """Show all available commands."""
    embed = discord.Embed(
        title="📊 Stock Bot Commands",
        description="Here are all the available commands:",
        color=discord.Color.green()
    )
    
    # Basic commands
    embed.add_field(name="📋 **Basic Commands**", value="\u200b", inline=False)
    basic_commands = [
        ("`!help`", "Show this help message"),
        ("`!ping`", "Test if the bot is responsive"),
        ("`!setchannel`", "Set current channel for stock updates"),
    ]
    for cmd, desc in basic_commands:
        embed.add_field(name=cmd, value=desc, inline=True)
    
    # Watch list commands
    embed.add_field(name="📈 **Watch List**", value="\u200b", inline=False)
    watchlist_commands = [
        ("`!addstock <TICKER>`", "Add a stock to watch list"),
        ("`!removestock <TICKER>`", "Remove a stock from watch list"),
        ("`!stocks`", "List all watched stocks"),
        ("`!check [TICKER]`", "Check current prices"),
    ]
    for cmd, desc in watchlist_commands:
        embed.add_field(name=cmd, value=desc, inline=True)
    
    # Analysis commands
    embed.add_field(name="🔍 **Analysis**", value="\u200b", inline=False)
    analysis_commands = [
        ("`!compare <T1> <T2>...`", "Compare 2-5 stocks side-by-side"),
        ("`!chart <TICKER> [PERIOD]`", "Generate price chart (1d/5d/1mo/3mo/6mo/1y/5y)"),
    ]
    for cmd, desc in analysis_commands:
        embed.add_field(name=cmd, value=desc, inline=True)
    
    # Settings commands
    embed.add_field(name="⚙️ **Settings**", value="\u200b", inline=False)
    settings_commands = [
        ("`!setinterval <TIME>`", "Set update frequency (15m/30m/1h/2h/4h)"),
    ]
    for cmd, desc in settings_commands:
        embed.add_field(name=cmd, value=desc, inline=True)
    
    embed.set_footer(text="ℹ️ Auto-updates run Mon-Fri 4AM-8PM ET only")
    await ctx.send(embed=embed)


@bot.command()
async def setchannel(ctx):
    """Set the current channel for hourly stock updates."""
    config = load_config()
    config["channel_id"] = ctx.channel.id
    save_config(config)
    await ctx.send(f"✅ Stock updates will be posted to **#{ctx.channel.name}**")


@bot.command()
async def addstock(ctx, ticker: str = None):
    """Add a stock ticker to the watch list."""
    if not ticker:
        await ctx.send("❌ Please provide a ticker symbol. Example: `!addstock AAPL`")
        return
    
    ticker = ticker.upper()
    config = load_config()
    
    if ticker in config["stocks"]:
        await ctx.send(f"⚠️ **{ticker}** is already in the watch list.")
        return
    
    # Verify the ticker is valid
    await ctx.send(f"🔍 Checking **{ticker}**...")
    data = get_stock_data(ticker)
    
    if data is None:
        await ctx.send(f"❌ Could not find stock data for **{ticker}**. Please check the ticker symbol.")
        return
    
    config["stocks"].append(ticker)
    save_config(config)
    await ctx.send(f"✅ Added **{ticker}** to the watch list. Current price: ${data['price']:.2f}")


@bot.command()
async def removestock(ctx, ticker: str = None):
    """Remove a stock ticker from the watch list."""
    if not ticker:
        await ctx.send("❌ Please provide a ticker symbol. Example: `!removestock AAPL`")
        return
    
    ticker = ticker.upper()
    config = load_config()
    
    if ticker not in config["stocks"]:
        await ctx.send(f"⚠️ **{ticker}** is not in the watch list.")
        return
    
    config["stocks"].remove(ticker)
    save_config(config)
    await ctx.send(f"✅ Removed **{ticker}** from the watch list.")


@bot.command()
async def stocks(ctx):
    """List all stocks in the watch list."""
    config = load_config()
    stock_list = config.get("stocks", [])
    
    if not stock_list:
        await ctx.send("📋 The watch list is empty. Use `!addstock TICKER` to add stocks.")
        return
    
    stocks_str = ", ".join(f"**{s}**" for s in stock_list)
    await ctx.send(f"📋 **Watch List:** {stocks_str}")


@bot.command()
async def check(ctx, ticker: str = None):
    """Check current stock price(s). Use without argument to check all watched stocks."""
    config = load_config()
    
    if ticker:
        # Check single stock
        ticker = ticker.upper()
        await ctx.send(f"🔍 Fetching data for **{ticker}**...")
        data = get_stock_data(ticker)
        
        if data is None:
            await ctx.send(f"❌ Could not find stock data for **{ticker}**.")
            return
        
        embed = create_stock_embed([data])
        await ctx.send(embed=embed)
    else:
        # Check all watched stocks
        stock_list = config.get("stocks", [])
        
        if not stock_list:
            await ctx.send("📋 No stocks to check. Use `!addstock TICKER` to add stocks first.")
            return
        
        await ctx.send(f"🔍 Fetching data for {len(stock_list)} stock(s)...")
        stocks_data = await fetch_all_stocks(stock_list)
        embed = create_stock_embed(stocks_data)
        await ctx.send(embed=embed)


@bot.command()
async def setinterval(ctx, preset: str = None):
    """Set the update interval. Options: 15m, 30m, 1h, 2h, 4h"""
    if not preset or preset.lower() not in INTERVAL_PRESETS:
        presets_str = ", ".join(f"`{p}`" for p in INTERVAL_PRESETS.keys())
        await ctx.send(f"❌ Please provide a valid interval: {presets_str}")
        return
    
    preset = preset.lower()
    minutes = INTERVAL_PRESETS[preset]
    
    config = load_config()
    config["interval_minutes"] = minutes
    save_config(config)
    
    # Restart the scheduled task with new interval
    start_scheduled_task()
    
    # Calculate next update time
    next_time = get_next_interval_time(minutes)
    next_time_str = next_time.strftime("%I:%M %p ET")
    
    await ctx.send(f"✅ Update interval changed to **{preset}**.\nNext update at {next_time_str}.")


@bot.command()
async def compare(ctx, *tickers):
    """Compare 2-5 stocks side by side. Example: !compare AAPL MSFT GOOGL"""
    if len(tickers) < 2:
        await ctx.send("❌ Please provide at least 2 tickers. Example: `!compare AAPL MSFT GOOGL`")
        return
    
    if len(tickers) > 5:
        await ctx.send("❌ Maximum 5 stocks can be compared at once.")
        return
    
    tickers = [t.upper() for t in tickers]
    await ctx.send(f"🔍 Comparing {len(tickers)} stocks...")
    
    embed = discord.Embed(
        title="📊 Stock Comparison",
        color=discord.Color.purple(),
        timestamp=datetime.utcnow()
    )
    
    # Collect data for all stocks
    comparison_data = []
    for ticker in tickers:
        data = get_stock_data(ticker)
        if data:
            comparison_data.append(data)
    
    if not comparison_data:
        await ctx.send("❌ Could not fetch data for any of the provided tickers.")
        return
    
    # Build comparison fields
    # Price row
    prices = " | ".join(f"**{d['ticker']}**: ${d['price']:.2f}" for d in comparison_data)
    embed.add_field(name="💰 Price", value=prices, inline=False)
    
    # Daily change row
    changes = []
    for d in comparison_data:
        sign = "+" if d['change_percent'] >= 0 else ""
        emoji = "🟢" if d['change_percent'] >= 0 else "🔴"
        changes.append(f"{emoji} **{d['ticker']}**: {sign}{d['change_percent']:.2f}%")
    embed.add_field(name="📈 Daily Change", value=" | ".join(changes), inline=False)
    
    # 52-week context
    contexts = []
    for d in comparison_data:
        ctx_str = d.get('fifty_two_week_context') or 'N/A'
        contexts.append(f"**{d['ticker']}**: {ctx_str}")
    embed.add_field(name="📅 52-Week", value=" | ".join(contexts), inline=False)
    
    # P/E ratio (if available)
    pe_ratios = []
    for d in comparison_data:
        pe = d.get('pe_ratio')
        pe_str = f"{pe:.1f}" if pe else "N/A"
        pe_ratios.append(f"**{d['ticker']}**: {pe_str}")
    embed.add_field(name="📉 P/E Ratio", value=" | ".join(pe_ratios), inline=False)
    
    # Market cap (if available)
    def format_market_cap(mc):
        if mc is None:
            return "N/A"
        if mc >= 1e12:
            return f"${mc/1e12:.2f}T"
        elif mc >= 1e9:
            return f"${mc/1e9:.2f}B"
        elif mc >= 1e6:
            return f"${mc/1e6:.2f}M"
        return f"${mc:.0f}"
    
    market_caps = []
    for d in comparison_data:
        mc = format_market_cap(d.get('market_cap'))
        market_caps.append(f"**{d['ticker']}**: {mc}")
    embed.add_field(name="🏢 Market Cap", value=" | ".join(market_caps), inline=False)
    
    await ctx.send(embed=embed)


@bot.command()
async def chart(ctx, ticker: str = None, period: str = "1mo"):
    """Generate a price chart for a stock. Periods: 1d, 5d, 1mo, 3mo, 6mo, 1y, 5y"""
    if not ticker:
        await ctx.send("❌ Please provide a ticker symbol. Example: `!chart AAPL 1mo`")
        return
    
    ticker = ticker.upper()
    valid_periods = ['1d', '5d', '1mo', '3mo', '6mo', '1y', '5y']
    
    if period.lower() not in valid_periods:
        await ctx.send(f"❌ Invalid period. Valid options: {', '.join(valid_periods)}")
        return
    
    period = period.lower()
    await ctx.send(f"🔍 Generating chart for **{ticker}** ({period})...")
    
    try:
        stock = yf.Ticker(ticker)
        
        # Determine interval based on period
        interval_map = {
            '1d': '5m',
            '5d': '15m',
            '1mo': '1d',
            '3mo': '1d',
            '6mo': '1d',
            '1y': '1wk',
            '5y': '1mo'
        }
        interval = interval_map.get(period, '1d')
        
        hist = stock.history(period=period, interval=interval)
        
        if hist.empty:
            await ctx.send(f"❌ No historical data available for **{ticker}**.")
            return
        
        # Create the chart with dark theme
        plt.style.use('dark_background')
        fig, ax = plt.subplots(figsize=(10, 5))
        
        # Plot price line
        ax.plot(hist.index, hist['Close'], color='#00d4aa', linewidth=2)
        
        # Fill under the line
        ax.fill_between(hist.index, hist['Close'], alpha=0.3, color='#00d4aa')
        
        # Formatting
        ax.set_title(f'{ticker} - {period.upper()}', fontsize=16, fontweight='bold', color='white')
        ax.set_xlabel('')
        ax.set_ylabel('Price ($)', fontsize=12, color='white')
        
        # Format x-axis dates
        if period in ['1d', '5d']:
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
        elif period in ['1mo', '3mo']:
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%b %d'))
        else:
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%b %Y'))
        
        plt.xticks(rotation=45)
        ax.grid(True, alpha=0.3)
        
        # Add current price annotation
        current_price = hist['Close'].iloc[-1]
        ax.annotate(f'${current_price:.2f}', 
                   xy=(hist.index[-1], current_price),
                   xytext=(10, 0), textcoords='offset points',
                   fontsize=12, color='#00d4aa', fontweight='bold')
        
        plt.tight_layout()
        
        # Save to buffer
        buf = io.BytesIO()
        plt.savefig(buf, format='png', dpi=100, facecolor='#2f3136', edgecolor='none')
        buf.seek(0)
        plt.close()
        
        # Send as file
        file = discord.File(buf, filename=f'{ticker}_chart.png')
        await ctx.send(file=file)
        
    except Exception as e:
        await ctx.send(f"❌ Could not generate chart for **{ticker}**.")
        plt.close()


bot.run(TOKEN)
