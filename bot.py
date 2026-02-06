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
    '鼠': [06, 18, 30, 42],
    '牛': [05, 17, 29, 41],
    '虎': [04, 16, 28, 40],
    '兔': [03, 15, 27, 39],
    '龙': [02, 14, 26, 38],
    '蛇': [01, 13, 25, 37, 49],
    '马': [12, 24, 36, 48],
    '羊': [11, 23, 35, 47],
    '猴': [10, 22, 34, 46],
    '鸡': [09, 21, 33, 45],
    '狗': [08, 20, 32, 44],
    '猪': [07, 19, 31, 43]
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
                auto_predict_reminder INTEGER DEFAULT 1,
                auto_predict INTEGER DEFAULT 0,
                default_period INTEGER DEFAULT 50,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Prediction history table (legacy - kept for backward compatibility)
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
        
        # Prediction records table (new enhanced version)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS prediction_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                expect TEXT UNIQUE NOT NULL,
                predict_zodiac1 TEXT NOT NULL,
                predict_zodiac2 TEXT NOT NULL,
                predict_numbers1 TEXT NOT NULL,
                predict_numbers2 TEXT NOT NULL,
                predict_score1 REAL NOT NULL,
                predict_score2 REAL NOT NULL,
                predict_time DATETIME NOT NULL,
                actual_tema INTEGER,
                actual_zodiac TEXT,
                is_hit INTEGER DEFAULT 0,
                hit_rank INTEGER,
                analysis_data TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Create indices for prediction_records
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_pred_expect ON prediction_records(expect)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_pred_is_hit ON prediction_records(is_hit)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_pred_time ON prediction_records(predict_time DESC)')
        
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
            'auto_predict_reminder': 'auto_predict_reminder',
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
    
    def can_predict(self, expect: str) -> bool:
        """Check if prediction is allowed for this period"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT id FROM prediction_records WHERE expect = ?', (expect,))
        result = cursor.fetchone()
        conn.close()
        return result is None
    
    def save_zodiac_prediction(self, expect: str, zodiac1: str, zodiac2: str, 
                               numbers1: List[int], numbers2: List[int],
                               score1: float, score2: float, analysis_data: Dict) -> bool:
        """Save zodiac prediction to database"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                INSERT INTO prediction_records 
                (expect, predict_zodiac1, predict_zodiac2, predict_numbers1, predict_numbers2,
                 predict_score1, predict_score2, predict_time, analysis_data)
                VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'), ?)
            ''', (expect, zodiac1, zodiac2, 
                  ','.join(map(str, numbers1)), ','.join(map(str, numbers2)),
                  score1, score2, json.dumps(analysis_data, ensure_ascii=False)))
            conn.commit()
            logger.info(f"Saved zodiac prediction for {expect}: {zodiac1}, {zodiac2}")
            return True
        except Exception as e:
            logger.error(f"Error saving zodiac prediction: {e}")
            return False
        finally:
            conn.close()
    
    def get_prediction_record(self, expect: str) -> Optional[Dict]:
        """Get prediction record for a specific period"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM prediction_records WHERE expect = ?', (expect,))
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return {
                'id': row['id'],
                'expect': row['expect'],
                'predict_zodiac1': row['predict_zodiac1'],
                'predict_zodiac2': row['predict_zodiac2'],
                'predict_numbers1': row['predict_numbers1'],
                'predict_numbers2': row['predict_numbers2'],
                'predict_score1': row['predict_score1'],
                'predict_score2': row['predict_score2'],
                'predict_time': row['predict_time'],
                'actual_tema': row['actual_tema'],
                'actual_zodiac': row['actual_zodiac'],
                'is_hit': row['is_hit'],
                'hit_rank': row['hit_rank'],
                'analysis_data': json.loads(row['analysis_data']) if row['analysis_data'] else None
            }
        return None
    
    def update_prediction_result(self, expect: str, actual_tema: int, actual_zodiac: str):
        """Update prediction record with actual result"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        # Get prediction
        cursor.execute('SELECT predict_zodiac1, predict_zodiac2 FROM prediction_records WHERE expect = ?', (expect,))
        record = cursor.fetchone()
        
        if record:
            predict1, predict2 = record['predict_zodiac1'], record['predict_zodiac2']
            
            # Determine hit status
            if actual_zodiac == predict1:
                is_hit, hit_rank = 1, 1
            elif actual_zodiac == predict2:
                is_hit, hit_rank = 1, 2
            else:
                is_hit, hit_rank = 2, 0
            
            # Update record
            cursor.execute('''
                UPDATE prediction_records 
                SET actual_tema = ?, actual_zodiac = ?, is_hit = ?, hit_rank = ?
                WHERE expect = ?
            ''', (actual_tema, actual_zodiac, is_hit, hit_rank, expect))
            conn.commit()
            logger.info(f"Updated prediction result for {expect}: {'HIT' if is_hit == 1 else 'MISS'}")
        
        conn.close()
    
    def get_prediction_history(self, limit: int = 10) -> List[Dict]:
        """Get prediction history"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT * FROM prediction_records 
            WHERE is_hit > 0
            ORDER BY expect DESC 
            LIMIT ?
        ''', (limit,))
        rows = cursor.fetchall()
        conn.close()
        
        results = []
        for row in rows:
            results.append({
                'expect': row['expect'],
                'predict_zodiac1': row['predict_zodiac1'],
                'predict_zodiac2': row['predict_zodiac2'],
                'actual_zodiac': row['actual_zodiac'],
                'is_hit': row['is_hit'],
                'hit_rank': row['hit_rank']
            })
        return results
    
    def calculate_hit_rate(self) -> Dict:
        """Calculate prediction hit rate statistics"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        # Total predictions (with results)
        cursor.execute('SELECT COUNT(*) as total FROM prediction_records WHERE is_hit > 0')
        total = cursor.fetchone()['total']
        
        # Hit count
        cursor.execute('SELECT COUNT(*) as hits FROM prediction_records WHERE is_hit = 1')
        hits = cursor.fetchone()['hits']
        
        # Recent 10 periods
        cursor.execute('''
            SELECT COUNT(*) as recent_hits 
            FROM (SELECT * FROM prediction_records WHERE is_hit > 0 ORDER BY expect DESC LIMIT 10)
            WHERE is_hit = 1
        ''')
        recent_10_hits = cursor.fetchone()['recent_hits']
        
        cursor.execute('SELECT COUNT(*) as recent_total FROM (SELECT * FROM prediction_records WHERE is_hit > 0 ORDER BY expect DESC LIMIT 10)')
        recent_10_total = cursor.fetchone()['recent_total']
        
        # Recent 5 periods
        cursor.execute('''
            SELECT COUNT(*) as recent_hits 
            FROM (SELECT * FROM prediction_records WHERE is_hit > 0 ORDER BY expect DESC LIMIT 5)
            WHERE is_hit = 1
        ''')
        recent_5_hits = cursor.fetchone()['recent_hits']
        
        cursor.execute('SELECT COUNT(*) as recent_total FROM (SELECT * FROM prediction_records WHERE is_hit > 0 ORDER BY expect DESC LIMIT 5)')
        recent_5_total = cursor.fetchone()['recent_total']
        
        conn.close()
        
        return {
            'total': total,
            'hits': hits,
            'hit_rate': (hits / total * 100) if total > 0 else 0,
            'recent_10_hits': recent_10_hits,
            'recent_10_total': recent_10_total,
            'recent_10_rate': (recent_10_hits / recent_10_total * 100) if recent_10_total > 0 else 0,
            'recent_5_hits': recent_5_hits,
            'recent_5_total': recent_5_total,
            'recent_5_rate': (recent_5_hits / recent_5_total * 100) if recent_5_total > 0 else 0
        }


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
    
    def predict_top2_zodiac(self, period: int = 100) -> Dict:
        """
        Predict TOP 2 most likely zodiacs based on multi-dimensional analysis
        
        Analysis dimensions:
        1. Frequency analysis (30% weight) - Recent appearance count
        2. Missing analysis (30% weight) - Periods since last appearance
        3. Cycle analysis (20% weight) - Deviation from expected frequency
        4. Trend analysis (20% weight) - Recent 10 period trend
        
        Returns: TOP 2 zodiacs with detailed analysis data
        """
        history = self.db.get_history(period)
        
        if not history:
            # Random selection if no history
            all_zodiacs = list(ZODIAC_NUMBERS.keys())
            selected = random.sample(all_zodiacs, 2)
            return {
                'zodiac1': selected[0],
                'zodiac2': selected[1],
                'numbers1': ZODIAC_NUMBERS[selected[0]],
                'numbers2': ZODIAC_NUMBERS[selected[1]],
                'score1': 50.0,
                'score2': 45.0,
                'analysis': {}
            }
        
        # Build zodiac scores
        zodiac_scores = {}
        all_zodiacs = list(ZODIAC_NUMBERS.keys())
        
        for zodiac in all_zodiacs:
            freq_score = self._calculate_frequency_score(history, zodiac, period)
            missing_score = self._calculate_missing_score(history, zodiac)
            cycle_score = self._calculate_cycle_score(history, zodiac, period)
            trend_score = self._calculate_trend_score(history, zodiac)
            
            final_score = (
                freq_score * 0.30 +
                missing_score * 0.30 +
                cycle_score * 0.20 +
                trend_score * 0.20
            )
            
            zodiac_scores[zodiac] = {
                'score': final_score,
                'freq': freq_score,
                'missing': missing_score,
                'cycle': cycle_score,
                'trend': trend_score
            }
        
        # Get TOP 2
        sorted_zodiacs = sorted(zodiac_scores.items(), key=lambda x: x[1]['score'], reverse=True)
        top2 = sorted_zodiacs[:2]
        
        zodiac1, analysis1 = top2[0]
        zodiac2, analysis2 = top2[1]
        
        return {
            'zodiac1': zodiac1,
            'zodiac2': zodiac2,
            'numbers1': ZODIAC_NUMBERS[zodiac1],
            'numbers2': ZODIAC_NUMBERS[zodiac2],
            'score1': analysis1['score'],
            'score2': analysis2['score'],
            'analysis': {
                zodiac1: analysis1,
                zodiac2: analysis2,
                'all_scores': zodiac_scores
            }
        }
    
    def _calculate_frequency_score(self, history: List[Dict], zodiac: str, period: int) -> float:
        """Calculate frequency score for a zodiac (lower frequency = higher score)"""
        zodiac_list = [h['tema_zodiac'] for h in history]
        count = zodiac_list.count(zodiac)
        expected = period / 12  # Expected frequency for 12 zodiacs
        
        # Score inversely proportional to frequency
        if count == 0:
            return 100.0
        else:
            deviation = expected - count
            return min(100.0, max(0.0, 50.0 + deviation * 5))
    
    def _calculate_missing_score(self, history: List[Dict], zodiac: str) -> float:
        """Calculate missing score (longer missing = higher score)"""
        zodiac_list = [h['tema_zodiac'] for h in history]
        
        # Find last appearance
        try:
            last_idx = zodiac_list.index(zodiac)
            missing_periods = last_idx
        except ValueError:
            # Not found in history
            missing_periods = len(zodiac_list)
        
        # Score based on missing periods
        return min(100.0, missing_periods * 2)
    
    def _calculate_cycle_score(self, history: List[Dict], zodiac: str, period: int) -> float:
        """Calculate cycle score based on theoretical expectation"""
        zodiac_list = [h['tema_zodiac'] for h in history]
        count = zodiac_list.count(zodiac)
        expected = period / 12
        
        # Favor zodiacs below expected frequency
        if count < expected:
            return min(100.0, (expected - count) / expected * 100)
        else:
            return max(0.0, 50.0 - (count - expected) * 5)
    
    def _calculate_trend_score(self, history: List[Dict], zodiac: str) -> float:
        """Calculate trend score based on recent 10 periods"""
        recent_10 = [h['tema_zodiac'] for h in history[:10]]
        recent_count = recent_10.count(zodiac)
        
        # Favor zodiacs not appearing in recent 10
        if recent_count == 0:
            return 100.0
        else:
            return max(0.0, 100.0 - recent_count * 20)
    
    def get_zodiac_analysis_details(self, history: List[Dict], zodiac: str) -> Dict:
        """Get detailed analysis for a zodiac"""
        tema_list = [h['tema'] for h in history]
        zodiac_list = [h['tema_zodiac'] for h in history]
        
        # Count appearances
        count = zodiac_list.count(zodiac)
        
        # Find missing periods
        try:
            last_idx = zodiac_list.index(zodiac)
            current_missing = last_idx
        except ValueError:
            current_missing = len(zodiac_list)
        
        # Find all missing periods
        missing_periods = []
        for i, z in enumerate(zodiac_list):
            if z == zodiac:
                missing_periods.append(i)
        
        max_missing = max(missing_periods) if missing_periods else len(zodiac_list)
        avg_missing = sum(missing_periods) / len(missing_periods) if missing_periods else len(zodiac_list)
        
        return {
            'count': count,
            'current_missing': current_missing,
            'max_missing': max_missing,
            'avg_missing': avg_missing,
            'percentage': (count / len(zodiac_list) * 100) if zodiac_list else 0
        }
    
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
        elif data == "ai_zodiac_predict":
            await self.show_ai_zodiac_predict(query)
        elif data == "do_zodiac_prediction":
            await self.perform_zodiac_prediction(query)
        elif data == "prediction_history":
            await self.show_prediction_history(query)
        
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
        # Get next period number
        latest = self.db.get_latest_result()
        if latest:
            next_expect = str(int(latest['expect']) + 1)
        else:
            next_expect = "未知"
        
        countdown = self.get_countdown()
        
        # Check if prediction exists for next period
        can_predict = self.db.can_predict(next_expect) if latest else False
        prediction_status = "未预测" if can_predict else "✅ 已预测（已锁定）"
        
        message = f"""
