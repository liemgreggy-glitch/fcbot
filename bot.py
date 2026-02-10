#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Telegram Bot (预测机器人)
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
from PIL import Image, ImageDraw, ImageFont
from tupian import ResultImageGenerator
from xuanji_scraper import XuanjiImageScraper
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
from prediction_engine_ultimate import PredictionEngineUltimate, TRADITIONAL_TO_SIMPLIFIED

# Load environment variables
load_dotenv()

# Configuration
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ADMIN_USER_ID = os.getenv("ADMIN_USER_ID")
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", "5"))
DATABASE_PATH = os.getenv("DATABASE_PATH", "lottery.db")
TIMEZONE = os.getenv("TIMEZONE", "Asia/Shanghai")
LOTTERY_TIME = os.getenv("LOTTERY_TIME", "21:32:32")
# 管理员白名单
ADMIN_USER_IDS = os.getenv('ADMIN_USER_IDS', '').split(',')
ADMIN_USER_IDS = [int(uid.strip()) for uid in ADMIN_USER_IDS if uid.strip().isdigit()]
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
    # 简体
    '鼠': '🐭', '牛': '🐮', '虎': '🐯', '兔': '🐰',
    '龙': '🐉', '蛇': '🐍', '马': '🐴', '羊': '🐑',
    '猴': '🐵', '鸡': '🐔', '狗': '🐶', '猪': '🐖',
    
    # 繁体（兼容 API 返回的繁体字）
    '鼠': '🐭', '牛': '🐮', '虎': '🐯', '兔': '🐰',
    '龍': '🐉', '蛇': '🐍', '馬': '🐴', '羊': '🐑',
    '猴': '🐵', '雞': '🐔', '狗': '🐶', '豬': '🐖'
}

# Reverse mapping: number to zodiac
NUMBER_TO_ZODIAC = {}
for zodiac, numbers in ZODIAC_NUMBERS.items():
    for num in numbers:
        NUMBER_TO_ZODIAC[num] = zodiac

