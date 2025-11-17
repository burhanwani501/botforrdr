import os
import logging
import pandas as pd
import numpy as np
import matplotlib
# Use non-interactive backend for Render
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import schedule
import time
import asyncio
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters
from telegram.constants import ParseMode
from telegram.error import TelegramError, BadRequest
from dotenv import load_dotenv
import json
import sqlite3
import hashlib
import aiohttp
from typing import Dict, List, Optional, Tuple
import warnings

warnings.filterwarnings('ignore')

# Load environment variables first
load_dotenv()

# Import config after loading env
import config

# Configure logging for Render
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=getattr(logging, config.config.LOG_LEVEL),
    handlers=[
        logging.StreamHandler()  # Only stream handler for Render
    ]
)
logger = logging.getLogger(__name__)

class BinaryTradingBot:
    def __init__(self):
        self.config = config.config
        self.application = Application.builder().token(self.config.BOT_TOKEN).build()
        self.user_cooldown = {}
        self.setup_handlers()
        self.setup_database()
        self.setup_advanced_features()
        
        # Validate configuration
        try:
            self.config.validate_config()
        except ValueError as e:
            logger.error(f"Configuration error: {e}")
            raise
    
    def setup_advanced_features(self):
        """Setup advanced features"""
        self.session = None
        self.last_signal_time = {}
        self.user_analytics = {}
        self.premium_users = set()
    
    def setup_database(self):
        """Initialize SQLite database with advanced schema"""
        self.conn = sqlite3.connect(self.config.DATABASE_NAME, check_same_thread=False)
        cursor = self.conn.cursor()
        
        # Users table with enhanced fields
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                risk_level TEXT DEFAULT 'medium',
                preferred_pairs TEXT DEFAULT 'EUR/USD,GBP/USD',
                notification_enabled INTEGER DEFAULT 1,
                is_premium INTEGER DEFAULT 0,
                premium_until TIMESTAMP NULL,
                joined_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                total_signals INTEGER DEFAULT 0,
                successful_signals INTEGER DEFAULT 0,
                last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                language_code TEXT DEFAULT 'en'
            )
        ''')
        
        # Enhanced signals table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pair TEXT,
                direction TEXT,
                expiry_time TIMESTAMP,
                confidence REAL,
                price REAL,
                stop_loss REAL,
                take_profit REAL,
                signal_type TEXT DEFAULT 'regular',
                strategy TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                success INTEGER DEFAULT NULL,
                actual_result TEXT DEFAULT NULL,
                profit_loss REAL DEFAULT NULL
            )
        ''')
        
        # User signals tracking
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_signals (
                user_id INTEGER,
                signal_id INTEGER,
                received_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                action_taken TEXT DEFAULT 'viewed',
                result_noted INTEGER DEFAULT 0,
                FOREIGN KEY (user_id) REFERENCES users (user_id),
                FOREIGN KEY (signal_id) REFERENCES signals (id)
            )
        ''')
        
        # Channel subscription tracking
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS channel_subs (
                user_id INTEGER PRIMARY KEY,
                channel_username TEXT,
                subscribed INTEGER DEFAULT 0,
                last_checked TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
        ''')
        
        self.conn.commit()
        logger.info("Database initialized successfully")
    
    def setup_handlers(self):
        """Setup all command and callback handlers"""
        # Command handlers
        self.application.add_handler(CommandHandler("start", self.start))
        self.application.add_handler(CommandHandler("help", self.help_command))
        self.application.add_handler(CommandHandler("signal", self.send_signal))
        self.application.add_handler(CommandHandler("settings", self.settings))
        self.application.add_handler(CommandHandler("stats", self.user_stats))
        self.application.add_handler(CommandHandler("history", self.signal_history))
        self.application.add_handler(CommandHandler("analysis", self.market_analysis))
        self.application.add_handler(CommandHandler("premium", self.premium_info))
        self.application.add_handler(CommandHandler("admin", self.admin_panel))
        self.application.add_handler(CommandHandler("otc", self.otc_market))
        
        # Callback handlers
        self.application.add_handler(CallbackQueryHandler(self.button_handler))
        
        # Message handlers
        self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message))
        
        logger.info("Handlers setup completed")
    
    # ... (rest of your methods remain the same, they don't need modification for Render)
    
    async def create_binary_chart(self, signal: Dict) -> str:
        """Create binary options chart"""
        try:
            plt.figure(figsize=(10, 6))
            
            prices = signal['prices']
            analysis = signal['analysis']
            
            # Create x-axis labels
            x = list(range(len(prices)))
            
            plt.plot(x, prices, label='Price', color='blue', linewidth=2)
            plt.axhline(y=analysis['sma_10'], color='orange', linestyle='--', 
                       label=f'SMA 10: {analysis["sma_10"]:.4f}')
            plt.axhline(y=analysis['sma_20'], color='red', linestyle='--', 
                       label=f'SMA 20: {analysis["sma_20"]:.4f}')
            plt.axhline(y=signal['current_price'], color='green', linestyle='-', 
                       linewidth=2, label=f'Current: {signal["current_price"]:.4f}')
            
            market_type = signal.get('market_type', 'forex')
            market_label = "OTC" if market_type == 'otc' else "Forex"
            
            direction_text = "HIGH (CALL)" if signal['direction'] == 'HIGH' else "LOW (PUT)"
            
            plt.title(f'BINARY: {signal["pair"]} - {direction_text} | {signal["expiry_minutes"]}min | Conf: {signal["confidence"]*100:.1f}%')
            plt.legend()
            plt.grid(True, alpha=0.3)
            
            filename = f"/tmp/binary_chart_{int(time.time())}.png"
            plt.savefig(filename, dpi=150, bbox_inches='tight')
            plt.close()
            
            return filename
        except Exception as e:
            logger.error(f"Chart creation error: {e}")
            return "/tmp/chart_error.png"
    
    def run(self):
        """Start the bot"""
        print("🤖 Binary Trading Bot Starting...")
        print(f"🤖 Bot: @{self.config.BOT_USERNAME}")
        print(f"📢 Channel: @{self.config.CHANNEL_USERNAME}")
        print(f"👤 Admin: {self.config.ADMIN_USERNAME}")
        print(f"🔐 Channel Required: {self.config.CHANNEL_REQUIRED}")
        print(f"💎 Premium Enabled: {self.config.PREMIUM_ENABLED}")
        print("=" * 50)
        
        # Use webhook for production (Render) or polling for development
        if 'RENDER' in os.environ:
            # For Render, we'll use polling since it's simpler for bots
            self.application.run_polling()
        else:
            self.application.run_polling()

# Main execution
if __name__ == "__main__":
    try:
        bot = BinaryTradingBot()
        bot.run()
    except Exception as e:
        logger.error(f"Failed to start bot: {e}")
        print(f"❌ Bot startup failed: {e}")