🎯 <b>智能预测菜单</b>

━━━━━━━━━━━━━━━━━━━━━
📅 下期期号：{next_expect}
⏰ 开奖倒计时：{countdown}

━━━━━━━━━━━━━━━━━━━━━
🔮 <b>AI 生肖预测（TOP 2）</b> ⭐ 推荐

基于多维度分析预测最可能的2个生肖
• 频率分析 (30%)
• 遗漏分析 (30%)
• 周期分析 (20%)
• 趋势分析 (20%)

📊 预测状态：{prediction_status}

━━━━━━━━━━━━━━━━━━━━━
<b>其他预测方式</b>

• <b>AI综合预测</b> - 多因素综合分析（TOP 5）
• <b>生肖预测</b> - 基于生肖周期
• <b>热号预测</b> - 近期高频号码
• <b>冷号预测</b> - 长期未出号码

⚠️ 预测仅供参考，不保证准确性
"""
        
        keyboard = [
            [InlineKeyboardButton("🔮 AI 生肖预测（TOP 2）⭐", callback_data="ai_zodiac_predict")],
            [InlineKeyboardButton("🤖 AI综合预测", callback_data="predict_comprehensive")],
            [InlineKeyboardButton("🐲 生肖预测", callback_data="predict_zodiac")],
            [
                InlineKeyboardButton("🔥 热号预测", callback_data="predict_hot"),
                InlineKeyboardButton("❄️ 冷号预测", callback_data="predict_cold"),
            ],
            [InlineKeyboardButton("📊 预测历史", callback_data="prediction_history")],
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
    
    async def show_ai_zodiac_predict(self, query):
        """Show AI zodiac prediction interface"""
        # Get next period
        latest = self.db.get_latest_result()
        if not latest:
            await query.edit_message_text(
                "❌ 暂无历史数据，请稍后再试",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data="menu_predict")]])
            )
            return
        
        next_expect = str(int(latest['expect']) + 1)
        
        # Check if already predicted
        if not self.db.can_predict(next_expect):
            # Show existing prediction
            await self.show_existing_zodiac_prediction(query, next_expect)
            return
        
        # Show prediction prompt
        countdown = self.get_countdown()
        
        message = f"""
