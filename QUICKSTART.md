# Quick Start Guide - Macau Lottery Bot

## 🚀 Get Started in 3 Minutes

### Prerequisites
- Python 3.8 or higher
- pip (Python package installer)
- Telegram account
- Bot token from @BotFather

### Step 1: Get Your Bot Token (2 minutes)

1. Open Telegram and search for `@BotFather`
2. Send `/newbot` command
3. Follow prompts to create your bot:
   - Choose a name (e.g., "My Lottery Bot")
   - Choose a username (e.g., "my_lottery_bot")
4. Copy the bot token (looks like: `1234567890:ABCdefGHIjklMNOpqrsTUVwxyz`)

### Step 2: Setup Bot (1 minute)

```bash
# Clone or download the repository
cd fcbot

# Install dependencies
pip install -r requirements.txt

# Copy environment template
cp .env.example .env

# Edit .env and paste your bot token
# Replace 'your_bot_token_here' with the actual token from BotFather
nano .env  # or use any text editor
```

Your `.env` file should look like:
```env
TELEGRAM_BOT_TOKEN=1234567890:ABCdefGHIjklMNOpqrsTUVwxyz
```

### Step 3: Run the Bot (30 seconds)

```bash
python bot.py
```

You should see:
```
INFO - Database initialized successfully
INFO - Scheduler started
INFO - Bot started successfully
```

### Step 4: Test Your Bot

1. Open Telegram
2. Search for your bot username
3. Send `/start`
4. You should see the main menu! 🎉

## 🎯 What You Can Do Now

### For Users:
- 🎯 **Get Predictions**: Click "智能预测" to get AI predictions
- 📊 **Check Results**: Click "最新开奖" to see latest lottery results
- 📈 **View Analysis**: Click "数据分析" for statistical analysis
- 📜 **History**: Click "历史记录" to view past results
- ⚙️ **Settings**: Enable notifications and reminders

### For Developers:
- Check `lottery_bot.log` for debug info
- Database is created at `lottery.db`
- Modify prediction algorithms in `PredictionEngine` class

## 🔧 Configuration Options

Edit `.env` to customize:

```env
# Required
TELEGRAM_BOT_TOKEN=your_token_here

# Optional
ADMIN_USER_ID=123456789           # Your Telegram user ID for admin features
CHECK_INTERVAL=5                   # How often to check for new results (minutes)
DATABASE_PATH=lottery.db          # Database file location
TIMEZONE=Asia/Shanghai            # Timezone for lottery time
LOTTERY_TIME=21:32:32             # Daily lottery time
```

## 🐛 Troubleshooting

### Bot doesn't start
```bash
# Check if token is correct
cat .env | grep TELEGRAM_BOT_TOKEN

# Verify dependencies installed
pip install -r requirements.txt --upgrade
```

### Bot starts but doesn't respond
- Make sure you're messaging the correct bot
- Check the bot username matches what you created in BotFather
- Look for errors in `lottery_bot.log`

### Database errors
```bash
# Remove and recreate database
rm lottery.db
python bot.py  # Will auto-create fresh database
```

### API errors
- Check your internet connection
- API might be temporarily down - wait and retry
- Check `lottery_bot.log` for specific error messages

## 📱 Using the Bot

### Main Features:

1. **智能预测 (Smart Predictions)**
   - AI综合预测: Multi-factor weighted prediction
   - 生肖预测: Zodiac-based prediction
   - 热号预测: Hot numbers (recent frequent)
   - 冷号预测: Cold numbers (long missing)

2. **最新开奖 (Latest Results)**
   - Shows latest lottery draw
   - Displays countdown to next draw

3. **数据分析 (Data Analysis)**
   - 频率分析: Frequency statistics
   - 生肖分布: Zodiac distribution
   - 遗漏分析: Missing number analysis
   - 冷热分析: Hot/cold comparison

4. **历史记录 (History)**
   - Query last 10/20/30/50 draws
   - Complete draw information

5. **个人设置 (Settings)**
   - Toggle draw notifications
   - Toggle 21:00 reminder
   - Toggle auto-prediction

## 🎉 You're All Set!

Your Macau Lottery Bot is ready to use. Enjoy predictions! 🎰

## 📚 Need More Help?

- Read full documentation in `README.md`
- Check feature list in `FEATURES.md`
- Review security info in `SECURITY_SUMMARY.md`
- See implementation details in `IMPLEMENTATION_SUMMARY.md`

## ⚠️ Important Notes

- Predictions are for entertainment only
- Not financial or investment advice
- Please gamble responsibly
- Bot runs 24/7 - keep it running for auto-notifications

---

**Happy Predicting!** 🎲