# 权限检查装饰器
def admin_only(func):
    """装饰器：仅管理员可用"""
    async def wrapper(self, update, *args, **kwargs):
        user_id = None
        
        # 获取用户 ID
        if hasattr(update, 'message') and update.message:
            user_id = update.message.from_user.id
        elif hasattr(update, 'callback_query') and update.callback_query:
            user_id = update.callback_query.from_user.id
        
        # 检查是否是管理员
        if user_id and user_id not in ADMIN_USER_IDS:
            logger.warning(f"⚠️ 未授权访问: User {user_id}")
            if hasattr(update, 'message') and update.message:
                await update.message.reply_text("⚠️ 此机器人仅限授权用户使用")
            return
        
        return await func(self, update, *args, **kwargs)
    return wrapper


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
                notify_enabled INTEGER DEFAULT 1,           -- 开奖通知开关
                reminder_enabled INTEGER DEFAULT 0,         -- 21:00开奖提醒
                auto_predict_reminder INTEGER DEFAULT 1,    -- 新期号发布时提醒预测
                auto_predict INTEGER DEFAULT 0,             -- 开奖后自动预测（暂未实现）
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
        # 繁体转简体
        tema_zodiac = tema_zodiac.replace("龍", "龙").replace("馬", "马").replace("豬", "猪").replace("雞", "鸡")
        
        conn = self.get_connection()
        cursor = conn.cursor()
        ...
        
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
            'open_code': (
                json.loads(row['open_code']) if row['open_code'].strip().startswith('[') 
                else [int(x.strip()) for x in row['open_code'].split(',')]
            ),
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
            'open_code': json.loads(row['open_code']) if row['open_code'].startswith('[') else [int(x) for x in row['open_code'].split(',')],
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
    def get_result_by_expect(self, expect: str) -> Optional[Dict]:
        """Get lottery result by expect number"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        # 规范化期号（支持 '038' 或 '2026038' 格式）
        if len(expect) == 3:
            # 如果是3位数，需要匹配后3位
            cursor.execute("""
                SELECT expect, open_code, tema, tema_zodiac, open_time 
                FROM lottery_history 
                WHERE expect LIKE ?
                ORDER BY expect DESC
                LIMIT 1
            """, (f'%{expect}',))
        else:
            # 完整期号直接查询
            cursor.execute("""
                SELECT expect, open_code, tema, tema_zodiac, open_time 
                FROM lottery_history 
                WHERE expect = ?
            """, (expect,))
        
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return {
                'expect': row['expect'],
                'open_code': json.loads(row['open_code']),  # 这里是 JSON 字符串
                'tema': row['tema'],
                'tema_zodiac': row['tema_zodiac'],
                'open_time': row['open_time']
            }
        return None
    
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
        # Convert traditional Chinese to simplified Chinese using shared mapping
        for trad, simp in TRADITIONAL_TO_SIMPLIFIED.items():
            actual_zodiac = actual_zodiac.replace(trad, simp)
        
        conn = self.get_connection()
        cursor = conn.cursor()
        
        # Get prediction
        cursor.execute('SELECT predict_zodiac1, predict_zodiac2 FROM prediction_records WHERE expect = ?', (expect,))
        record = cursor.fetchone()
        
        if record:
            predict1, predict2 = record['predict_zodiac1'], record['predict_zodiac2']
            
            # Determine hit status
            # is_hit: 0 = not yet drawn, 1 = hit, 2 = miss
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
        """Get prediction history (only predictions with actual results)"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT * FROM prediction_records 
            WHERE actual_tema IS NOT NULL
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
        
        # Total predictions with actual results (both hits and misses)
        cursor.execute('SELECT COUNT(*) as total FROM prediction_records WHERE actual_tema IS NOT NULL')
        total = cursor.fetchone()['total']
        
        # Hit count (is_hit = 1 means hit)
        cursor.execute('SELECT COUNT(*) as hits FROM prediction_records WHERE is_hit = 1')
        hits = cursor.fetchone()['hits']
        
        # Recent 10 periods
        cursor.execute('''
            SELECT COUNT(*) as recent_hits 
            FROM (SELECT * FROM prediction_records WHERE actual_tema IS NOT NULL ORDER BY expect DESC LIMIT 10)
            WHERE is_hit = 1
        ''')
        recent_10_hits = cursor.fetchone()['recent_hits']
        
        cursor.execute('SELECT COUNT(*) as recent_total FROM (SELECT * FROM prediction_records WHERE actual_tema IS NOT NULL ORDER BY expect DESC LIMIT 10)')
        recent_10_total = cursor.fetchone()['recent_total']
        
        # Recent 5 periods
        cursor.execute('''
            SELECT COUNT(*) as recent_hits 
            FROM (SELECT * FROM prediction_records WHERE actual_tema IS NOT NULL ORDER BY expect DESC LIMIT 5)
            WHERE is_hit = 1
        ''')
        recent_5_hits = cursor.fetchone()['recent_hits']
        
        cursor.execute('SELECT COUNT(*) as recent_total FROM (SELECT * FROM prediction_records WHERE actual_tema IS NOT NULL ORDER BY expect DESC LIMIT 5)')
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

    
    def can_predict_3in3(self, user_id: int, expect: str, num_groups: int) -> bool:
        """Check if user can predict 3in3 for this period and group count"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT COUNT(*) as count 
            FROM predictions_3in3 
            WHERE user_id = ? AND expect = ? AND num_groups = ?
        ''', (user_id, expect, num_groups))
        
        result = cursor.fetchone()
        conn.close()
        
        return result['count'] == 0
    
    def save_3in3_prediction(self, user_id: int, expect: str, num_groups: int, predictions: list):
        """Save 3in3 prediction to database"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        # Convert predictions to JSON string
        predictions_json = json.dumps(predictions)
        
        try:
            cursor.execute('''
                INSERT INTO predictions_3in3 (user_id, expect, num_groups, predictions)
                VALUES (?, ?, ?, ?)
            ''', (user_id, expect, num_groups, predictions_json))
            
            conn.commit()
            conn.close()
            return True
        except sqlite3.IntegrityError:
            conn.close()
            return False
    
    def get_3in3_prediction(self, user_id: int, expect: str, num_groups: int) -> Optional[Dict]:
        """Get 3in3 prediction record"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT * FROM predictions_3in3 
            WHERE user_id = ? AND expect = ? AND num_groups = ?
        ''', (user_id, expect, num_groups))
        
        result = cursor.fetchone()
        conn.close()
        
        if result:
            return dict(result)
        return None
    
    def check_3in3_results(self, expect: str):
        """Check 3in3 predictions against actual results"""
        # Get actual result
        result = self.get_result_by_expect(expect)
        if not result:
            return
        
        actual_balls = result['open_code'][:7]  # First 7 balls
        actual_balls_str = json.dumps(actual_balls)
        
        conn = self.get_connection()
        cursor = conn.cursor()
        
        # Get all unchecked predictions for this period
        cursor.execute('''
            SELECT * FROM predictions_3in3 
            WHERE expect = ? AND is_checked = 0
        ''', (expect,))
        
        predictions = cursor.fetchall()
        
        for pred in predictions:
            pred_list = json.loads(pred['predictions'])
            hit_results = []
            
            # Check each group
            for group in pred_list:
                predicted_numbers = group[0]  # (numbers, scores)
                hit_count = sum(1 for num in predicted_numbers if num in actual_balls)
                hit_results.append({
                    'numbers': predicted_numbers,
                    'hit_count': hit_count,
                    'is_3in3': hit_count == 3
                })
            
            hit_results_json = json.dumps(hit_results)
            
            # Update record
            cursor.execute('''
                UPDATE predictions_3in3 
                SET actual_balls = ?, hit_results = ?, is_checked = 1
                WHERE id = ?
            ''', (actual_balls_str, hit_results_json, pred['id']))
        
        conn.commit()
        conn.close()
    
    def get_3in3_hit_stats(self, user_id: int, num_groups: int) -> Dict:
        """Calculate 3in3 hit rate statistics for specific group count"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT * FROM predictions_3in3 
            WHERE user_id = ? AND num_groups = ? AND is_checked = 1
            ORDER BY expect DESC
        ''', (user_id, num_groups))
        
        records = cursor.fetchall()
        conn.close()
        
        if not records:
            return {
                'total': 0,
                'hit_3in3': 0,
                'hit_rate': 0,
                'recent_5': {'total': 0, 'hits': 0, 'rate': 0}
            }
        
        total = len(records)
        hit_3in3 = 0
        recent_5_hits = 0
        
        for idx, record in enumerate(records):
            if record['hit_results']:
                hit_results = json.loads(record['hit_results'])
                # Check if any group got 3in3
                if any(r['is_3in3'] for r in hit_results):
                    hit_3in3 += 1
                    if idx < 5:
                        recent_5_hits += 1
        
        recent_5_total = min(5, total)
        
        return {
            'total': total,
            'hit_3in3': hit_3in3,
            'hit_rate': (hit_3in3 / total * 100) if total > 0 else 0,
            'recent_5': {
                'total': recent_5_total,
                'hits': recent_5_hits,
                'rate': (recent_5_hits / recent_5_total * 100) if recent_5_total > 0 else 0
            }
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
        """Predict based on comprehensive zodiac analysis"""
        
        # 1️⃣ 长期频率分析（100期）
        zodiac_list_100 = [h['tema_zodiac'] for h in history[:100]]
        long_term_counter = Counter(zodiac_list_100)
        
        # 2️⃣ 中期频率分析（50期）
        zodiac_list_50 = [h['tema_zodiac'] for h in history[:50]]
        mid_term_counter = Counter(zodiac_list_50)
        
        # 3️⃣ 短期频率分析（20期）
        zodiac_list_20 = [h['tema_zodiac'] for h in history[:20]]
        short_term_counter = Counter(zodiac_list_20)
        
        all_zodiacs = list(ZODIAC_NUMBERS.keys())
        zodiac_analysis = {}
        
        for zodiac in all_zodiacs:
            # 计算各周期出现频率
            freq_100 = long_term_counter.get(zodiac, 0)
            freq_50 = mid_term_counter.get(zodiac, 0)
            freq_20 = short_term_counter.get(zodiac, 0)
            
            # 计算遗漏期数（多久没出现）
            missing_periods = 0
            for h in history:
                if h['tema_zodiac'] == zodiac:
                    break
                missing_periods += 1
            
            # 综合评分算法
            # 长期低频 = 应该出现（权重 30%）
            long_term_score = (8.3 - freq_100 / 100 * 12) * 30  # 理论平均 8.3 次
            
            # 中期低频 = 近期冷门（权重 25%）
            mid_term_score = (4.2 - freq_50 / 50 * 12) * 25
            
            # 短期低频 = 当前冷门（权重 20%）
            short_term_score = (1.7 - freq_20 / 20 * 12) * 20
            
            # 遗漏期数 = 该轮到了（权重 25%）
            missing_score = min(missing_periods / 2, 25)  # 最多25分
            
            # 总分
            total_score = (long_term_score + mid_term_score + 
                          short_term_score + missing_score)
            
            zodiac_analysis[zodiac] = {
                'score': total_score,
                'freq_100': freq_100,
                'freq_50': freq_50,
                'freq_20': freq_20,
                'missing': missing_periods
            }
        
        # 按评分排序
        sorted_zodiacs = sorted(zodiac_analysis.items(), 
                              key=lambda x: x[1]['score'], 
                              reverse=True)
        
        # 选择 TOP 5
        top5 = []
        scores = {}
        
        for i, (zodiac, analysis) in enumerate(sorted_zodiacs[:5]):
            # 从该生肖的号码中选择
            num = random.choice(ZODIAC_NUMBERS[zodiac])
            top5.append(num)
            
            # 计算显示评分（60-95分）
            display_score = 95 - i * 7  # TOP1=95, TOP2=88, TOP3=81...
            scores[num] = display_score
        
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
        """Comprehensive prediction based on data analysis
        
        综合预测算法（纯数据驱动）：
        1. 长期频率分析（100期）- 30% 权重
        2. 短期遗漏分析（20期）- 35% 权重  
        3. 生肖周期分析（30期）- 25% 权重
        4. 连号避免机制 - 10% 权重
        
        Note: Predicts only numbers 1-49.
        """
        all_scores = defaultdict(float)
        
        # 因子1：长期频率分析（30%权重）- 冷号回补理论
        tema_list_100 = [h['tema'] for h in history[:100]]
        counter_100 = Counter(tema_list_100)
        expected_freq = 100 / 49  # 理论平均 2.04 次
        
        for num in range(1, 50):
            freq = counter_100.get(num, 0)
            # 出现越少，分数越高（冷号回补）
            if freq == 0:
                all_scores[num] += 30  # 从未出现，满分
            else:
                deviation = expected_freq - freq
                score = (deviation / expected_freq) * 30
                all_scores[num] += max(0, score)  # 低于平均才加分
        
        # 因子2：短期遗漏分析（35%权重）
        recent_20 = [h['tema'] for h in history[:20]]
        for num in range(1, 50):
            if num not in recent_20:
                all_scores[num] += 35  # 最近20期没出现，满分
            else:
                # 根据距离现在的位置计算分数
                last_idx = recent_20.index(num)  # 0=最新期, 19=第20期
                # 越早出现，分数越高
                all_scores[num] += (last_idx / 20) * 35
        
        # 因子3：生肖周期分析（25%权重）
        zodiac_list_30 = [h['tema_zodiac'] for h in history[:30]]
        zodiac_counter = Counter(zodiac_list_30)
        expected_zodiac_freq = 30 / 12  # 理论平均 2.5 次
        
        for num in range(1, 50):
            zodiac = NUMBER_TO_ZODIAC.get(num)
            if zodiac:
                zodiac_freq = zodiac_counter.get(zodiac, 0)
                # 该生肖出现越少，分数越高
                if zodiac_freq == 0:
                    all_scores[num] += 25
                else:
                    deviation = expected_zodiac_freq - zodiac_freq
                    score = (deviation / expected_zodiac_freq) * 25
                    all_scores[num] += max(0, score)
        
        # 因子4：连号避免机制（10%权重）
        # 避免预测刚出现过的号码
        recent_5 = [h['tema'] for h in history[:5]]
        for num in range(1, 50):
            if num in recent_5[:2]:
                # 最近2期出现过，扣分
                all_scores[num] -= 10
            elif num in recent_5[2:5]:
                # 3-5期出现过，扣少一点
                all_scores[num] -= 5
            else:
                # 最近5期没出现，加分
                all_scores[num] += 10
        
        # 排序取 TOP 5
        sorted_nums = sorted(all_scores.items(), key=lambda x: x[1], reverse=True)
        top5 = [num for num, _ in sorted_nums[:5]]
        
        # 计算显示评分（归一化到 60-95 分）
        scores = {}
        for i, num in enumerate(top5):
            # 递减评分：95, 88, 81, 74, 67
            display_score = 95 - i * 7
            scores[num] = display_score
        
        return top5, scores
    
    def predict_top2_zodiac(self, period: int = 100, expect: str = None) -> Dict:
        """
        Predict TOP 2 most likely zodiacs based on multi-dimensional analysis
        
        Analysis dimensions:
        1. Frequency analysis (30% weight) - Recent appearance count
        2. Missing analysis (30% weight) - Periods since last appearance
        3. Cycle analysis (20% weight) - Deviation from expected frequency
        4. Trend analysis (20% weight) - Recent 10 period trend
        
        Returns: TOP 2 zodiacs with detailed analysis data
        """
        # Dynamic history range based on expect number
        if expect:
            period_num = int(expect[-3:])  # 取期号后3位
            ranges = {0: 300, 1: 200, 2: 100, 3: 50, 4: 30}
            dynamic_period = ranges[period_num % 5]
            
            # Use expect + period as random seed
            random.seed(int(expect) * 1000 + dynamic_period)
        else:
            dynamic_period = period
            random.seed(int(datetime.now().timestamp()))
        
        history = self.db.get_history(dynamic_period)
        
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
            freq_score = self._calculate_frequency_score(history, zodiac, dynamic_period)
            missing_score = self._calculate_missing_score(history, zodiac)
            cycle_score = self._calculate_cycle_score(history, zodiac, dynamic_period)
            trend_score = self._calculate_trend_score(history, zodiac)
            
            # Add small random factor for variation (±5)
            random_factor = random.uniform(-5, 5)
            
            final_score = (
                freq_score * 0.30 +
                missing_score * 0.30 +
                cycle_score * 0.20 +
                trend_score * 0.20
            ) + random_factor
            
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
        
        # Reset random seed
        random.seed()
        
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
        
        # Find all appearances and calculate missing periods between them
        # Note: zodiac_list is in reverse chronological order (newest first)
        appearances = []
        for i, z in enumerate(zodiac_list):
            if z == zodiac:
                appearances.append(i)
        
        # Calculate missing periods between consecutive appearances
        if appearances:
            gaps = []
            for i in range(len(appearances) - 1):
                # Since appearances are in reverse order, later appearance has larger index
                gap = appearances[i+1] - appearances[i] - 1
                if gap >= 0:  # Only count positive gaps
                    gaps.append(gap)
            
            max_missing = max(gaps) if gaps else current_missing
            avg_missing = sum(gaps) / len(gaps) if gaps else current_missing
        else:
            # Never appeared
            max_missing = len(zodiac_list)
            avg_missing = len(zodiac_list)
        
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

    def predict_3in3(self, num_groups: int = 1, expect: str = None) -> List[Tuple[List[int], Dict]]:
        """
        3中3预测 - 预测七色球中可能出现的3个号码
        
        Args:
            num_groups: 预测组数（1/3/5/10）
        
        Returns:
            [(号码组1, 评分1), (号码组2, 评分2), ...]
        """
        # Dynamic history range based on expect number
        if expect:
            period_num = int(expect[-3:])  # 取期号后3位
            ranges = {0: 300, 1: 200, 2: 100, 3: 50, 4: 30}
            dynamic_period = ranges[period_num % 5]
            
            # Use expect + num_groups as random seed
            seed_value = int(expect) * 100 + num_groups
            random.seed(seed_value)
        else:
            dynamic_period = 100
            random.seed(int(datetime.now().timestamp()))
        
        history = self.db.get_history(dynamic_period)
        
        if not history:
            # 无历史数据时随机生成
            result_groups = []
            for _ in range(num_groups):
                top3 = sorted(random.sample(range(1, 50), 3))
                scores = {top3[0]: 50.0, top3[1]: 50.0, top3[2]: 50.0}
                result_groups.append((top3, scores))
            return result_groups
        
        # 统计每个号码在七色球中的出现频率
        all_scores = defaultdict(float)
        
        # 因子1：七色球历史频率（40%权重）
        # 统计最近100期，每个号码在七色球中出现的次数
        for record in history[:100]:
            open_code = record.get('open_code', [])
            if isinstance(open_code, list):
                for num in open_code:
                    if 1 <= num <= 49:
                        all_scores[num] += 0.4
        
        # 因子2：七色球遗漏分析（30%权重）
        # 最近20期没在七色球中出现的号码，加分
        recent_balls = set()
        for record in history[:20]:
            open_code = record.get('open_code', [])
            if isinstance(open_code, list):
                for num in open_code:
                    if 1 <= num <= 49:
                        recent_balls.add(num)
        
        for num in range(1, 50):
            if num not in recent_balls:
                all_scores[num] += 30
            else:
                # 计算最近一次出现的位置
                for idx, record in enumerate(history[:20]):
                    open_code = record.get('open_code', [])
                    if isinstance(open_code, list) and num in open_code:
                        all_scores[num] += (idx / 20) * 30
                        break
        
        # 因子3：生肖均衡（30%权重）
        # 七色球通常会分布不同生肖
        zodiac_list = []
        for record in history[:30]:
            open_code = record.get('open_code', [])
            if isinstance(open_code, list):
                for num in open_code:
                    if 1 <= num <= 49:
                        zodiac = NUMBER_TO_ZODIAC.get(num)
                        if zodiac:
                            zodiac_list.append(zodiac)
        
        zodiac_counter = Counter(zodiac_list)
        expected_zodiac = len(zodiac_list) / 12 if zodiac_list else 1
        
        for num in range(1, 50):
            zodiac = NUMBER_TO_ZODIAC.get(num)
            if zodiac:
                freq = zodiac_counter.get(zodiac, 0)
                if freq < expected_zodiac:
                    all_scores[num] += 30
                else:
                    score = max(0, (expected_zodiac - freq) / expected_zodiac * 30)
                    all_scores[num] += score
        
        # Add small random factor for variation (±5 for each number)
        for num in range(1, 50):
            all_scores[num] += random.uniform(-5, 5)
        
        # 排序得到候选号码
        sorted_nums = sorted(all_scores.items(), key=lambda x: x[1], reverse=True)
        
        # 生成多组预测
        result_groups = []
        
        for group_idx in range(num_groups):
            if num_groups == 1:
                # 1组：直接取TOP3
                top3 = [num for num, _ in sorted_nums[:3]]
            else:
                # 多组：错开选择，保证多样性
                candidates = sorted_nums[:min(30, len(sorted_nums))]
                selected = []
                
                # 选择3个号码
                for i in range(3):
                    offset = group_idx * 3 + i
                    if offset < len(candidates):
                        num = candidates[offset][0]
                        selected.append(num)
                
                # 如果不够3个，随机补充
                while len(selected) < 3:
                    remaining = [n for n, _ in candidates if n not in selected]
                    if remaining:
                        selected.append(random.choice(remaining))
                    else:
                        selected.append(random.randint(1, 49))
                
                top3 = sorted(selected)
            
            # 计算评分（显示用）
            scores = {
                top3[0]: 95.0 - group_idx * 5,
                top3[1]: 85.0 - group_idx * 5,
                top3[2]: 75.0 - group_idx * 5
            }
            
            result_groups.append((top3, scores))
        
        # Reset random seed
        random.seed()
        
        return result_groups

class LotteryBot:
    """Main Telegram bot handler"""
    
    def __init__(self):
        self.db = DatabaseHandler(DATABASE_PATH)
        self.api = APIHandler()
        self.predictor = PredictionEngine(self.db)
        self.predictor_ultimate = PredictionEngineUltimate(self.db)
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
    @admin_only
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command"""
        user = update.effective_user
        self.db.get_user_settings(user.id)  # Create if not exists
        
        countdown = self.get_countdown()
        
        # 获取最新开奖结果
        latest = self.db.get_latest_result()
        
        message = f"""
🎰 <b>预测机器人</b> 🎰

👋 欢迎，{user.first_name}！

📅 <b>今日开奖倒计时：<code>{countdown}</code></b>
⏰ <b>开奖时间：每晚 {LOTTERY_TIME}</b>
"""
        
        # 添加最新开奖结果
        if latest:
            tema = latest['tema']
            open_code = latest['open_code']
            expect = latest['expect']
            open_time = latest.get('open_time', '')
            zodiac = latest.get('tema_zodiac', NUMBER_TO_ZODIAC.get(tema, '未知'))
            zodiac_emoji = ZODIAC_EMOJI.get(zodiac, '')
            
            # 格式化开奖时间
            if open_time:
                from datetime import datetime
                try:
                    dt = datetime.strptime(open_time, '%Y-%m-%d %H:%M:%S')
                    time_str = dt.strftime('%m月%d日 %H:%M')
                except:
                    time_str = open_time
            else:
                time_str = '未知'
            
            # 格式化七色球（去掉方括号）
            if isinstance(open_code, list):
                balls_str = ', '.join([f"{str(int(num)).zfill(2)}" for num in open_code])
            else:
                balls_str = str(open_code).strip('[]')
            
            message += f"""
➖➖➖➖➖➖➖
📊 <b>最新开奖（{expect}期）</b>

🎯 <b>特码：{str(int(tema)).zfill(2)}    {zodiac_emoji}{zodiac}</b>
🎲 <b>七色球：{balls_str}</b>
📅 <b>时间：{time_str}</b>
➖➖➖➖➖➖➖
"""
        
        message += """
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
                InlineKeyboardButton("🔮 玄机预测图", callback_data="xuanji_menu"),
            ],
            [
                InlineKeyboardButton("⚙️ 个人设置", callback_data="menu_settings"),
                InlineKeyboardButton("❓ 帮助", callback_data="help"),
            ],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(message, reply_markup=reply_markup, parse_mode='HTML')
    
    @admin_only
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
        elif data == "predict_3in3":
            await self.show_3in3_groups_menu(query)
        elif data.startswith("3in3_groups_"):
            num_groups = int(data.replace("3in3_groups_", ""))
            await self.show_3in3_prediction(query, num_groups)
        elif data == "3in3_history":
            await self.show_3in3_history(query)
        elif data.startswith("predict_"):
            method = data.replace("predict_", "")
            await self.show_prediction(query, method)
        elif data == "ai_zodiac_predict":
            await self.show_ai_zodiac_predict(query)
        elif data == "xuanji_menu":
            await self.show_xuanji_menu(query)
        elif data.startswith("xuanji_select_"):
            # 选择图片类型后，显示期数菜单
            image_type = data.replace("xuanji_select_", "")
            await self.show_xuanji_period_menu(query, image_type)
        elif data.startswith("xuanji_"):
            # 格式：xuanji_huofenghuang_2026038
            parts = data.replace("xuanji_", "").split("_")
            if len(parts) == 2:
                image_type, expect = parts
                await self.show_xuanji_image(query, image_type, expect)
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
        elif data == "analysis_trends":
            await self.show_trends_analysis(query)
        elif data == "analysis_comprehensive":
            await self.show_comprehensive_report(query)
        
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

➖➖➖➖➖➖➖
📅 下期期号：{next_expect}
⏰ 开奖倒计时：{countdown}
➖➖➖➖➖➖➖
🔮 <b>AI 生肖预测（TOP 2）</b> ⭐ 推荐

基于多维度分析预测最可能的2个生肖
• 频率分析 (30%)
• 遗漏分析 (30%)
• 周期分析 (20%)
• 趋势分析 (20%)

📊 预测状态：{prediction_status}
➖➖➖➖➖➖➖
⚠️ 免责声明
本机器人仅供娱乐和学习参考，预测结果不构成任何投资建议。请理性娱乐，谨慎决策。

⚠️ 预测仅供参考，不保证准确性
"""
        
        keyboard = [
            [InlineKeyboardButton("🔮 AI 生肖预测（TOP 2）⭐", callback_data="ai_zodiac_predict")],
            [InlineKeyboardButton("🎲 三中三预测", callback_data="predict_3in3")],
            [
                InlineKeyboardButton("🤖 综合预测", callback_data="predict_comprehensive"),
                InlineKeyboardButton("🐲 生肖预测", callback_data="predict_zodiac"),
            ],
            [
                InlineKeyboardButton("🔥 热号预测", callback_data="predict_hot"),
                InlineKeyboardButton("❄️ 冷号预测", callback_data="predict_cold"),
            ],
            [InlineKeyboardButton("📊 预测历史", callback_data="prediction_history")],
            [InlineKeyboardButton("🔙 返主菜单", callback_data="back_to_main")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='HTML')
    
    async def show_prediction(self, query, method: str):
        """Show prediction result"""
        top5, scores = self.predictor.predict_top5(method)
        
        # 获取当前期号和下一期（必须在使用前定义！）
        latest = self.db.get_latest_result()
        current_expect = latest['expect'] if latest else '未知'
        if latest and latest['expect'].isdigit():
            next_expect = str(int(latest['expect']) + 1)
        else:
            next_expect = '未知'
        
        method_names = {
            'comprehensive': 'AI综合预测',
            'zodiac': '生肖预测',
            'hot': '热号预测',
            'cold': '冷号预测',
            'frequency': '频率预测'
        }
        
        # 添加期号显示
        message = f"🎯 <b>{method_names.get(method, '预测')}</b>\n\n"
        message += f"📅 当前期号：{current_expect}\n"
        message += f"🎲 预测期号：<b>{next_expect}</b>\n\n"
        message += "➖➖➖➖➖➖➖\n"
        message += "📊 <b>TOP5 特码预测：</b>\n\n"
        
        for idx, num in enumerate(top5, 1):
            zodiac = NUMBER_TO_ZODIAC.get(num, '未知')
            zodiac_emoji = ZODIAC_EMOJI.get(zodiac, '')
            score = scores.get(num, 0)
            bar = "█" * int(score / 10)
            message += f"{idx}. 号码 <b>{str(int(num)).zfill(2)}</b> {zodiac_emoji}{zodiac} - {score:.1f}%\n"
            message += f"   {bar}\n\n"
        
        countdown = self.get_countdown()
        message += "➖➖➖➖➖➖➖\n"
        message += f"⏰ 距离开奖：<code>{countdown}</code>\n"
        message += "\n⚠️ <i>预测仅供参考，请理性对待</i>"
        
        # Save prediction
        if latest:
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

➖➖➖➖➖➖➖
📅 预测期号：{next_expect}
⏰ 开奖倒计时：{countdown}

➖➖➖➖➖➖➖
📊 预测状态：<b>未预测</b>

💡 <b>提示：</b>
• 每期仅可预测一次
• 预测后自动锁定，不可修改
• 开奖后自动对比结果
• 结果将记录到历史

➖➖➖➖➖➖➖
🤖 <b>AI 分析维度：</b>

✅ 生肖频率分析（30%权重）
✅ 生肖遗漏分析（30%权重）
✅ 生肖周期分析（20%权重）
✅ 生肖趋势分析（20%权重）

分析期数：根据期号动态调整（30-300期）

➖➖➖➖➖➖➖
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
        
        # Calculate dynamic period based on expect
        period_num = int(next_expect[-3:])
        ranges = {0: 300, 1: 200, 2: 100, 3: 50, 4: 30}
        dynamic_period = ranges[period_num % 5]
        
        # Show progress animation
        progress_msg = f"""
⏳ <b>AI 正在分析历史数据...</b>

✅ 加载最近{dynamic_period}期历史数据...
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
        
        # Perform prediction with ultimate engine (18 dimensions)
        prediction = self.predictor_ultimate.predict_top2_zodiac(300, next_expect)
        
        # Get dynamic period from prediction
        dynamic_period = prediction.get('period', 100)
        
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
        await self.display_zodiac_prediction(query, next_expect, prediction, dynamic_period)
    
    async def display_zodiac_prediction(self, query, expect: str, prediction: Dict, dynamic_period: int = 100):
        """Display zodiac prediction result with 18-dimensional analysis"""
        countdown = self.get_countdown()
        
        zodiac1 = prediction['zodiac1']
        zodiac2 = prediction['zodiac2']
        emoji1 = ZODIAC_EMOJI.get(zodiac1, '')
        emoji2 = ZODIAC_EMOJI.get(zodiac2, '')
        
        numbers1_str = ', '.join(f"{str(int(n)).zfill(2)}" for n in prediction['numbers1'])
        numbers2_str = ', '.join(f"{str(int(n)).zfill(2)}" for n in prediction['numbers2'])
        
        score1 = prediction['score1']
        score2 = prediction['score2']
        
        # Convert scores to confidence percentages (normalize to 0-100%)
        confidence1 = min(100, score1)
        confidence2 = min(100, score2)
        
        # Get hit rate
        hit_stats = self.db.calculate_hit_rate()
        
        message = f"""
🎯 <b>AI 生肖预测（TOP 2）</b>

📊 <b>18维度综合分析</b>
{'═' * 27}
🥇 第一预测：{emoji1} {zodiac1} (置信度: {confidence1:.1f}%)
🥈 第二预测：{emoji2} {zodiac2} (置信度: {confidence2:.1f}%)

📈 <b>分析维度：</b>
✅ 马尔可夫链 | ✅ 傅里叶周期
✅ 贝叶斯概率 | ✅ 蒙特卡洛验证
✅ 五行分析   | ✅ 波色分析
✅ 生肖关系   | ✅ 大小单双
✅ 遗漏分析   | ✅ 热度分析
✅ 周期规律   | ✅ 连开惩罚
✅ 号码冷热   | ✅ 尾数走势
✅ 质合分析   | ✅ 波色分析
✅ 重复惩罚   | ✅ 随机扰动

🔢 <b>对应号码：</b>
{zodiac1}：{numbers1_str}
{zodiac2}：{numbers2_str}

➖➖➖➖➖➖➖
⏰ 预测时间：{datetime.now(self.tz).strftime('%Y-%m-%d %H:%M:%S')}
📅 预测期号：{expect}
📊 开奖倒计时：{countdown}
📈 分析期数：{dynamic_period}期
"""
        
        if hit_stats['total'] > 0:
            message += f"""
➖➖➖➖➖➖➖
📊 <b>历史命中率统计</b>

总预测次数：{hit_stats['total']}期
命中次数：{hit_stats['hits']}期
总命中率：{hit_stats['hit_rate']:.1f}% 📈
"""
            if hit_stats['recent_10_total'] > 0:
                message += f"近10期表现：{hit_stats['recent_10_hits']}/{hit_stats['recent_10_total']} = {hit_stats['recent_10_rate']:.1f}%\n"
            if hit_stats['recent_5_total'] > 0:
                message += f"近5期表现：{hit_stats['recent_5_hits']}/{hit_stats['recent_5_total']} = {hit_stats['recent_5_rate']:.1f}%\n"
        
        message += """
➖➖➖➖➖➖➖
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
        
        # Get confidence scores from record if available, otherwise use default
        confidence1 = min(100, record.get('predict_score1', 85.0))
        confidence2 = min(100, record.get('predict_score2', 75.0))
        
        message = f"""
🎯 <b>AI 生肖预测（TOP 2）</b>

📊 <b>18维度综合分析</b>
{'═' * 27}
🥇 第一预测：{emoji1} {zodiac1} (置信度: {confidence1:.1f}%)
🥈 第二预测：{emoji2} {zodiac2} (置信度: {confidence2:.1f}%)

📈 <b>分析维度：</b>
✅ 马尔可夫链 | ✅ 傅里叶周期
✅ 贝叶斯概率 | ✅ 蒙特卡洛验证
✅ 五行分析   | ✅ 波色分析
✅ 生肖关系   | ✅ 大小单双
✅ 遗漏分析   | ✅ 热度分析
✅ 周期规律   | ✅ 连开惩罚
✅ 号码冷热   | ✅ 尾数走势
✅ 质合分析   | ✅ 波色分析
✅ 重复惩罚   | ✅ 随机扰动

🔢 <b>对应号码：</b>
{zodiac1}：{record['predict_numbers1']}
{zodiac2}：{record['predict_numbers2']}

➖➖➖➖➖➖➖
⏰ 开奖倒计时：{countdown}
📅 预测期号：{expect}
📊 本期预测状态：<b>✅ 已预测（已锁定）</b>
📅 预测时间：{record['predict_time']}
⏰ 开奖时间：预计 {LOTTERY_TIME}

💡 提示：开奖后将自动对比预测结果
"""
        
        # If already drawn, show comparison
        if record['is_hit'] > 0:
            actual_zodiac = record['actual_zodiac']
            actual_emoji = ZODIAC_EMOJI.get(actual_zodiac, '')
            
            message += f"""

➖➖➖➖➖➖➖
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

➖➖➖➖➖➖➖
"""
        
        keyboard = [
            [InlineKeyboardButton("📊 查看预测历史", callback_data="prediction_history")],
            [InlineKeyboardButton("🔙 返回", callback_data="menu_predict")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='HTML')
    async def show_xuanji_menu(self, query):
        """显示玄机图类型选择菜单"""
        from xuanji_scraper import XuanjiImageScraper
        
        # 获取最新期号
        latest = self.db.get_latest_result()
        if latest:
            current_expect = int(latest['expect'])
            next_expect = current_expect + 1
        else:
            next_expect = "未知"
        
        countdown = self.get_countdown()
        
        message = f"""
🔮 <b>玄机图查询</b>

➖➖➖➖➖➖➖
📅 最新期号：{next_expect}
⏰ 开奖倒计时：{countdown}
➖➖➖➖➖➖➖

📊 <b>请选择玄机图类型：</b>

💡 支持查看最新3期的玄机图
"""
        
        # 获取可用的图片类型
        types = XuanjiImageScraper.get_available_types()
        
        keyboard = []
        
        # 动态生成按钮
        for key, info in types.items():
            keyboard.append([
                InlineKeyboardButton(
                    f"{info['emoji']} {info['name']}",
                    callback_data=f"xuanji_select_{key}"
                )
            ])
        
        keyboard.append([InlineKeyboardButton("🔙 返回主菜单", callback_data="back_to_main")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='HTML')
    
    async def show_xuanji_image(self, query, image_type, expect=None):
        """显示指定类型的玄机图"""
        # 立即显示加载提示
        await query.answer("🔄 正在获取图片，请稍候...", show_alert=False)
        
        # 修改消息内容，显示加载中
        loading_msg = f"""
⏳ <b>正在获取玄机图...</b>

🔄 正在下载图片
🔄 请稍候片刻...
"""
        await query.edit_message_text(loading_msg, parse_mode='HTML')
        
        try:
            from xuanji_scraper import XuanjiImageScraper
            import os
            
            # 如果没有指定期数，获取下一期期号
            if not expect:
                latest = self.db.get_latest_result()
                if latest:
                    expect = str(int(latest['expect']) + 1)
                else:
                    await query.edit_message_text(
                        "❌ 无法获取最新期号，请稍后再试",
                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data="xuanji_menu")]])
                    )
                    return
            
            scraper = XuanjiImageScraper()
            image_path, result_expect, type_name = scraper.get_image(image_type, expect)
            
            if image_path and os.path.exists(image_path):
                emoji = XuanjiImageScraper.IMAGE_TYPES[image_type]['emoji']
                
                # 查询该期的开奖结果
                period_result = self.db.get_result_by_expect(result_expect)
                
                # 构建 caption
                caption = f"""{emoji} <b>{type_name}玄机图</b>

📅 <b>期号：第 {result_expect} 期</b>
"""
                
                # 如果该期已开奖，显示结果
                if period_result and period_result.get('open_code'):
                    import json
                    # 处理 opencode 可能是字符串或列表
                    if isinstance(period_result['open_code'], str):
                        if ',' in period_result['open_code']:
                            open_code_list = [int(x.strip()) for x in period_result['open_code'].split(',')]
                        else:
                            open_code_list = json.loads(period_result['open_code'])
                    else:
                        open_code_list = period_result['open_code']
                    tema = period_result.get('tema')
                    tema_zodiac = period_result.get('tema_zodiac', '')
                    
                    # 格式化号码
                    main_numbers = [str(n).zfill(2) for n in open_code_list[:6]]
                    special_number = str(tema).zfill(2) if tema else '?'
                    
                    caption += f"""
➖➖➖➖➖➖➖
🎯 <b>开奖结果</b>

🔢 <b>号码：{' '.join(main_numbers)} +  {special_number}</b>
"""
                    
                    # 添加生肖信息（如果有）
                    if tema_zodiac:
                        caption += f"🐾 <b>特码生肖：{ZODIAC_EMOJI.get(tema_zodiac, '')} {tema_zodiac}</b>\n"
                else:
                    caption += "\n⏰ <i>本期尚未开奖</i>\n"
                
                caption += """
➖➖➖➖➖➖➖
💡 <i>玄机图仅供参考，请理性对待</i>

⚠️ 本机器人仅供娱乐和学习参考，不构成任何投注建议。"""
                
                # 先发送图片
                sent_photo = await query.message.reply_photo(
                    photo=open(image_path, 'rb'),
                    caption=caption,
                    parse_mode='HTML'
                )
                
                # 删除临时文件
                try:
                    if os.path.exists(image_path):
                        os.remove(image_path)
                except:
                    pass
                
                # 删除加载消息
                try:
                    await query.message.delete()
                except:
                    pass
                
                # 在图片下方发送新的确认消息（这样按钮就在最下面）
                if sent_photo:
                    keyboard = [
                        [InlineKeyboardButton("🔙 返回玄机图菜单", callback_data="xuanji_menu")],
                        [InlineKeyboardButton("🏠 返回主菜单", callback_data="back_to_main")]
                    ]
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    await query.message.reply_text(
                        f"✅ {type_name}玄机图已发送",
                        reply_markup=reply_markup
                    )
            else:
                await query.edit_message_text(
                    f"❌ 获取{type_name}玄机图失败，请稍后再试\n\n可能原因：\n• 网络连接问题\n• 图片源暂时不可用\n• 该期图片尚未发布",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data="xuanji_menu")]])
                )
                
        except Exception as e:
            logger.error(f"Error fetching xuanji image: {e}")
            import traceback
            traceback.print_exc()
            
            await query.edit_message_text(
                f"❌ 获取玄机图时发生错误\n\n错误信息：{str(e)}",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data="xuanji_menu")]])
            )
    async def show_xuanji_period_menu(self, query, image_type):
        """显示期数选择菜单"""
        from xuanji_scraper import XuanjiImageScraper
        
        # 获取最近3期的期号
        latest = self.db.get_latest_result()
        if latest:
            current_expect = int(latest['expect'])
            # 下一期就是最新的玄机图期数
            next_expect = current_expect + 1
            periods = [
                (str(next_expect), f"下一期 (第{next_expect}期)"),      # 038期 - 最新
                (str(current_expect), f"最新期 (第{current_expect}期)"),  # 037期 - 已开奖
                (str(current_expect - 1), f"上一期 (第{current_expect - 1}期)"),  # 036期 - 历史
            ]
        else:
            await query.edit_message_text(
                "❌ 无法获取期号信息",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data="xuanji_menu")]])
            )
            return
        
        type_info = XuanjiImageScraper.IMAGE_TYPES.get(image_type, {})
        type_name = type_info.get('name', '未知')
        type_emoji = type_info.get('emoji', '🔮')
        
        message = f"""
{type_emoji} <b>{type_name}玄机图</b>

➖➖➖➖➖➖➖
📊 <b>请选择期数：</b>

💡 提示：最新期为即将开奖的期数
"""
        
        keyboard = []
        for expect, label in periods:
            keyboard.append([
                InlineKeyboardButton(
                    label,
                    callback_data=f"xuanji_{image_type}_{expect}"
                )
            ])
        
        keyboard.append([InlineKeyboardButton("🔙 返回玄机图菜单", callback_data="xuanji_menu")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='HTML')

    async def show_3in3_groups_menu(self, query):
        """Show 3in3 prediction groups selection menu"""
        user_id = query.from_user.id
        latest = self.db.get_latest_result()
        if latest:
            next_expect = str(int(latest['expect']) + 1)
        else:
            next_expect = "未知"
        
        countdown = self.get_countdown()
        
        # Check prediction status for each group count
        can_predict_1 = self.db.can_predict_3in3(user_id, next_expect, 1)
        can_predict_3 = self.db.can_predict_3in3(user_id, next_expect, 3)
        can_predict_5 = self.db.can_predict_3in3(user_id, next_expect, 5)
        can_predict_10 = self.db.can_predict_3in3(user_id, next_expect, 10)
        
        status_1 = "📝 可预测" if can_predict_1 else "✅ 已预测"
        status_3 = "📝 可预测" if can_predict_3 else "✅ 已预测"
        status_5 = "📝 可预测" if can_predict_5 else "✅ 已预测"
        status_10 = "📝 可预测" if can_predict_10 else "✅ 已预测"
        
        message = f"""
🎲 <b>3中3预测</b>

➖➖➖➖➖➖➖
📅 预测期号：{next_expect}
⏰ 开奖倒计时：{countdown}
➖➖➖➖➖➖➖

🎯 <b>预测说明：</b>
预测七色球（7个号码）中可能出现的3个号码

➖➖➖➖➖➖➖
📊 <b>请选择预测组数：</b>

1组预测 - {status_1}
3组预测 - {status_3}
5组预测 - {status_5}
10组预测 - {status_10}

💡 每个组数独立预测，预测后锁定
"""
        
        keyboard = [
            [
                InlineKeyboardButton(
                    "1组预测" + ("" if can_predict_1 else " ✅"),
                    callback_data="3in3_groups_1"
                ),
                InlineKeyboardButton(
                    "3组预测" + ("" if can_predict_3 else " ✅"),
                    callback_data="3in3_groups_3"
                ),
            ],
            [
                InlineKeyboardButton(
                    "5组预测" + ("" if can_predict_5 else " ✅"),
                    callback_data="3in3_groups_5"
                ),
                InlineKeyboardButton(
                    "10组预测" + ("" if can_predict_10 else " ✅"),
                    callback_data="3in3_groups_10"
                ),
            ],
            [InlineKeyboardButton("📊 查看历史统计", callback_data="3in3_history")],
            [InlineKeyboardButton("🔙 返回", callback_data="menu_predict")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='HTML')
    
    async def show_3in3_prediction(self, query, num_groups: int):
        """Show 3in3 prediction result with 18-dimensional analysis"""
        user_id = query.from_user.id
        latest = self.db.get_latest_result()
        if latest:
            next_expect = str(int(latest['expect']) + 1)
        else:
            next_expect = "未知"
        
        # Check if already predicted
        if not self.db.can_predict_3in3(user_id, next_expect, num_groups):
            # Show existing prediction
            await self.show_existing_3in3_prediction(query, user_id, next_expect, num_groups)
            return
        
        countdown = self.get_countdown()
        
        # Get predictions using ultimate engine
        predictions = self.predictor_ultimate.predict_3in3(num_groups, next_expect)
        
        # Save to database
        self.db.save_3in3_prediction(user_id, next_expect, num_groups, predictions)
        
        # Calculate dynamic period for display
        period_num = int(next_expect[-3:])
        ranges = {0: 300, 1: 200, 2: 100, 3: 50, 4: 30}
        dynamic_period = ranges[period_num % 5]
        
        message = f"""
🎲 <b>3中3预测（{next_expect}期）</b>

📊 <b>18维度综合分析</b>
{'═' * 27}
📊 预测{num_groups}组，每组3个号码
📈 分析期数：{dynamic_period}期
⏰ 预测时间：{datetime.now(self.tz).strftime('%Y-%m-%d %H:%M:%S')}

📈 <b>分析维度：</b>
✅ 马尔可夫链 | ✅ 傅里叶周期
✅ 贝叶斯概率 | ✅ 蒙特卡洛验证
✅ 五行分析   | ✅ 波色分析
✅ 生肖关系   | ✅ 大小单双
✅ 遗漏分析   | ✅ 热度分析
✅ 周期规律   | ✅ 连开惩罚
✅ 号码冷热   | ✅ 尾数走势
✅ 质合分析   | ✅ 波色分析
✅ 重复惩罚   | ✅ 随机扰动

➖➖➖➖➖➖➖
🔢 <b>预测号码组合：</b>

"""
        
        for idx, (numbers, analysis) in enumerate(predictions, 1):
            # Get confidence from analysis
            confidence = analysis.get('confidence', 50.0)
            
            message += f"""<b>第{idx}组</b> (置信度: {confidence:.1f}%)
"""
            for num in numbers:
                zodiac = NUMBER_TO_ZODIAC.get(num, '未知')
                zodiac_emoji = ZODIAC_EMOJI.get(zodiac, '')
                message += f"🎯 <b>{str(int(num)).zfill(2)}</b> {zodiac_emoji}{zodiac}\n"
            
            message += "➖➖➖➖➖➖➖\n"
        
        message += f"""
⏰ 距离开奖：<code>{countdown}</code>

✅ <b>预测已保存并锁定</b>
💡 开奖后将自动统计命中情况

⚠️ 预测仅供参考，请理性对待
"""
        
        # Get hit stats
        hit_stats = self.db.get_3in3_hit_stats(user_id, num_groups)
        
        if hit_stats['total'] > 0:
            message += f"""

➖➖➖➖➖➖➖
📊 <b>{num_groups}组预测历史统计</b>

总预测：{hit_stats['total']}期
3中3命中：{hit_stats['hit_3in3']}期
命中率：{hit_stats['hit_rate']:.1f}% 📈
"""
            if hit_stats['recent_5']['total'] > 0:
                message += f"近5期：{hit_stats['recent_5']['hits']}/{hit_stats['recent_5']['total']} = {hit_stats['recent_5']['rate']:.1f}%\n"
        
        keyboard = [
            [InlineKeyboardButton("📊 查看历史统计", callback_data="3in3_history")],
            [InlineKeyboardButton("🔙 返回", callback_data="predict_3in3")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='HTML')
    async def show_existing_3in3_prediction(self, query, user_id: int, expect: str, num_groups: int):
        """Show existing 3in3 prediction with 18-dimensional analysis"""
        record = self.db.get_3in3_prediction(user_id, expect, num_groups)
        
        if not record:
            await query.answer("❌ 未找到预测记录", show_alert=True)
            return
        
        countdown = self.get_countdown()
        predictions = json.loads(record['predictions'])
        
        message = f"""
🎲 <b>3中3预测（{expect}期）</b>

📊 <b>18维度综合分析</b>
{'═' * 27}
📊 {num_groups}组预测
⏰ 预测时间：{record['predict_time']}

📈 <b>分析维度：</b>
✅ 马尔可夫链 | ✅ 傅里叶周期
✅ 贝叶斯概率 | ✅ 蒙特卡洛验证
✅ 五行分析   | ✅ 波色分析
✅ 生肖关系   | ✅ 大小单双
✅ 遗漏分析   | ✅ 热度分析
✅ 周期规律   | ✅ 连开惩罚
✅ 号码冷热   | ✅ 尾数走势
✅ 质合分析   | ✅ 波色分析
✅ 重复惩罚   | ✅ 随机扰动

➖➖➖➖➖➖➖
📊 预测状态：<b>✅ 已预测（已锁定）</b>

➖➖➖➖➖➖➖
🔢 <b>预测号码组合：</b>

"""
        
        # Show predictions
        for idx, item in enumerate(predictions, 1):
            # Handle both old format (numbers, scores) and new format (numbers, analysis)
            if isinstance(item, (list, tuple)) and len(item) >= 2:
                numbers = item[0]
                second_item = item[1]
                # Check if it's new format with analysis dict
                if isinstance(second_item, dict):
                    if 'confidence' in second_item:
                        confidence = second_item['confidence']
                    elif 'individual_scores' in second_item:
                        confidence = sum(second_item['individual_scores'].values()) / len(second_item['individual_scores'])
                    else:
                        # Old format with scores dict
                        confidence = sum(second_item.values()) / len(second_item) if second_item else 50.0
                else:
                    confidence = 50.0
            else:
                numbers = item if isinstance(item, list) else []
                confidence = 50.0
            
            message += f"""<b>第{idx}组</b> (置信度: {confidence:.1f}%)
"""
            for num in numbers:
                zodiac = NUMBER_TO_ZODIAC.get(num, '未知')
                zodiac_emoji = ZODIAC_EMOJI.get(zodiac, '')
                message += f"🎯 <b>{str(int(num)).zfill(2)}</b> {zodiac_emoji}{zodiac}\n"
            
            message += "➖➖➖➖➖➖➖\n"
        
        # Check if results are available
        if record['is_checked'] and record['hit_results']:
            actual_balls = json.loads(record['actual_balls'])
            hit_results = json.loads(record['hit_results'])
            
            message += f"""

🎰 <b>开奖结果</b>

七色球：{', '.join(f"{str(int(n)).zfill(2)}" for n in actual_balls)}

➖➖➖➖➖➖➖
📊 <b>命中情况</b>

"""
            
            has_3in3 = False
            for idx, result in enumerate(hit_results, 1):
                numbers_str = ', '.join(f"{str(int(n)).zfill(2)}" for n in result['numbers'])
                hit_count = result['hit_count']
                
                if result['is_3in3']:
                    message += f"<b>第{idx}组</b> ✅ 3中3！\n"
                    message += f"预测：{numbers_str}\n"
                    message += f"命中：{hit_count}/3 🎉\n\n"
                    has_3in3 = True
                else:
                    message += f"<b>第{idx}组</b> 命中 {hit_count}/3\n"
                    message += f"预测：{numbers_str}\n\n"
            
            if has_3in3:
                message += "🎊 <b>恭喜！至少一组3中3！</b>\n"
            else:
                message += "💔 很遗憾，本期未中3中3\n"
        else:
            message += f"""

⏰ 距离开奖：<code>{countdown}</code>

💡 开奖后将自动统计命中情况
"""
        
        message += "\n➖➖➖➖➖➖➖\n"
        
        keyboard = [
            [InlineKeyboardButton("📊 查看历史统计", callback_data="3in3_history")],
            [InlineKeyboardButton("🔙 返回", callback_data="predict_3in3")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='HTML')
    
    async def show_3in3_history(self, query):
        """Show 3in3 prediction history statistics"""
        user_id = query.from_user.id
        
        # Get stats for all group counts
        stats_1 = self.db.get_3in3_hit_stats(user_id, 1)
        stats_3 = self.db.get_3in3_hit_stats(user_id, 3)
        stats_5 = self.db.get_3in3_hit_stats(user_id, 5)
        stats_10 = self.db.get_3in3_hit_stats(user_id, 10)
        
        message = """
📊 <b>3中3预测历史统计</b>

➖➖➖➖➖➖➖
"""
        
        if stats_1['total'] > 0:
            message += f"""
<b>1组预测</b>
总预测：{stats_1['total']}期
3中3命中：{stats_1['hit_3in3']}期
命中率：{stats_1['hit_rate']:.1f}% 📈
"""
            if stats_1['recent_5']['total'] > 0:
                message += f"近5期：{stats_1['recent_5']['hits']}/{stats_1['recent_5']['total']} = {stats_1['recent_5']['rate']:.1f}%\n"
            message += "\n➖➖➖➖➖➖➖\n"
        
        if stats_3['total'] > 0:
            message += f"""
<b>3组预测</b>
总预测：{stats_3['total']}期
3中3命中：{stats_3['hit_3in3']}期
命中率：{stats_3['hit_rate']:.1f}% 📈
"""
            if stats_3['recent_5']['total'] > 0:
                message += f"近5期：{stats_3['recent_5']['hits']}/{stats_3['recent_5']['total']} = {stats_3['recent_5']['rate']:.1f}%\n"
            message += "\n➖➖➖➖➖➖➖\n"
        
        if stats_5['total'] > 0:
            message += f"""
<b>5组预测</b>
总预测：{stats_5['total']}期
3中3命中：{stats_5['hit_3in3']}期
命中率：{stats_5['hit_rate']:.1f}% 📈
"""
            if stats_5['recent_5']['total'] > 0:
                message += f"近5期：{stats_5['recent_5']['hits']}/{stats_5['recent_5']['total']} = {stats_5['recent_5']['rate']:.1f}%\n"
            message += "\n➖➖➖➖➖➖➖\n"
        
        if stats_10['total'] > 0:
            message += f"""
<b>10组预测</b>
总预测：{stats_10['total']}期
3中3命中：{stats_10['hit_3in3']}期
命中率：{stats_10['hit_rate']:.1f}% 📈
"""
            if stats_10['recent_5']['total'] > 0:
                message += f"近5期：{stats_10['recent_5']['hits']}/{stats_10['recent_5']['total']} = {stats_10['recent_5']['rate']:.1f}%\n"
            message += "\n➖➖➖➖➖➖➖\n"
        
        if all(s['total'] == 0 for s in [stats_1, stats_3, stats_5, stats_10]):
            message += """
📝 暂无预测记录

开始预测后，这里将显示详细的命中率统计

➖➖➖➖➖➖➖
"""
        
        message += """
💡 <b>说明</b>
• 每个组数独立统计
• 只要任意一组3中3即算命中
• 统计包含所有已开奖期数
"""
        
        keyboard = [
            [InlineKeyboardButton("🔙 返回", callback_data="predict_3in3")],
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

➖➖➖➖➖➖➖
暂无预测历史记录

请先进行预测后查看
"""
        else:
            message = f"""
📊 <b>预测历史记录</b>

➖➖➖➖➖➖➖
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

➖➖➖➖➖➖➖
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
            
            message += "\n➖➖➖➖➖➖➖"
        
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

<b>基础分析</b>
• <b>频率分析</b> - 号码出现频次统计
• <b>生肖分布</b> - 各生肖出现比例
• <b>遗漏分析</b> - 长期未出号码
• <b>冷热分析</b> - 冷热号码对比

<b>高级分析</b>
• <b>走势分析</b> - 号码走势图表
• <b>综合报告</b> - 完整数据报告

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
            [
                InlineKeyboardButton("📈 走势分析", callback_data="analysis_trends"),
                InlineKeyboardButton("📋 综合报告", callback_data="analysis_comprehensive"),
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
            message += f"{idx}. <b>{str(int(num)).zfill(2)}</b> {zodiac_emoji}{zodiac} - {count}次 ({percentage:.1f}%)\n"
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
            message += f"{idx}. <b>{str(int(num)).zfill(2)}</b> {zodiac_emoji}{zodiac} - {status}\n"
        
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
            message += f"{idx}. <b>{str(int(num)).zfill(2)}</b> {zodiac_emoji}{zodiac} - {count}次\n"
        
        message += "\n❄️ <b>冷号 Top 10：</b>\n"
        for idx, (num, count) in enumerate(analysis['cold'], 1):
            zodiac = NUMBER_TO_ZODIAC.get(num, '未知')
            zodiac_emoji = ZODIAC_EMOJI.get(zodiac, '')
            message += f"{idx}. <b>{str(int(num)).zfill(2)}</b> {zodiac_emoji}{zodiac} - {count}次\n"
        
        keyboard = [[InlineKeyboardButton("🔙 返回分析菜单", callback_data="menu_analysis")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='HTML')
    
    async def show_trends_analysis(self, query):
        """Show trend analysis"""
        history = self.db.get_history(30)
        
        if not history:
            await query.edit_message_text("暂无历史数据")
            return
        
        # Analyze trends
        tema_list = [h['tema'] for h in history]
        zodiac_list = [h['tema_zodiac'] for h in history]
        
        # Get most recent trend (last 10 periods)
        recent_temas = tema_list[:10]
        recent_zodiacs = zodiac_list[:10]
        
        # Count consecutive number pairs (numbers differing by 1)
        consecutive_pairs = 0
        if len(recent_temas) >= 2:
            for i in range(len(recent_temas) - 1):
                if abs(recent_temas[i] - recent_temas[i+1]) == 1:
                    consecutive_pairs += 1
        
        # Zodiac distribution in recent 30
        zodiac_counter = Counter(zodiac_list)
        top_zodiacs = zodiac_counter.most_common(3)
        
        message = f"""
📈 <b>走势分析（最近30期）</b>

➖➖➖➖➖➖➖
🔍 <b>最近10期特码走势</b>

"""
        
        for i, tema in enumerate(recent_temas, 1):
            zodiac = NUMBER_TO_ZODIAC.get(tema, '未知')
            emoji = ZODIAC_EMOJI.get(zodiac, '')
            message += f"{i}. <b>{str(int(tema)).zfill(2)}</b> {emoji}{zodiac}\n"
        
        message += f"""

➖➖➖➖➖➖➖
📊 <b>走势特征分析</b>

🔗 连号出现：{consecutive_pairs}次
📍 连号概率：{consecutive_pairs/9*100:.1f}%

➖➖➖➖➖➖➖
🐉 <b>生肖热度排行（30期）</b>

"""
        
        for idx, (zodiac, count) in enumerate(top_zodiacs, 1):
            emoji = ZODIAC_EMOJI.get(zodiac, '')
            percentage = count / len(zodiac_list) * 100
            message += f"{idx}. {emoji}{zodiac}：{count}次 ({percentage:.1f}%)\n"
        
        message += """

➖➖➖➖➖➖➖
💡 <b>趋势提示</b>

"""
        
        if consecutive_pairs >= 3:
            message += "• 连号趋势明显，可关注连号组合\n"
        elif consecutive_pairs == 0:
            message += "• 近期无连号，下期可能出现\n"
        
        if len(top_zodiacs) > 0:
            hot_zodiac = top_zodiacs[0][0]
            hot_emoji = ZODIAC_EMOJI.get(hot_zodiac, '')
            message += f"• {hot_emoji}{hot_zodiac}生肖近期热度高\n"
        
        keyboard = [[InlineKeyboardButton("🔙 返回分析菜单", callback_data="menu_analysis")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='HTML')
    
    async def show_comprehensive_report(self, query):
        """Show comprehensive data report"""
        history = self.db.get_history(100)
        
        if not history:
            await query.edit_message_text("暂无历史数据")
            return
        
        # Collect statistics
        tema_list = [h['tema'] for h in history]
        zodiac_list = [h['tema_zodiac'] for h in history]
        
        # Basic stats
        total_periods = len(history)
        unique_numbers = len(set(tema_list))
        
        # Frequency analysis
        tema_counter = Counter(tema_list)
        most_common_tema = tema_counter.most_common(1)[0] if tema_counter else (0, 0)
        least_common = tema_counter.most_common()[-1] if tema_counter else (0, 0)
        
        # Zodiac analysis
        zodiac_counter = Counter(zodiac_list)
        most_common_zodiac = zodiac_counter.most_common(1)[0] if zodiac_counter else ('未知', 0)
        least_common_zodiac = zodiac_counter.most_common()[-1] if zodiac_counter else ('未知', 0)
        
        # Missing analysis
        all_numbers = set(range(1, 50))
        appeared = set(tema_list)
        not_appeared = all_numbers - appeared
        
        # Interval distribution
        intervals = {
            '01-10': len([t for t in tema_list if 1 <= t <= 10]),
            '11-20': len([t for t in tema_list if 11 <= t <= 20]),
            '21-30': len([t for t in tema_list if 21 <= t <= 30]),
            '31-40': len([t for t in tema_list if 31 <= t <= 40]),
            '41-49': len([t for t in tema_list if 41 <= t <= 49]),
        }
        
        latest = history[0]
        oldest = history[-1]
        
        message = f"""
📋 <b>综合数据报告</b>

➖➖➖➖➖➖➖
📊 <b>基础统计</b>

• 统计期数：{total_periods}期
• 数据范围：{oldest['expect']} - {latest['expect']}
• 统计时间：{datetime.now(self.tz).strftime('%Y-%m-%d %H:%M')}

➖➖➖➖➖➖➖
🔢 <b>号码分布</b>

• 最热号码：<b>{most_common_tema[0]:02d}</b> ({most_common_tema[1]}次)
• 最冷号码：<b>{least_common[0]:02d}</b> ({least_common[1]}次)
• 平均出现：{total_periods/49:.2f}次/号
• 号码覆盖：{unique_numbers}/49 ({unique_numbers/49*100:.1f}%)

➖➖➖➖➖➖➖
🐉 <b>生肖分布</b>

• 最热生肖：{ZODIAC_EMOJI.get(most_common_zodiac[0], '')}{most_common_zodiac[0]} ({most_common_zodiac[1]}次, {most_common_zodiac[1]/total_periods*100:.1f}%)
• 最冷生肖：{ZODIAC_EMOJI.get(least_common_zodiac[0], '')}{least_common_zodiac[0]} ({least_common_zodiac[1]}次, {least_common_zodiac[1]/total_periods*100:.1f}%)
• 理论期望：{total_periods/12:.2f}次/生肖

➖➖➖➖➖➖➖
📈 <b>遗漏分析</b>

• 从未出现：{len(not_appeared)}个号码
"""
        
        if not_appeared:
            not_appeared_list = sorted(list(not_appeared))[:5]
            not_appeared_str = ', '.join([f"{str(int(n)).zfill(2)}" for n in not_appeared_list])
            message += f"• 示例：{not_appeared_str}\n"
        
        message += f"""

➖➖➖➖➖➖➖
📊 <b>区间分布</b>

01-10：{intervals['01-10']}次 ({intervals['01-10']/total_periods*100:.1f}%)
11-20：{intervals['11-20']}次 ({intervals['11-20']/total_periods*100:.1f}%)
21-30：{intervals['21-30']}次 ({intervals['21-30']/total_periods*100:.1f}%)
31-40：{intervals['31-40']}次 ({intervals['31-40']/total_periods*100:.1f}%)
41-49：{intervals['41-49']}次 ({intervals['41-49']/total_periods*100:.1f}%)

➖➖➖➖➖➖➖
💡 <b>综合分析结论</b>

"""
        
        # Analysis conclusions
        if most_common_tema[1] > total_periods/49 * 2:
            message += f"• 热号策略：关注 {most_common_tema[0]:02d}（异常热）\n"
        
        if len(not_appeared) > 10:
            message += f"• 回补策略：{len(not_appeared)}个号码从未出现\n"
        
        if most_common_zodiac[1] > total_periods/12 * 1.5:
            emoji = ZODIAC_EMOJI.get(most_common_zodiac[0], '')
            message += f"• 生肖策略：{emoji}{most_common_zodiac[0]}热度高\n"
        
        if least_common_zodiac[1] < total_periods/12 * 0.5:
            emoji = ZODIAC_EMOJI.get(least_common_zodiac[0], '')
            message += f"• 冷肖回补：{emoji}{least_common_zodiac[0]}严重遗漏\n"
        
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
            codes = ' '.join([f"{str(int(x)).zfill(2)}" for x in h['open_code'][:6]])
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
        
        codes = ' '.join([f"{str(int(x)).zfill(2)}" for x in result['open_code'][:6]])
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
🎰 <b>预测机器人</b> 🎰

👋 欢迎，{user.first_name}！

📅 今日开奖倒计时：<code>{countdown}</code>
⏰ 开奖时间：每晚 {LOTTERY_TIME}

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
                InlineKeyboardButton("🔮 玄机预测图", callback_data="xuanji_menu"),
            ],
            
            
            [
                InlineKeyboardButton("⚙️ 个人设置", callback_data="menu_settings"),
                InlineKeyboardButton("❓ 帮助", callback_data="help"),
            ],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='HTML')
    
    async def check_new_result(self, context):
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
            
            # Check 3in3 predictions
            self.db.check_3in3_results(expect)
            
            # Notify all users with notifications enabled
            await self.notify_users(result, context)
            
        except Exception as e:
            import traceback
            logger.error(f"Error checking new result: {e}")
            logger.error(traceback.format_exc())
    def generate_result_image(self, result: Dict) -> str:
        """Generate result image like macaujc.com style"""
        try:
            # Image settings
            width = 800
            height = 300
            bg_color = (255, 255, 255)
            
            # Create image
            img = Image.new('RGB', (width, height), bg_color)
            draw = ImageDraw.Draw(img)
            
            # Try to load font, fallback to default
            try:
                title_font = ImageFont.truetype("/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf", 32)
                number_font = ImageFont.truetype("/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf", 48)
                zodiac_font = ImageFont.truetype("/usr/share/fonts/dejavu/DejaVuSans.ttf", 24)
            except:
                title_font = ImageFont.load_default()
                number_font = ImageFont.load_default()
                zodiac_font = ImageFont.load_default()
            
            # Color scheme (like macaujc.com)
            colors = {
                'red': (220, 53, 69),
                'blue': (13, 110, 253),
                'green': (25, 135, 84),
            }
            
            # Draw title
            title = f"新澳门六合彩  第 {result['expect']} 期"
            draw.text((50, 30), title, fill=(0, 0, 0), font=title_font)
            
            # Draw numbers
            codes = result['open_code'][:6]
            tema = result['tema']
            
            # Number positions
            box_size = 90
            box_gap = 10
            start_x = 50
            start_y = 100
            
            # Draw 6 regular numbers
            for i, num in enumerate(codes):
                x = start_x + i * (box_size + box_gap)
                
                # Alternate colors (red/blue like the website)
                color = colors['red'] if i % 2 == 0 else colors['blue']
                
                # Draw box
                draw.rectangle([x, start_y, x + box_size, start_y + box_size], 
                             fill=color, outline=(0, 0, 0), width=2)
                
                # Draw number
                num_text = f"{str(int(num)).zfill(2)}"
                bbox = draw.textbbox((0, 0), num_text, font=number_font)
                text_width = bbox[2] - bbox[0]
                text_height = bbox[3] - bbox[1]
                text_x = x + (box_size - text_width) // 2
                text_y = start_y + (box_size - text_height) // 2 - 10
                draw.text((text_x, text_y), num_text, fill=(255, 255, 255), font=number_font)
                
                # Draw zodiac below number
                zodiac = self.predictor.number_to_zodiac.get(num, '')
                if zodiac:
                    bbox = draw.textbbox((0, 0), zodiac, font=zodiac_font)
                    text_width = bbox[2] - bbox[0]
                    zodiac_x = x + (box_size - text_width) // 2
                    draw.text((zodiac_x, start_y + box_size - 35), zodiac, 
                            fill=(255, 255, 255), font=zodiac_font)
            
            # Draw "+" sign
            plus_x = start_x + 6 * (box_size + box_gap) + 10
            draw.text((plus_x, start_y + box_size // 2 - 20), "+", 
                     fill=(0, 0, 0), font=number_font)
            
            # Draw special number (tema) in green
            tema_x = plus_x + 40
            draw.rectangle([tema_x, start_y, tema_x + box_size, start_y + box_size], 
                         fill=colors['green'], outline=(0, 0, 0), width=2)
            
            # Draw tema number
            tema_text = f"{str(int(tema)).zfill(2)}"
            bbox = draw.textbbox((0, 0), tema_text, font=number_font)
            text_width = bbox[2] - bbox[0]
            text_height = bbox[3] - bbox[1]
            text_x = tema_x + (box_size - text_width) // 2
            text_y = start_y + (box_size - text_height) // 2 - 10
            draw.text((text_x, text_y), tema_text, fill=(255, 255, 255), font=number_font)
            
            # Draw tema zodiac
            tema_zodiac = result['tema_zodiac']
            bbox = draw.textbbox((0, 0), tema_zodiac, font=zodiac_font)
            text_width = bbox[2] - bbox[0]
            zodiac_x = tema_x + (box_size - text_width) // 2
            draw.text((zodiac_x, start_y + box_size - 35), tema_zodiac, 
                    fill=(255, 255, 255), font=zodiac_font)
            
            # Save image
            image_path = f"/tmp/result_{result['expect']}.png"
            img.save(image_path)
            return image_path
            
        except Exception as e:
            logger.error(f"Error generating image: {e}")
            return None 

    async def notify_users(self, result: Dict, context: ContextTypes.DEFAULT_TYPE):
        """Notify users about new result with prediction comparison"""
        logger.info(f"[DEBUG] notify_users called")
        logger.info(f"[DEBUG] result type: {type(result).__name__}")
        logger.info(f"[DEBUG] result content: {result}")
        users = self.db.get_all_notify_users()
        
        codes = ' '.join([f"{str(int(x)).zfill(2)}" for x in result['open_code'][:6]])
        zodiac_emoji = ZODIAC_EMOJI.get(result['tema_zodiac'], '')
        
        # Check if there's a prediction for this period
        prediction = self.db.get_prediction_record(result['expect'])
        
        message = f"""
🎰 <b>【新开奖结果】</b>

➖➖➖➖➖➖➖
📅 期号：{result['expect']}
⏰ 时间：{result['open_time']}

🎲 正码：<code>{codes}</code>

➖➖➖➖➖➖➖
🌟 <b>特码：{result['tema']:02d}</b>  {zodiac_emoji}{result['tema_zodiac']}
➖➖➖➖➖➖➖
"""
        
        # Add prediction comparison if exists and result has been recorded
        # is_hit > 0 means result has been compared (1=hit, 2=miss)
        if prediction and prediction.get('is_hit', 0) > 0:
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

➖➖➖➖➖➖➖
📊 <b>命中率统计</b>

总命中率：{hit_stats['hit_rate']:.1f}%
"""
                if hit_stats['recent_10_total'] > 0:
                    message += f"近10期：{hit_stats['recent_10_hits']}/{hit_stats['recent_10_total']} = {hit_stats['recent_10_rate']:.1f}%\n"
            elif prediction['is_hit'] == 2:
                # is_hit == 2 means it's a miss
                message += f"💔 <b>很遗憾，本期预测未中</b>\n"
            
            message += "\n➖➖➖➖➖➖➖\n"
        
        message += "\n恭喜中奖的朋友！ 🎊"
        
        keyboard = [[InlineKeyboardButton("🎯 预测下期", callback_data="ai_zodiac_predict")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # Generate result image using tupian module
        img_gen = ResultImageGenerator()
        image_path = img_gen.generate(result)
        
        # Only notify admin
        admin_id = int(os.getenv('ADMIN_USER_IDS', '0'))
        if admin_id == 0:
            logger.warning("ADMIN_USER_IDS not configured")
            return
        
        for user_id in [admin_id]:
            try:
                # Send image first
                if image_path and os.path.exists(image_path):
                    await context.bot.send_photo(
                        chat_id=user_id,
                        photo=open(image_path, 'rb')
                    )
                
                # Then send text message
                await context.bot.send_message(
                    chat_id=user_id,
                    text=message,
                    reply_markup=reply_markup,
                    parse_mode='HTML'
                )
                logger.info(f"Notified user {user_id}")
            except Exception as e:
                logger.error(f"Error notifying user {user_id}: {e}")
        
        # Clean up image file
        if image_path and os.path.exists(image_path):
            os.remove(image_path)
    
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
        
        # Only notify admin
        admin_id = int(os.getenv('ADMIN_USER_IDS', '0'))
        if admin_id == 0:
            logger.warning("ADMIN_USER_IDS not configured")
            return
        
        for user_id in [admin_id]:
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
        # Check for new results at 21:30-21:40 (every minute)
        for m in range(30, 41):  # 30 到 40 分钟
            scheduler.add_job(
                self.smart_check,
                CronTrigger(hour=21, minute=m, second=0, timezone=self.tz),
                args=[application],
                id=f'smart_check_{m}'
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
        """Smart check - always check for new results"""
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
            application.run_polling(allowed_updates=Update.ALL_TYPES, close_loop=True)
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