🔮 <b>AI 生肖预测（TOP 2）</b>

━━━━━━━━━━━━━━━━━━━━━
📅 预测期号：{next_expect}
⏰ 开奖倒计时：{countdown}

━━━━━━━━━━━━━━━━━━━━━
📊 预测状态：<b>未预测</b>

💡 <b>提示：</b>
• 每期仅可预测一次
• 预测后自动锁定，不可修改
• 开奖后自动对比结果
• 结果将记录到历史

━━━━━━━━━━━━━━━━━━━━━
🤖 <b>AI 分析维度：</b>

✅ 生肖频率分析（30%权重）
✅ 生肖遗漏分析（30%权重）
✅ 生肖周期分析（20%权重）
✅ 生肖趋势分析（20%权重）

分析期数：最近100期历史数据

━━━━━━━━━━━━━━━━━━━━━
"""
        
        keyboard = [
            [InlineKeyboardButton("🎲 开始预测", callback_data="do_zodiac_prediction")],
            [InlineKeyboardButton("📈 查看历史命中率", callback_data="prediction_history")],
            [InlineKeyboardButton("🔙 返回", callback_data="menu_predict")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='HTML')
    
    async def perform_zodiac_prediction(self, query):
        """Perform zodiac prediction with animation"""
        # Get next period
        latest = self.db.get_latest_result()
        if not latest:
            await query.answer("❌ 暂无历史数据", show_alert=True)
            return
        
        next_expect = str(int(latest['expect']) + 1)
        
        # Check if already predicted
        if not self.db.can_predict(next_expect):
            await query.answer("⚠️ 本期已预测，不可重复预测", show_alert=True)
            await self.show_existing_zodiac_prediction(query, next_expect)
            return
        
        # Show progress animation
        progress_msg = """
