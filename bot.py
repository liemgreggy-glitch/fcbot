#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Macau Lottery Telegram Bot (澳门六合彩预测机器人)
Complete bot with prediction, analysis, and automation features
"""

import os
import sys
import logging
import sqlite3
import json
import random
from datetime import datetime, timedelta, time
from typing import List, Dict, Tuple, Optional
from collections import Counter, defaultdict
import asyncio

import requests
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    filters,
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
import pytz

# Load environment variables
load_dotenv()

# Configuration
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ADMIN_USER_ID = os.getenv("ADMIN_USER_ID")
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", "5"))
DATABASE_PATH = os.getenv("DATABASE_PATH", "lottery.db")
TIMEZONE = os.getenv("TIMEZONE", "Asia/Shanghai")
LOTTERY_TIME = os.getenv("LOTTERY_TIME", "21:32:32")

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('lottery_bot.log', encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# Zodiac mapping (correct mapping verified with real API data)
ZODIAC_NUMBERS = {
    '鼠': [6, 18, 30, 42],
    '牛': [5, 17, 29, 41],
    '虎': [4, 16, 28, 40],
    '兔': [3, 15, 27, 39],
    '龙': [2, 14, 26, 38],
    '蛇': [1, 13, 25, 37, 49],
    '马': [12, 24, 36, 48],
    '羊': [11, 23, 35, 47],
    '猴': [10, 22, 34, 46],
    '鸡': [9, 21, 33, 45],
    '狗': [8, 20, 32, 44],
    '猪': [7, 19, 31, 43]
}

# Zodiac emoji mapping
ZODIAC_EMOJI = {
    '鼠': '🐭', '牛': '🐮', '虎': '🐯', '兔': '🐰',
    '龙': '🐉', '蛇': '🐍', '马': '🐴', '羊': '🐑',
    '猴': '🐵', '鸡': '🐔', '狗': '🐶', '猪': '🐖'
}

# Reverse mapping: number to zodiac
NUMBER_TO_ZODIAC = {}
for zodiac, numbers in ZODIAC_NUMBERS.items():
    for num in numbers:
        NUMBER_TO_ZODIAC[num] = zodiac


class DatabaseHandler:
    """Handle all database operations"""
    
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.init_database()
    
    def get_connection(self):
        """Get database connection"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn
    
    def init_database(self):
        """Initialize database tables"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        # Lottery history table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS lottery_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                expect TEXT UNIQUE NOT NULL,
                open_code TEXT NOT NULL,
                tema INTEGER NOT NULL,
                tema_zodiac TEXT NOT NULL,
                open_time TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # User settings table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_settings (
                user_id INTEGER PRIMARY KEY,
                notify_enabled INTEGER DEFAULT 1,
                reminder_enabled INTEGER DEFAULT 0,
                auto_predict INTEGER DEFAULT 0,
                default_period INTEGER DEFAULT 10,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Prediction history table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS prediction_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                expect TEXT NOT NULL,
                predicted_top5 TEXT NOT NULL,
                actual_tema INTEGER,
                is_hit INTEGER DEFAULT 0,
                hit_rank INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        conn.commit()
        conn.close()
        logger.info("Database initialized successfully")
    
    def save_lottery_result(self, expect: str, open_code: List[int], tema: int, tema_zodiac: str, open_time: str):
        """Save lottery result to database"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                INSERT OR REPLACE INTO lottery_history 
                (expect, open_code, tema, tema_zodiac, open_time)
                VALUES (?, ?, ?, ?, ?)
            ''', (expect, json.dumps(open_code), tema, tema_zodiac, open_time))
            conn.commit()
            logger.info(f"Saved lottery result: {expect}")
            return True
        except Exception as e:
            logger.error(f"Error saving lottery result: {e}")
            return False
        finally:
            conn.close()
    
    def get_latest_result(self) -> Optional[Dict]:
        """Get latest lottery result"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM lottery_history ORDER BY expect DESC LIMIT 1')
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return {
                'expect': row['expect'],
                'open_code': json.loads(row['open_code']),
                'tema': row['tema'],
                'tema_zodiac': row['tema_zodiac'],
                'open_time': row['open_time']
            }
        return None
    
    def get_history(self, limit: int = 10) -> List[Dict]:
        """Get lottery history"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM lottery_history ORDER BY expect DESC LIMIT ?', (limit,))
        rows = cursor.fetchall()
        conn.close()
        
        results = []
        for row in rows:
            results.append({
                'expect': row['expect'],
                'open_code': json.loads(row['open_code']),
                'tema': row['tema'],
                'tema_zodiac': row['tema_zodiac'],
                'open_time': row['open_time']
            })
        return results
    
    def is_database_empty(self) -> bool:
        """Check if lottery history database is empty"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT COUNT(*) as count FROM lottery_history')
        count = cursor.fetchone()['count']
        conn.close()
        return count == 0
    
    def get_user_settings(self, user_id: int) -> Dict:
        """Get user settings"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM user_settings WHERE user_id = ?', (user_id,))
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return dict(row)
        else:
            # Create default settings
            return self.create_user_settings(user_id)
    
    def create_user_settings(self, user_id: int) -> Dict:
        """Create default user settings"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO user_settings (user_id) VALUES (?)
        ''', (user_id,))
        conn.commit()
        conn.close()
        return self.get_user_settings(user_id)
    
    def update_user_setting(self, user_id: int, setting: str, value: int):
        """Update user setting with secure column validation"""
        # Whitelist of allowed settings to prevent SQL injection
        allowed_settings = {
            'notify_enabled': 'notify_enabled',
            'reminder_enabled': 'reminder_enabled',
            'auto_predict': 'auto_predict',
            'default_period': 'default_period'
        }
        
        if setting not in allowed_settings:
            raise ValueError(f"Invalid setting: {setting}")
        
        # Use validated column name
        column_name = allowed_settings[setting]
        
        conn = self.get_connection()
        cursor = conn.cursor()
        query = f'UPDATE user_settings SET {column_name} = ?, updated_at = CURRENT_TIMESTAMP WHERE user_id = ?'
        cursor.execute(query, (value, user_id))
        conn.commit()
        conn.close()
    
    def save_prediction(self, expect: str, predicted_top5: List[int], actual_tema: Optional[int] = None):
        """Save prediction to database"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        is_hit = 0
        hit_rank = None
        if actual_tema and actual_tema in predicted_top5:
            is_hit = 1
            hit_rank = predicted_top5.index(actual_tema) + 1
        
        cursor.execute('''
            INSERT INTO prediction_history 
            (expect, predicted_top5, actual_tema, is_hit, hit_rank)
            VALUES (?, ?, ?, ?, ?)
        ''', (expect, json.dumps(predicted_top5), actual_tema, is_hit, hit_rank))
        conn.commit()
        conn.close()
    
    def get_all_notify_users(self) -> List[int]:
        """Get all users with notifications enabled"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT user_id FROM user_settings WHERE notify_enabled = 1')
        users = [row['user_id'] for row in cursor.fetchall()]
        conn.close()
        return users
    
    def get_all_reminder_users(self) -> List[int]:
        """Get all users with reminders enabled"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT user_id FROM user_settings WHERE reminder_enabled = 1')
        users = [row['user_id'] for row in cursor.fetchall()]
        conn.close()
        return users


class APIHandler:
    """Handle API calls to lottery service"""
    
    BASE_URL = "https://macaumarksix.com/api"
    HISTORY_URL = "https://history.macaumarksix.com/history/macaujc2/y"
    
    @staticmethod
    def get_latest_result() -> Optional[Dict]:
        """Get latest lottery result from API"""
        try:
            response = requests.get(f"{APIHandler.BASE_URL}/macaujc2.com", timeout=10)
            response.raise_for_status()
            data = response.json()
            
            if data and len(data) > 0:
                latest = data[0]
                open_code = [int(x.strip()) for x in latest['openCode'].split(',')]
                
                # Handle zodiac - could be a list or comma-separated string
                if isinstance(latest.get('zodiac'), list):
                    zodiacs = latest['zodiac']
                else:
                    zodiacs = [x.strip() for x in latest.get('zodiac', '').split(',')]
                
                tema = open_code[6]  # 7th number (index 6)
                tema_zodiac = zodiacs[6] if len(zodiacs) > 6 else NUMBER_TO_ZODIAC.get(tema, '未知')
                
                return {
                    'expect': latest['expect'],
                    'open_code': open_code,
                    'tema': tema,
                    'tema_zodiac': tema_zodiac,
                    'open_time': latest['openTime']
                }
            return None
        except Exception as e:
            logger.error(f"Error fetching latest result: {e}")
            return None
    
    @staticmethod
    def get_live_result() -> Optional[Dict]:
        """Get live lottery result"""
        try:
            response = requests.get(f"{APIHandler.BASE_URL}/live2", timeout=10)
            response.raise_for_status()
            data = response.json()
            
            if data and 'openCode' in data:
                open_code = [int(x.strip()) for x in data['openCode'].split(',')]
                if len(open_code) >= 7:
                    tema = open_code[6]
                    
                    # Handle zodiac - could be a list or comma-separated string
                    if 'zodiac' in data:
                        if isinstance(data['zodiac'], list):
                            zodiacs = data['zodiac']
                        else:
                            zodiacs = [x.strip() for x in data['zodiac'].split(',')]
                        tema_zodiac = zodiacs[6] if len(zodiacs) > 6 else NUMBER_TO_ZODIAC.get(tema, '未知')
                    else:
                        tema_zodiac = NUMBER_TO_ZODIAC.get(tema, '未知')
                    
                    return {
                        'expect': data['expect'],
                        'open_code': open_code,
                        'tema': tema,
                        'tema_zodiac': tema_zodiac,
                        'open_time': data.get('openTime', '')
                    }
            return None
        except Exception as e:
            logger.error(f"Error fetching live result: {e}")
            return None
    
    @staticmethod
    def get_history(year: int) -> List[Dict]:
        """Get historical results for a year"""
        try:
            response = requests.get(f"{APIHandler.HISTORY_URL}/{year}", timeout=30)
            response.raise_for_status()
            data = response.json()
            
            # Handle new API format with result/code/data structure
            if data.get('result') and data.get('code') == 200:
                items = data.get('data', [])
            else:
                logger.warning(f"Unexpected API response for {year}: {data.get('message', 'Unknown error')}")
                items = []
            
            results = []
            for item in items:
                open_code = [int(x.strip()) for x in item['openCode'].split(',')]
                zodiacs = [x.strip() for x in item['zodiac'].split(',')]
                
                tema = open_code[6]  # 7th number (index 6)
                tema_zodiac = zodiacs[6]  # 7th zodiac
                
                results.append({
                    'expect': item['expect'],
                    'open_code': open_code,
                    'tema': tema,
                    'tema_zodiac': tema_zodiac,
                    'open_time': item['openTime']
                })
            return results
        except Exception as e:
            logger.error(f"Error fetching history for {year}: {e}")
            return []


def get_zodiac_from_number(number: int) -> Optional[str]:
    """Get zodiac from number using lookup table"""
    for zodiac, numbers in ZODIAC_NUMBERS.items():
        if number in numbers:
            return zodiac
    return None


def extract_tema_info(open_code: str, zodiac_str: str) -> Dict:
    """Extract tema information with dual verification"""
    codes = [int(x.strip()) for x in open_code.split(',')]
    zodiacs = [x.strip() for x in zodiac_str.split(',')]
    
    tema_number = codes[6]  # 7th number (index 6)
    tema_zodiac_api = zodiacs[6]  # API returned zodiac
    
    # Verify through number lookup table
    tema_zodiac_calculated = get_zodiac_from_number(tema_number)
    
    # Verify consistency
    if tema_zodiac_api != tema_zodiac_calculated:
        logger.warning(
            f"⚠️ Zodiac mismatch! Codes:{codes}, Number:{tema_number}, "
            f"API:{tema_zodiac_api}, Calculated:{tema_zodiac_calculated}"
        )
    
    return {
        'number': tema_number,
        'zodiac': tema_zodiac_api,  # Prioritize API returned
        'emoji': ZODIAC_EMOJI.get(tema_zodiac_api, '❓')
    }


def sync_history_data(db_handler: DatabaseHandler) -> int:
    """Sync historical data on first startup"""
    logger.info("🔄 Starting history data sync...")
    
    total_synced = 0
    for year in [2024, 2025, 2026]:
        try:
            logger.info(f"Fetching {year} data...")
            results = APIHandler.get_history(year)
            
            for result in results:
                try:
                    db_handler.save_lottery_result(
                        expect=result['expect'],
                        open_code=result['open_code'],
                        tema=result['tema'],
                        tema_zodiac=result['tema_zodiac'],
                        open_time=result['open_time']
                    )
                    total_synced += 1
                except Exception as e:
                    logger.error(f"Failed to save {result.get('expect', 'unknown')}: {e}")
            
            logger.info(f"✅ {year} data synced successfully: {len(results)} records")
            
        except Exception as e:
            logger.error(f"❌ {year} data sync failed: {e}")
    
    logger.info(f"🎉 History data sync completed! Total synced: {total_synced} records")
    return total_synced


class PredictionEngine:
    """AI prediction engine for lottery numbers"""
    
    def __init__(self, db_handler: DatabaseHandler):
        self.db = db_handler
    
    def predict_top5(self, method: str = 'comprehensive') -> Tuple[List[int], Dict]:
        """Predict top 5 tema numbers with scores"""
        history = self.db.get_history(100)
        
        if not history:
            # Random prediction if no history (1-49, excluding 50)
            top5 = random.sample(range(1, 50), 5)
            scores = {num: 50.0 for num in top5}
            return top5, scores
        
        if method == 'frequency':
            return self._predict_by_frequency(history)
        elif method == 'zodiac':
            return self._predict_by_zodiac(history)
        elif method == 'hot':
            return self._predict_hot_numbers(history)
        elif method == 'cold':
            return self._predict_cold_numbers(history)
        else:  # comprehensive
            return self._predict_comprehensive(history)
    
    def _predict_by_frequency(self, history: List[Dict]) -> Tuple[List[int], Dict]:
        """Predict based on frequency analysis"""
        tema_list = [h['tema'] for h in history]
        counter = Counter(tema_list)
        most_common = counter.most_common(5)
        
        top5 = [num for num, _ in most_common]
        total = sum(count for _, count in most_common)
        scores = {num: (count / total * 100) for num, count in most_common}
        
        return top5, scores
    
    def _predict_by_zodiac(self, history: List[Dict]) -> Tuple[List[int], Dict]:
        """Predict based on zodiac cycle"""
        zodiac_list = [h['tema_zodiac'] for h in history[:20]]
        zodiac_counter = Counter(zodiac_list)
        
        # Find least appeared zodiacs
        all_zodiacs = list(ZODIAC_NUMBERS.keys())
        zodiac_scores = {z: zodiac_counter.get(z, 0) for z in all_zodiacs}
        sorted_zodiacs = sorted(zodiac_scores.items(), key=lambda x: x[1])
        
        # Pick numbers from top zodiacs
        top5 = []
        scores = {}
        for zodiac, count in sorted_zodiacs[:5]:
            num = random.choice(ZODIAC_NUMBERS[zodiac])
            top5.append(num)
            scores[num] = 80.0 - count * 2
        
        return top5, scores
    
    def _predict_hot_numbers(self, history: List[Dict]) -> Tuple[List[int], Dict]:
        """Predict hot numbers (most recent frequent)"""
        recent_tema = [h['tema'] for h in history[:30]]
        counter = Counter(recent_tema)
        most_common = counter.most_common(5)
        
        top5 = [num for num, _ in most_common]
        total = sum(count for _, count in most_common)
        scores = {num: (count / total * 100) for num, count in most_common}
        
        return top5, scores
    
    def _predict_cold_numbers(self, history: List[Dict]) -> Tuple[List[int], Dict]:
        """Predict cold numbers (least appeared)"""
        tema_list = [h['tema'] for h in history[:50]]
        counter = Counter(tema_list)
        
        # Find numbers that haven't appeared (1-49 only, 50 is rare special case)
        all_numbers = set(range(1, 50))
        appeared = set(tema_list)
        not_appeared = all_numbers - appeared
        
        if len(not_appeared) >= 5:
            top5 = random.sample(list(not_appeared), 5)
            scores = {num: 90.0 for num in top5}
        else:
            # Get least common
            least_common = counter.most_common()[:-6:-1]
            top5 = [num for num, _ in least_common]
            scores = {num: 70.0 for num in top5}
        
        return top5, scores
    
    def _predict_comprehensive(self, history: List[Dict]) -> Tuple[List[int], Dict]:
        """Comprehensive prediction with weighted factors
        
        Note: Predicts only numbers 1-49. Number 50 exists in zodiac mapping for 狗
        but is extremely rare in actual lottery draws, so excluded from predictions.
        """
        all_scores = defaultdict(float)
        
        # Factor 1: Frequency analysis (35% weight)
        tema_list = [h['tema'] for h in history]
        counter = Counter(tema_list)
        total_count = len(tema_list)
        for num in range(1, 50):  # 1-49 only
            freq = counter.get(num, 0)
            all_scores[num] += (freq / total_count) * 35
        
        # Factor 2: Missing value analysis (30% weight)
        recent = [h['tema'] for h in history[:20]]
        for num in range(1, 50):  # 1-49 only
            if num not in recent:
                all_scores[num] += 30
            else:
                # Penalty for recently appeared
                last_idx = recent.index(num)
                all_scores[num] += (last_idx / 20) * 30
        
        # Factor 3: Zodiac cycle (25% weight)
        zodiac_list = [h['tema_zodiac'] for h in history[:15]]
        zodiac_counter = Counter(zodiac_list)
        for num in range(1, 50):  # 1-49 only
            zodiac = NUMBER_TO_ZODIAC.get(num)
            if zodiac:
                zodiac_freq = zodiac_counter.get(zodiac, 0)
                all_scores[num] += (1 - zodiac_freq / 15) * 25
        
        # Factor 4: Random factor (10% weight)
        for num in range(1, 50):  # 1-49 only
            all_scores[num] += random.uniform(0, 10)
        
        # Get top 5
        sorted_nums = sorted(all_scores.items(), key=lambda x: x[1], reverse=True)
        top5 = [num for num, _ in sorted_nums[:5]]
        scores = {num: score for num, score in sorted_nums[:5]}
        
        return top5, scores
    
    def get_hot_cold_analysis(self, period: int = 30) -> Dict:
        """Get hot and cold numbers analysis (1-49 range)"""
        history = self.db.get_history(period)
        tema_list = [h['tema'] for h in history]
        counter = Counter(tema_list)
        
        # Hot numbers (top 10)
        hot = counter.most_common(10)
        
        # Cold numbers (bottom 10, excluding 50 as it's extremely rare)
        all_numbers = set(range(1, 50))
        appeared = set(tema_list)
        not_appeared = list(all_numbers - appeared)
        
        cold = []
        for num in not_appeared[:10]:
            cold.append((num, 0))
        
        # Add least appeared if not enough
        if len(cold) < 10:
            least_common = counter.most_common()[:-11:-1]
            cold.extend(least_common[:(10 - len(cold))])
        
        return {'hot': hot, 'cold': cold, 'period': period}
    
    def get_zodiac_distribution(self, period: int = 50) -> Dict:
        """Get zodiac distribution analysis"""
        history = self.db.get_history(period)
        zodiac_list = [h['tema_zodiac'] for h in history]
        counter = Counter(zodiac_list)
        
        distribution = {}
        for zodiac in ZODIAC_NUMBERS.keys():
            count = counter.get(zodiac, 0)
            percentage = (count / len(zodiac_list) * 100) if zodiac_list else 0
            distribution[zodiac] = {'count': count, 'percentage': percentage}
        
        return distribution
    
    def get_missing_analysis(self) -> Dict:
        """Analyze missing numbers (1-49 range)"""
        history = self.db.get_history(50)
        tema_list = [h['tema'] for h in history]
        
        # Track last appearance
        last_appearance = {}
        for idx, tema in enumerate(tema_list):
            if tema not in last_appearance:
                last_appearance[tema] = idx
        
        # Find missing numbers (1-49 only)
        all_numbers = set(range(1, 50))
        missing = []
        for num in all_numbers:
            if num not in last_appearance:
                missing.append((num, 50))  # Not appeared in last 50
            else:
                missing.append((num, last_appearance[num]))
        
        # Sort by missing periods
        missing.sort(key=lambda x: x[1], reverse=True)
        
        return {'missing': missing[:15]}


class LotteryBot:
    """Main Telegram bot handler"""
    
    def __init__(self):
        self.db = DatabaseHandler(DATABASE_PATH)
        self.api = APIHandler()
        self.predictor = PredictionEngine(self.db)
        self.tz = pytz.timezone(TIMEZONE)
        self.last_expect = None
        
    def get_countdown(self) -> str:
        """Get countdown to next lottery time"""
        now = datetime.now(self.tz)
        lottery_time_parts = LOTTERY_TIME.split(':')
        target_time = now.replace(
            hour=int(lottery_time_parts[0]),
            minute=int(lottery_time_parts[1]),
            second=int(lottery_time_parts[2]),
            microsecond=0
        )
        
        # If already passed today, target tomorrow
        if now >= target_time:
            target_time += timedelta(days=1)
        
        diff = target_time - now
        hours, remainder = divmod(diff.seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command"""
        user = update.effective_user
        self.db.get_user_settings(user.id)  # Create if not exists
        
        countdown = self.get_countdown()
        
        message = f"""
🎰 <b>澳门六合彩预测机器人</b> 🎰

👋 欢迎，{user.first_name}！

📅 今日开奖倒计时：<code>{countdown}</code>
⏰ 开奖时间：每晚 {LOTTERY_TIME}

✨ <b>功能导航</b> ✨
• 🎯 智能预测 - AI预测特码TOP5
• 📊 最新开奖 - 查看最新结果
• 📈 数据分析 - 频率/生肖/冷热分析
• 📜 历史记录 - 查询历史开奖
• ⚙️ 个人设置 - 通知提醒设置

⚠️ <b>免责声明</b>
本机器人仅供娱乐和学习参考，预测结果不构成任何投资建议。请理性娱乐，谨慎决策。

请选择功能：
"""
        
        keyboard = [
            [
                InlineKeyboardButton("🎯 智能预测", callback_data="menu_predict"),
                InlineKeyboardButton("📊 最新开奖", callback_data="latest_result"),
            ],
            [
                InlineKeyboardButton("📈 数据分析", callback_data="menu_analysis"),
                InlineKeyboardButton("📜 历史记录", callback_data="menu_history"),
            ],
            [
                InlineKeyboardButton("⚙️ 个人设置", callback_data="menu_settings"),
                InlineKeyboardButton("❓ 帮助", callback_data="help"),
            ],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(message, reply_markup=reply_markup, parse_mode='HTML')
    
    async def button_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle button callbacks"""
        query = update.callback_query
        await query.answer()
        
        data = query.data
        
        # Menu handlers
        if data == "menu_predict":
            await self.show_predict_menu(query)
        elif data == "menu_analysis":
            await self.show_analysis_menu(query)
        elif data == "menu_history":
            await self.show_history_menu(query)
        elif data == "menu_settings":
            await self.show_settings_menu(query)
        elif data == "back_to_main":
            await self.back_to_main(query)
        
        # Prediction handlers
        elif data.startswith("predict_"):
            method = data.replace("predict_", "")
            await self.show_prediction(query, method)
        
        # Analysis handlers
        elif data == "analysis_frequency":
            await self.show_frequency_analysis(query)
        elif data == "analysis_zodiac":
            await self.show_zodiac_analysis(query)
        elif data == "analysis_missing":
            await self.show_missing_analysis(query)
        elif data == "analysis_hotcold":
            await self.show_hotcold_analysis(query)
        
        # History handlers
        elif data.startswith("history_"):
            limit = int(data.replace("history_", ""))
            await self.show_history(query, limit)
        
        # Settings handlers
        elif data.startswith("setting_"):
            await self.toggle_setting(query, data)
        
        # Latest result
        elif data == "latest_result":
            await self.show_latest_result(query)
        
        # Help
        elif data == "help":
            await self.show_help(query)
    
    async def show_predict_menu(self, query):
        """Show prediction menu"""
        message = """
🎯 <b>智能预测菜单</b>

请选择预测方式：

• <b>AI综合预测</b> - 多因素综合分析
• <b>生肖预测</b> - 基于生肖周期
• <b>热号预测</b> - 近期高频号码
• <b>冷号预测</b> - 长期未出号码

⚠️ 预测仅供参考，不保证准确性
"""
        
        keyboard = [
            [InlineKeyboardButton("🤖 AI综合预测", callback_data="predict_comprehensive")],
            [InlineKeyboardButton("🐲 生肖预测", callback_data="predict_zodiac")],
            [
                InlineKeyboardButton("🔥 热号预测", callback_data="predict_hot"),
                InlineKeyboardButton("❄️ 冷号预测", callback_data="predict_cold"),
            ],
            [InlineKeyboardButton("🔙 返回主菜单", callback_data="back_to_main")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='HTML')
    
    async def show_prediction(self, query, method: str):
        """Show prediction result"""
        top5, scores = self.predictor.predict_top5(method)
        
        method_names = {
            'comprehensive': 'AI综合预测',
            'zodiac': '生肖预测',
            'hot': '热号预测',
            'cold': '冷号预测',
            'frequency': '频率预测'
        }
        
        message = f"🎯 <b>{method_names.get(method, '预测')}</b>\n\n"
        message += "📊 <b>TOP5 特码预测：</b>\n\n"
        
        for idx, num in enumerate(top5, 1):
            zodiac = NUMBER_TO_ZODIAC.get(num, '未知')
            zodiac_emoji = ZODIAC_EMOJI.get(zodiac, '')
            score = scores.get(num, 0)
            bar = "█" * int(score / 10)
            message += f"{idx}. 号码 <b>{num:02d}</b> {zodiac_emoji}{zodiac} - {score:.1f}%\n"
            message += f"   {bar}\n\n"
        
        countdown = self.get_countdown()
        message += f"\n⏰ 距离开奖：<code>{countdown}</code>\n"
        message += "\n⚠️ <i>预测仅供参考，请理性对待</i>"
        
        # Save prediction
        latest = self.db.get_latest_result()
        if latest:
            next_expect = str(int(latest['expect']) + 1)
            self.db.save_prediction(next_expect, top5)
        
        keyboard = [
            [InlineKeyboardButton("🔄 重新预测", callback_data=f"predict_{method}")],
            [InlineKeyboardButton("🔙 返回预测菜单", callback_data="menu_predict")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='HTML')
    
    async def show_analysis_menu(self, query):
        """Show analysis menu"""
        message = """
📈 <b>数据分析菜单</b>

多维度分析特码走势：

• <b>频率分析</b> - 号码出现频次统计
• <b>生肖分布</b> - 各生肖出现比例
• <b>遗漏分析</b> - 长期未出号码
• <b>冷热分析</b> - 冷热号码对比

选择分析类型：
"""
        
        keyboard = [
            [
                InlineKeyboardButton("📊 频率分析", callback_data="analysis_frequency"),
                InlineKeyboardButton("🐲 生肖分布", callback_data="analysis_zodiac"),
            ],
            [
                InlineKeyboardButton("⏱ 遗漏分析", callback_data="analysis_missing"),
                InlineKeyboardButton("🌡 冷热分析", callback_data="analysis_hotcold"),
            ],
            [InlineKeyboardButton("🔙 返回主菜单", callback_data="back_to_main")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='HTML')
    
    async def show_frequency_analysis(self, query):
        """Show frequency analysis"""
        history = self.db.get_history(50)
        
        if not history:
            await query.edit_message_text("暂无历史数据")
            return
        
        tema_list = [h['tema'] for h in history]
        counter = Counter(tema_list)
        most_common = counter.most_common(10)
        
        message = "📊 <b>频率分析（最近50期）</b>\n\n"
        message += "<b>Top 10 高频号码：</b>\n\n"
        
        for idx, (num, count) in enumerate(most_common, 1):
            zodiac = NUMBER_TO_ZODIAC.get(num, '未知')
            zodiac_emoji = ZODIAC_EMOJI.get(zodiac, '')
            percentage = (count / len(tema_list)) * 100
            bar = "█" * int(percentage * 2)
            message += f"{idx}. <b>{num:02d}</b> {zodiac_emoji}{zodiac} - {count}次 ({percentage:.1f}%)\n"
            message += f"   {bar}\n"
        
        keyboard = [[InlineKeyboardButton("🔙 返回分析菜单", callback_data="menu_analysis")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='HTML')
    
    async def show_zodiac_analysis(self, query):
        """Show zodiac distribution"""
        distribution = self.predictor.get_zodiac_distribution(50)
        
        message = "🐲 <b>生肖分布（最近50期）</b>\n\n"
        
        # Sort by count
        sorted_zodiac = sorted(distribution.items(), key=lambda x: x[1]['count'], reverse=True)
        
        for zodiac, data in sorted_zodiac:
            count = data['count']
            percentage = data['percentage']
            zodiac_emoji = ZODIAC_EMOJI.get(zodiac, '')
            bar = "█" * int(percentage / 2)
            message += f"{zodiac_emoji}<b>{zodiac}</b> - {count}次 ({percentage:.1f}%)\n"
            message += f"{bar}\n"
        
        keyboard = [[InlineKeyboardButton("🔙 返回分析菜单", callback_data="menu_analysis")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='HTML')
    
    async def show_missing_analysis(self, query):
        """Show missing numbers analysis"""
        analysis = self.predictor.get_missing_analysis()
        missing = analysis['missing']
        
        message = "⏱ <b>遗漏分析（最近50期）</b>\n\n"
        message += "<b>Top 15 遗漏号码：</b>\n\n"
        
        for idx, (num, periods) in enumerate(missing, 1):
            zodiac = NUMBER_TO_ZODIAC.get(num, '未知')
            zodiac_emoji = ZODIAC_EMOJI.get(zodiac, '')
            if periods >= 50:
                status = "未出现"
            else:
                status = f"{periods}期"
            message += f"{idx}. <b>{num:02d}</b> {zodiac_emoji}{zodiac} - {status}\n"
        
        keyboard = [[InlineKeyboardButton("🔙 返回分析菜单", callback_data="menu_analysis")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='HTML')
    
    async def show_hotcold_analysis(self, query):
        """Show hot and cold numbers"""
        analysis = self.predictor.get_hot_cold_analysis(30)
        
        message = f"🌡 <b>冷热分析（最近{analysis['period']}期）</b>\n\n"
        
        message += "🔥 <b>热号 Top 10：</b>\n"
        for idx, (num, count) in enumerate(analysis['hot'], 1):
            zodiac = NUMBER_TO_ZODIAC.get(num, '未知')
            zodiac_emoji = ZODIAC_EMOJI.get(zodiac, '')
            message += f"{idx}. <b>{num:02d}</b> {zodiac_emoji}{zodiac} - {count}次\n"
        
        message += "\n❄️ <b>冷号 Top 10：</b>\n"
        for idx, (num, count) in enumerate(analysis['cold'], 1):
            zodiac = NUMBER_TO_ZODIAC.get(num, '未知')
            zodiac_emoji = ZODIAC_EMOJI.get(zodiac, '')
            message += f"{idx}. <b>{num:02d}</b> {zodiac_emoji}{zodiac} - {count}次\n"
        
        keyboard = [[InlineKeyboardButton("🔙 返回分析菜单", callback_data="menu_analysis")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='HTML')
    
    async def show_history_menu(self, query):
        """Show history menu"""
        message = """
📜 <b>历史记录菜单</b>

查询历史开奖结果：

选择查询范围：
"""
        
        keyboard = [
            [
                InlineKeyboardButton("最近10期", callback_data="history_10"),
                InlineKeyboardButton("最近20期", callback_data="history_20"),
            ],
            [
                InlineKeyboardButton("最近30期", callback_data="history_30"),
                InlineKeyboardButton("最近50期", callback_data="history_50"),
            ],
            [InlineKeyboardButton("🔙 返回主菜单", callback_data="back_to_main")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='HTML')
    
    async def show_history(self, query, limit: int):
        """Show lottery history"""
        history = self.db.get_history(limit)
        
        if not history:
            await query.edit_message_text("暂无历史数据")
            return
        
        message = f"📜 <b>历史记录（最近{limit}期）</b>\n\n"
        
        for h in history[:10]:  # Show max 10 in one message
            codes = ' '.join([f"{x:02d}" for x in h['open_code'][:6]])
            zodiac_emoji = ZODIAC_EMOJI.get(h['tema_zodiac'], '')
            message += f"<b>期号：</b>{h['expect']}\n"
            message += f"<b>号码：</b><code>{codes}</code>\n"
            message += f"<b>特码：</b><code>{h['tema']:02d}</code> {zodiac_emoji}{h['tema_zodiac']}\n"
            message += f"<b>时间：</b>{h['open_time']}\n"
            message += "─" * 30 + "\n"
        
        if len(history) > 10:
            message += f"\n<i>仅显示前10期，共{len(history)}期</i>"
        
        keyboard = [[InlineKeyboardButton("🔙 返回历史菜单", callback_data="menu_history")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='HTML')
    
    async def show_settings_menu(self, query):
        """Show settings menu"""
        user_id = query.from_user.id
        settings = self.db.get_user_settings(user_id)
        
        notify_status = "✅ 已开启" if settings['notify_enabled'] else "❌ 已关闭"
        reminder_status = "✅ 已开启" if settings['reminder_enabled'] else "❌ 已关闭"
        auto_predict_status = "✅ 已开启" if settings['auto_predict'] else "❌ 已关闭"
        
        message = f"""
⚙️ <b>个人设置</b>

当前设置状态：

🔔 <b>开奖通知：</b>{notify_status}
⏰ <b>开奖提醒：</b>{reminder_status}
🤖 <b>自动预测：</b>{auto_predict_status}

点击下方按钮切换设置：
"""
        
        keyboard = [
            [InlineKeyboardButton(
                f"🔔 开奖通知 {notify_status}",
                callback_data="setting_notify"
            )],
            [InlineKeyboardButton(
                f"⏰ 开奖提醒 (21:00) {reminder_status}",
                callback_data="setting_reminder"
            )],
            [InlineKeyboardButton(
                f"🤖 自动预测 {auto_predict_status}",
                callback_data="setting_auto_predict"
            )],
            [InlineKeyboardButton("🔙 返回主菜单", callback_data="back_to_main")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='HTML')
    
    async def toggle_setting(self, query, data: str):
        """Toggle user setting"""
        user_id = query.from_user.id
        setting_map = {
            'setting_notify': 'notify_enabled',
            'setting_reminder': 'reminder_enabled',
            'setting_auto_predict': 'auto_predict'
        }
        
        setting = setting_map.get(data)
        if setting:
            current = self.db.get_user_settings(user_id)
            new_value = 0 if current[setting] else 1
            self.db.update_user_setting(user_id, setting, new_value)
        
        # Refresh settings menu
        await self.show_settings_menu(query)
    
    async def show_latest_result(self, query):
        """Show latest lottery result"""
        result = self.db.get_latest_result()
        
        if not result:
            await query.edit_message_text("暂无开奖数据")
            return
        
        codes = ' '.join([f"{x:02d}" for x in result['open_code'][:6]])
        zodiac_emoji = ZODIAC_EMOJI.get(result['tema_zodiac'], '')
        
        message = f"""
📊 <b>最新开奖结果</b>

<b>期号：</b>{result['expect']}
<b>开奖时间：</b>{result['open_time']}

<b>号码：</b><code>{codes}</code>
<b>特码：</b><code>{result['tema']:02d}</code> 🎯

<b>生肖：</b>{zodiac_emoji}{result['tema_zodiac']}

─────────────────
"""
        
        countdown = self.get_countdown()
        message += f"\n⏰ 下期开奖倒计时：<code>{countdown}</code>"
        
        keyboard = [
            [InlineKeyboardButton("🎯 预测下期", callback_data="menu_predict")],
            [InlineKeyboardButton("🔙 返回主菜单", callback_data="back_to_main")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='HTML')
    
    async def show_help(self, query):
        """Show help message"""
        message = """
❓ <b>帮助信息</b>

<b>📌 功能说明：</b>

<b>🎯 智能预测</b>
• AI综合预测：多因素分析
• 生肖预测：基于生肖周期
• 冷热号预测：统计分析

<b>📊 最新开奖</b>
• 查看最新期开奖结果
• 显示特码和生肖

<b>📈 数据分析</b>
• 频率分析：号码出现统计
• 生肖分布：生肖比例分析
• 遗漏分析：未出号码追踪
• 冷热分析：冷热号对比

<b>📜 历史记录</b>
• 查询历史开奖数据
• 支持多种查询范围

<b>⚙️ 个人设置</b>
• 开奖通知：自动推送结果
• 开奖提醒：21:00提醒
• 自动预测：开奖后自动预测

<b>⏰ 开奖时间：</b>
每晚 21:32:32 (北京时间)

<b>⚠️ 注意事项：</b>
• 预测仅供参考
• 请理性对待
• 谨慎决策

如有问题，请联系管理员。
"""
        
        keyboard = [[InlineKeyboardButton("🔙 返回主菜单", callback_data="back_to_main")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='HTML')
    
    async def back_to_main(self, query):
        """Back to main menu"""
        user = query.from_user
        countdown = self.get_countdown()
        
        message = f"""
🎰 <b>澳门六合彩预测机器人</b> 🎰

👋 欢迎，{user.first_name}！

📅 今日开奖倒计时：<code>{countdown}</code>
⏰ 开奖时间：每晚 {LOTTERY_TIME}

✨ <b>功能导航</b> ✨
• 🎯 智能预测 - AI预测特码TOP5
• 📊 最新开奖 - 查看最新结果
• 📈 数据分析 - 频率/生肖/冷热分析
• 📜 历史记录 - 查询历史开奖
• ⚙️ 个人设置 - 通知提醒设置

请选择功能：
"""
        
        keyboard = [
            [
                InlineKeyboardButton("🎯 智能预测", callback_data="menu_predict"),
                InlineKeyboardButton("📊 最新开奖", callback_data="latest_result"),
            ],
            [
                InlineKeyboardButton("📈 数据分析", callback_data="menu_analysis"),
                InlineKeyboardButton("📜 历史记录", callback_data="menu_history"),
            ],
            [
                InlineKeyboardButton("⚙️ 个人设置", callback_data="menu_settings"),
                InlineKeyboardButton("❓ 帮助", callback_data="help"),
            ],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='HTML')
    
    async def check_new_result(self, context: ContextTypes.DEFAULT_TYPE):
        """Check for new lottery result"""
        try:
            result = self.api.get_latest_result()
            
            if not result:
                logger.warning("No result from API")
                return
            
            expect = result['expect']
            
            # Check if this is a new result
            if self.last_expect and expect == self.last_expect:
                return
            
            # Check if already in database
            existing = self.db.get_latest_result()
            if existing and existing['expect'] == expect:
                self.last_expect = expect
                return
            
            # New result found!
            logger.info(f"New result found: {expect}")
            
            # Save to database
            self.db.save_lottery_result(
                expect,
                result['open_code'],
                result['tema'],
                result['tema_zodiac'],
                result['open_time']
            )
            
            self.last_expect = expect
            
            # Notify all users with notifications enabled
            await self.notify_users(result, context)
            
        except Exception as e:
            logger.error(f"Error checking new result: {e}")
    
    async def notify_users(self, result: Dict, context: ContextTypes.DEFAULT_TYPE):
        """Notify users about new result"""
        users = self.db.get_all_notify_users()
        
        codes = ' '.join([f"{x:02d}" for x in result['open_code'][:6]])
        zodiac_emoji = ZODIAC_EMOJI.get(result['tema_zodiac'], '')
        
        message = f"""
🎉 <b>开奖通知</b> 🎉

<b>期号：</b>{result['expect']}
<b>开奖时间：</b>{result['open_time']}

<b>号码：</b><code>{codes}</code>
<b>特码：</b><code>{result['tema']:02d}</code> 🎯

<b>生肖：</b>{zodiac_emoji}{result['tema_zodiac']}

恭喜中奖的朋友！ 🎊
"""
        
        keyboard = [[InlineKeyboardButton("🎯 预测下期", callback_data="menu_predict")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        for user_id in users:
            try:
                await context.bot.send_message(
                    chat_id=user_id,
                    text=message,
                    reply_markup=reply_markup,
                    parse_mode='HTML'
                )
                logger.info(f"Notified user {user_id}")
            except Exception as e:
                logger.error(f"Error notifying user {user_id}: {e}")
    
    async def send_reminder(self, context: ContextTypes.DEFAULT_TYPE):
        """Send reminder before lottery"""
        users = self.db.get_all_reminder_users()
        
        countdown = self.get_countdown()
        
        message = f"""
⏰ <b>开奖提醒</b>

距离今晚开奖还有：<code>{countdown}</code>

开奖时间：{LOTTERY_TIME}

🎯 点击下方预测今晚特码
"""
        
        keyboard = [[InlineKeyboardButton("🎯 立即预测", callback_data="menu_predict")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        for user_id in users:
            try:
                await context.bot.send_message(
                    chat_id=user_id,
                    text=message,
                    reply_markup=reply_markup,
                    parse_mode='HTML'
                )
                logger.info(f"Sent reminder to user {user_id}")
            except Exception as e:
                logger.error(f"Error sending reminder to user {user_id}: {e}")
    
    def setup_scheduler(self, application: Application):
        """Setup scheduled jobs"""
        scheduler = AsyncIOScheduler(timezone=self.tz)
        
        # Check for new results
        # Smart interval: 1 min during draw time, 5 min otherwise
        scheduler.add_job(
            self.smart_check,
            IntervalTrigger(minutes=1),
            args=[application],
            id='smart_check'
        )
        
        # Daily reminder at 21:00
        scheduler.add_job(
            self.send_reminder,
            CronTrigger(hour=21, minute=0, second=0, timezone=self.tz),
            args=[application],
            id='daily_reminder'
        )
        
        scheduler.start()
        logger.info("Scheduler started")
        
        return scheduler
    
    async def smart_check(self, application: Application):
        """Smart check based on time"""
        now = datetime.now(self.tz)
        hour = now.hour
        minute = now.minute
        
        # During draw time (21:30-21:40), check more frequently
        if hour == 21 and 30 <= minute <= 40:
            await self.check_new_result(application)
        # Otherwise, check every 5 minutes
        elif minute % 5 == 0:
            await self.check_new_result(application)
    
    def run(self):
        """Run the bot"""
        if not TELEGRAM_BOT_TOKEN:
            logger.error("TELEGRAM_BOT_TOKEN not found in environment variables")
            sys.exit(1)
        
        # Check if database is empty and sync history data
        if self.db.is_database_empty():
            logger.info("Database is empty, starting history sync...")
            sync_history_data(self.db)
        else:
            logger.info("Database already has data, skipping history sync")
        
        # Create application
        application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
        
        # Add handlers
        application.add_handler(CommandHandler("start", self.start_command))
        application.add_handler(CallbackQueryHandler(self.button_handler))
        
        # Setup scheduler
        scheduler = self.setup_scheduler(application)
        
        # Initialize last_expect
        latest = self.db.get_latest_result()
        if latest:
            self.last_expect = latest['expect']
        
        logger.info("Bot started successfully")
        
        # Run bot
        try:
            application.run_polling(allowed_updates=Update.ALL_TYPES)
        except KeyboardInterrupt:
            logger.info("Bot stopped by user")
        finally:
            scheduler.shutdown()


def main():
    """Main entry point"""
    bot = LotteryBot()
    bot.run()


if __name__ == "__main__":
    main()