⏳ <b>AI 正在分析历史数据...</b>

✅ 加载最近100期历史数据...
"""
        await query.edit_message_text(progress_msg, parse_mode='HTML')
        await asyncio.sleep(0.5)
        
        progress_msg += "✅ 分析49个号码出现频率...\n"
        await query.edit_message_text(progress_msg, parse_mode='HTML')
        await asyncio.sleep(0.5)
        
        progress_msg += "✅ 计算12生肖遗漏值...\n"
        await query.edit_message_text(progress_msg, parse_mode='HTML')
        await asyncio.sleep(0.5)
        
        progress_msg += "✅ 分析生肖周期规律...\n"
        await query.edit_message_text(progress_msg, parse_mode='HTML')
        await asyncio.sleep(0.5)
        
        progress_msg += "✅ 统计冷热号走势...\n"
        await query.edit_message_text(progress_msg, parse_mode='HTML')
        await asyncio.sleep(0.5)
        
        progress_msg += "✅ 综合评分排序...\n\n🤖 AI 预测生成完成！"
        await query.edit_message_text(progress_msg, parse_mode='HTML')
        await asyncio.sleep(1)
        
        # Perform prediction
        prediction = self.predictor.predict_top2_zodiac(100)
        
        # Save to database
        self.db.save_zodiac_prediction(
            expect=next_expect,
            zodiac1=prediction['zodiac1'],
            zodiac2=prediction['zodiac2'],
            numbers1=prediction['numbers1'],
            numbers2=prediction['numbers2'],
            score1=prediction['score1'],
            score2=prediction['score2'],
            analysis_data=prediction['analysis']
        )
        
        # Show prediction result
        await self.display_zodiac_prediction(query, next_expect, prediction)
    
    async def display_zodiac_prediction(self, query, expect: str, prediction: Dict):
        """Display zodiac prediction result"""
        countdown = self.get_countdown()
        
        zodiac1 = prediction['zodiac1']
        zodiac2 = prediction['zodiac2']
        emoji1 = ZODIAC_EMOJI.get(zodiac1, '')
        emoji2 = ZODIAC_EMOJI.get(zodiac2, '')
        
        numbers1_str = ', '.join(f"{n:02d}" for n in prediction['numbers1'])
        numbers2_str = ', '.join(f"{n:02d}" for n in prediction['numbers2'])
        
        score1 = prediction['score1']
        score2 = prediction['score2']
        
        # Get detailed analysis
        history = self.db.get_history(100)
        details1 = self.predictor.get_zodiac_analysis_details(history, zodiac1)
        details2 = self.predictor.get_zodiac_analysis_details(history, zodiac2)
        
        # Stars for score
        stars1 = "⭐" * min(5, int(score1 / 20))
        stars2 = "⭐" * min(5, int(score2 / 20))
        
        # Get hit rate
        hit_stats = self.db.calculate_hit_rate()
        
        message = f"""
🔮 <b>AI 生肖预测（{expect}期）</b>

━━━━━━━━━━━━━━━━━━━━━
⏰ 预测时间：{datetime.now(self.tz).strftime('%Y-%m-%d %H:%M:%S')}
📊 开奖倒计时：{countdown}
📈 分析期数：100期

━━━━━━━━━━━━━━━━━━━━━
🥇 <b>推荐生肖一：{emoji1} {zodiac1}</b>

📊 综合评分：{score1:.1f}/100 {stars1}

🔍 <b>分析依据：</b>
✅ 出现次数：{details1['count']}次/100期
✅ 当前遗漏：{details1['current_missing']}期
✅ 最大遗漏：{details1['max_missing']}期
✅ 平均遗漏：{details1['avg_missing']:.1f}期
✅ 出现频率：{details1['percentage']:.1f}%

🎯 <b>对应号码：</b>{numbers1_str}

━━━━━━━━━━━━━━━━━━━━━
🥈 <b>推荐生肖二：{emoji2} {zodiac2}</b>

📊 综合评分：{score2:.1f}/100 {stars2}

🔍 <b>分析依据：</b>
✅ 出现次数：{details2['count']}次/100期
✅ 当前遗漏：{details2['current_missing']}期
✅ 最大遗漏：{details2['max_missing']}期
✅ 平均遗漏：{details2['avg_missing']:.1f}期
✅ 出现频率：{details2['percentage']:.1f}%

🎯 <b>对应号码：</b>{numbers2_str}

━━━━━━━━━━━━━━━━━━━━━
"""
        
        if hit_stats['total'] > 0:
            message += f"""
📊 <b>历史命中率统计</b>

总预测次数：{hit_stats['total']}期
命中次数：{hit_stats['hits']}期
总命中率：{hit_stats['hit_rate']:.1f}% 📈

"""
            if hit_stats['recent_10_total'] > 0:
                message += f"近10期表现：{hit_stats['recent_10_hits']}/{hit_stats['recent_10_total']} = {hit_stats['recent_10_rate']:.1f}%\n"
            if hit_stats['recent_5_total'] > 0:
                message += f"近5期表现：{hit_stats['recent_5_hits']}/{hit_stats['recent_5_total']} = {hit_stats['recent_5_rate']:.1f}%\n"
            message += "\n"
        
        message += """
━━━━━━━━━━━━━━━━━━━━━
⚠️ <b>重要提示</b>

✅ 本期预测已锁定，无法修改
✅ 开奖后将自动对比结果
✅ 结果将记录到预测历史

💡 <i>预测仅供参考，请理性对待</i>
"""
        
        keyboard = [
            [InlineKeyboardButton("📊 查看预测历史", callback_data="prediction_history")],
            [InlineKeyboardButton("🔙 返回", callback_data="menu_predict")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='HTML')
    
    async def show_existing_zodiac_prediction(self, query, expect: str):
        """Show existing prediction for a period"""
        record = self.db.get_prediction_record(expect)
        
        if not record:
            await query.edit_message_text(
                "❌ 未找到预测记录",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data="menu_predict")]])
            )
            return
        
        countdown = self.get_countdown()
        
        zodiac1 = record['predict_zodiac1']
        zodiac2 = record['predict_zodiac2']
        emoji1 = ZODIAC_EMOJI.get(zodiac1, '')
        emoji2 = ZODIAC_EMOJI.get(zodiac2, '')
        
        message = f"""
🔮 <b>AI 生肖预测（{expect}期）</b>

━━━━━━━━━━━━━━━━━━━━━
⏰ 开奖倒计时：{countdown}

📊 本期预测状态：<b>✅ 已预测（已锁定）</b>

━━━━━━━━━━━━━━━━━━━━━
🎯 <b>本期预测结果</b>

🥇 推荐生肖一：{emoji1} {zodiac1} ({record['predict_numbers1']})
🥈 推荐生肖二：{emoji2} {zodiac2} ({record['predict_numbers2']})

━━━━━━━━━━━━━━━━━━━━━
📅 预测时间：{record['predict_time']}
⏰ 开奖时间：预计 21:32:32

💡 提示：开奖后将自动对比预测结果
"""
        
        # If already drawn, show comparison
        if record['is_hit'] > 0:
            actual_zodiac = record['actual_zodiac']
            actual_emoji = ZODIAC_EMOJI.get(actual_zodiac, '')
            
            message += f"""

━━━━━━━━━━━━━━━━━━━━━
🎰 <b>开奖结果对比</b>

实际开出：<b>{record['actual_tema']:02d}</b> {actual_emoji}{actual_zodiac}

"""
            if record['is_hit'] == 1:
                if record['hit_rank'] == 1:
                    message += f"🎉 <b>恭喜！TOP1 生肖预测命中！</b> ✅\n\n"
                    message += f"预测生肖一：{emoji1} {zodiac1} ✅ 命中！\n"
                    message += f"预测生肖二：{emoji2} {zodiac2}\n"
                else:
                    message += f"🎊 <b>TOP2 生肖预测命中！</b> ✅\n\n"
                    message += f"预测生肖一：{emoji1} {zodiac1}\n"
                    message += f"预测生肖二：{emoji2} {zodiac2} ✅ 命中！\n"
            else:
                message += f"💔 <b>很遗憾，本期预测未中</b>\n\n"
                message += f"预测生肖一：{emoji1} {zodiac1} ❌\n"
                message += f"预测生肖二：{emoji2} {zodiac2} ❌\n"
        
        message += """

━━━━━━━━━━━━━━━━━━━━━
"""
        
        keyboard = [
            [InlineKeyboardButton("📊 查看预测历史", callback_data="prediction_history")],
            [InlineKeyboardButton("🔙 返回", callback_data="menu_predict")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='HTML')
    
    async def show_prediction_history(self, query):
        """Show prediction history with hit rate"""
        records = self.db.get_prediction_history(10)
        hit_stats = self.db.calculate_hit_rate()
        
        if not records:
            message = """
📊 <b>预测历史记录</b>

━━━━━━━━━━━━━━━━━━━━━
暂无预测历史记录

请先进行预测后查看
"""
        else:
            message = f"""
📊 <b>预测历史记录</b>

━━━━━━━━━━━━━━━━━━━━━
📈 <b>总体统计</b>

总预测次数：{hit_stats['total']}期
命中次数：{hit_stats['hits']}期
总命中率：{hit_stats['hit_rate']:.1f}% 📈

"""
            
            if hit_stats['recent_10_total'] > 0:
                message += f"\n近10期表现：{hit_stats['recent_10_hits']}/{hit_stats['recent_10_total']} = {hit_stats['recent_10_rate']:.1f}%"
            if hit_stats['recent_5_total'] > 0:
                message += f"\n近5期表现：{hit_stats['recent_5_hits']}/{hit_stats['recent_5_total']} = {hit_stats['recent_5_rate']:.1f}%"
            
            message += """

━━━━━━━━━━━━━━━━━━━━━
📅 <b>最近预测记录</b>

"""
            
            for record in records[:10]:
                z1 = record['predict_zodiac1']
                z2 = record['predict_zodiac2']
                emoji1 = ZODIAC_EMOJI.get(z1, '')
                emoji2 = ZODIAC_EMOJI.get(z2, '')
                
                result_str = ""
                if record['is_hit'] == 1:
                    if record['hit_rank'] == 1:
                        result_str = f"✅ TOP1命中（{ZODIAC_EMOJI.get(record['actual_zodiac'], '')}{record['actual_zodiac']}）"
                    else:
                        result_str = f"✅ TOP2命中（{ZODIAC_EMOJI.get(record['actual_zodiac'], '')}{record['actual_zodiac']}）"
                else:
                    result_str = f"❌ 未中（{ZODIAC_EMOJI.get(record['actual_zodiac'], '')}{record['actual_zodiac']}）"
                
                message += f"{record['expect']}  预测:{emoji1}{z1}{emoji2}{z2}  {result_str}\n"
            
            message += "\n━━━━━━━━━━━━━━━━━━━━━"
        
        keyboard = [
            [InlineKeyboardButton("🔮 开始预测", callback_data="ai_zodiac_predict")],
            [InlineKeyboardButton("🔙 返回", callback_data="menu_predict")],
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
            
            # Update prediction result if exists
            self.db.update_prediction_result(expect, result['tema'], result['tema_zodiac'])
            
            # Notify all users with notifications enabled
            await self.notify_users(result, context)
            
        except Exception as e:
            logger.error(f"Error checking new result: {e}")
    
    async def notify_users(self, result: Dict, context: ContextTypes.DEFAULT_TYPE):
        """Notify users about new result with prediction comparison"""
        users = self.db.get_all_notify_users()
        
        codes = ' '.join([f"{x:02d}" for x in result['open_code'][:6]])
        zodiac_emoji = ZODIAC_EMOJI.get(result['tema_zodiac'], '')
        
        # Check if there's a prediction for this period
        prediction = self.db.get_prediction_record(result['expect'])
        
        message = f"""
🎰 <b>【新开奖结果】</b>

━━━━━━━━━━━━━━━━━━━━━
📅 期号：{result['expect']}
⏰ 时间：{result['open_time']}

🎲 正码：<code>{codes}</code>

━━━━━━━━━━━━━━━━━━━━━
🌟 <b>特码：{result['tema']:02d}</b>  {zodiac_emoji}{result['tema_zodiac']}
━━━━━━━━━━━━━━━━━━━━━
"""
        
        # Add prediction comparison if exists
        if prediction and prediction['is_hit'] > 0:
            pred_z1 = prediction['predict_zodiac1']
            pred_z2 = prediction['predict_zodiac2']
            emoji1 = ZODIAC_EMOJI.get(pred_z1, '')
            emoji2 = ZODIAC_EMOJI.get(pred_z2, '')
            
            message += f"""

🔮 <b>AI 预测对比</b>

预测：{emoji1}{pred_z1} + {emoji2}{pred_z2}
结果：{zodiac_emoji}{result['tema_zodiac']}

"""
            
            if prediction['is_hit'] == 1:
                if prediction['hit_rank'] == 1:
                    message += f"🎉 <b>预测命中！TOP1 生肖正确！</b>\n"
                else:
                    message += f"🎊 <b>预测命中！TOP2 生肖正确！</b>\n"
                
                # Get hit rate stats
                hit_stats = self.db.calculate_hit_rate()
                message += f"""

━━━━━━━━━━━━━━━━━━━━━
📊 <b>命中率统计</b>

总命中率：{hit_stats['hit_rate']:.1f}%
"""
                if hit_stats['recent_10_total'] > 0:
                    message += f"近10期：{hit_stats['recent_10_hits']}/{hit_stats['recent_10_total']} = {hit_stats['recent_10_rate']:.1f}%\n"
            else:
                message += f"💔 <b>很遗憾，本期预测未中</b>\n"
            
            message += "\n━━━━━━━━━━━━━━━━━━━━━\n"
        
        message += "\n恭喜中奖的朋友！ 🎊"
        
        keyboard = [[InlineKeyboardButton("🎯 预测下期", callback_data="ai_zodiac_predict")]]
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
