import logging
import json
import uuid
import sqlite3
from typing import Dict, List, Optional
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Document
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
import asyncio
import os
from dotenv import load_dotenv
from datetime import datetime

# بارگذاری متغیرهای محیطی
load_dotenv()

# تنظیمات لاگ
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

def load_config():
    """بارگذاری تنظیمات از متغیرهای محیطی"""
    # بارگذاری از متغیرهای محیطی
    bot_token = os.getenv('BOT_TOKEN')
    bot_username = os.getenv('BOT_USERNAME')
    admin_ids_str = os.getenv('ADMIN_IDS')
    
    # پردازش آیدی ادمین‌ها از متغیر محیطی
    admin_ids = []
    if admin_ids_str:
        try:
            # پشتیبانی از فرمت‌های مختلف: "123456789,987654321" یا "123456789 987654321"
            admin_ids_str = admin_ids_str.replace(' ', ',')
            admin_ids = [int(id.strip()) for id in admin_ids_str.split(',') if id.strip()]
        except ValueError as e:
            logger.error(f"خطا در پردازش آیدی ادمین‌ها: {e}")
    
    # اگر متغیر محیطی موجود نبود، از فایل کانفیگ بخوان (برای اجرای محلی)
    if not admin_ids:
        try:
            if os.path.exists('config.json'):
                with open('config.json', 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    admin_ids = config.get('admin_ids', [])
            else:
                # ایجاد فایل کانفیگ نمونه برای اجرای محلی
                sample_config = {
                    "admin_ids": [123456789],
                    "note": "آیدی عددی ادمین‌ها را در این لیست قرار دهید یا در متغیر محیطی ADMIN_IDS تعریف کنید"
                }
                with open('config.json', 'w', encoding='utf-8') as f:
                    json.dump(sample_config, f, ensure_ascii=False, indent=2)
                print("⚠️ فایل config.json ایجاد شد. لطفاً آیدی ادمین‌ها را در آن وارد کنید یا متغیر محیطی ADMIN_IDS را تعریف کنید.")
        except Exception as e:
            logger.error(f"خطا در بارگذاری فایل کانفیگ: {e}")
    
    # بررسی وجود تنظیمات ضروری
    if not bot_token:
        raise ValueError("❌ BOT_TOKEN در متغیرهای محیطی یافت نشد!")
    
    if not bot_username:
        raise ValueError("❌ BOT_USERNAME در متغیرهای محیطی یافت نشد!")
    
    if not admin_ids:
        raise ValueError("❌ آیدی ادمین‌ها در متغیر محیطی ADMIN_IDS یا فایل config.json یافت نشد!")
    
    return bot_token, bot_username, admin_ids

# بارگذاری تنظیمات
try:
    BOT_TOKEN, BOT_USERNAME, ADMIN_IDS = load_config()
except ValueError as e:
    print(f"خطای تنظیمات: {e}")
    exit(1)

class DatabaseManager:
    """مدیریت دیتابیس SQLite"""
    
    def __init__(self, db_path: str = None):
        # اگر مسیر مشخص نشده، سعی کن از پوشه data استفاده کن (برای Railway Volume)
        if db_path is None:
            # بررسی وجود پوشه data (Railway Volume)
            if os.path.exists('/app/data'):
                self.db_path = '/app/data/bot_database.db'
            else:
                # ایجاد پوشه data اگر وجود ندارد
                os.makedirs('data', exist_ok=True)
                self.db_path = 'data/bot_database.db'
        else:
            self.db_path = db_path
        
        self.init_database()
    
    def init_database(self):
        """ایجاد جداول دیتابیس"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # جدول دسته‌ها
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS categories (
                        id TEXT PRIMARY KEY,
                        name TEXT NOT NULL,
                        created_by INTEGER NOT NULL,
                        created_at TEXT NOT NULL
                    )
                ''')
                
                # جدول فایل‌ها
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS files (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        category_id TEXT NOT NULL,
                        file_id TEXT NOT NULL,
                        file_name TEXT NOT NULL,
                        file_size INTEGER NOT NULL,
                        caption TEXT,
                        upload_date TEXT NOT NULL,
                        FOREIGN KEY (category_id) REFERENCES categories (id) ON DELETE CASCADE
                    )
                ''')
                
                conn.commit()
                logger.info(f"دیتابیس در مسیر {self.db_path} آماده شد")
                
        except Exception as e:
            logger.error(f"خطا در ایجاد دیتابیس: {e}")
            raise
    
    def add_category(self, category_id: str, name: str, created_by: int) -> bool:
        """اضافه کردن دسته جدید"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO categories (id, name, created_by, created_at)
                    VALUES (?, ?, ?, ?)
                ''', (category_id, name, created_by, datetime.now().isoformat()))
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"خطا در اضافه کردن دسته: {e}")
            return False
    
    def get_categories(self) -> Dict[str, Dict]:
        """دریافت تمام دسته‌ها"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT * FROM categories')
                categories_data = cursor.fetchall()
                
                categories = {}
                for cat_data in categories_data:
                    cat_id, name, created_by, created_at = cat_data
                    
                    # دریافت فایل‌های هر دسته
                    cursor.execute('''
                        SELECT file_id, file_name, file_size, caption 
                        FROM files WHERE category_id = ?
                    ''', (cat_id,))
                    files_data = cursor.fetchall()
                    
                    files = []
                    for file_data in files_data:
                        files.append({
                            'file_id': file_data[0],
                            'file_name': file_data[1],
                            'file_size': file_data[2],
                            'caption': file_data[3] or ''
                        })
                    
                    categories[cat_id] = {
                        'name': name,
                        'files': files,
                        'created_by': created_by,
                        'created_at': created_at
                    }
                
                return categories
        except Exception as e:
            logger.error(f"خطا در دریافت دسته‌ها: {e}")
            return {}
    
    def get_category(self, category_id: str) -> Optional[Dict]:
        """دریافت یک دسته خاص"""
        categories = self.get_categories()
        return categories.get(category_id)
    
    def add_file_to_category(self, category_id: str, file_info: Dict) -> bool:
        """اضافه کردن فایل به دسته"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO files (category_id, file_id, file_name, file_size, caption, upload_date)
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', (
                    category_id,
                    file_info['file_id'],
                    file_info['file_name'],
                    file_info['file_size'],
                    file_info.get('caption', ''),
                    datetime.now().isoformat()
                ))
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"خطا در اضافه کردن فایل: {e}")
            return False
    
    def add_files_to_category(self, category_id: str, files: List[Dict]) -> bool:
        """اضافه کردن چندین فایل به دسته"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                upload_date = datetime.now().isoformat()
                
                for file_info in files:
                    cursor.execute('''
                        INSERT INTO files (category_id, file_id, file_name, file_size, caption, upload_date)
                        VALUES (?, ?, ?, ?, ?, ?)
                    ''', (
                        category_id,
                        file_info['file_id'],
                        file_info['file_name'],
                        file_info['file_size'],
                        file_info.get('caption', ''),
                        upload_date
                    ))
                
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"خطا در اضافه کردن فایل‌ها: {e}")
            return False
    
    def delete_file(self, category_id: str, file_index: int) -> bool:
        """حذف فایل از دسته"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # دریافت فایل‌های دسته
                cursor.execute('''
                    SELECT id FROM files WHERE category_id = ? ORDER BY id
                ''', (category_id,))
                file_ids = cursor.fetchall()
                
                if file_index >= len(file_ids):
                    return False
                
                file_id = file_ids[file_index][0]
                cursor.execute('DELETE FROM files WHERE id = ?', (file_id,))
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"خطا در حذف فایل: {e}")
            return False
    
    def delete_category(self, category_id: str) -> bool:
        """حذف دسته"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # حذف فایل‌ها
                cursor.execute('DELETE FROM files WHERE category_id = ?', (category_id,))
                
                # حذف دسته
                cursor.execute('DELETE FROM categories WHERE id = ?', (category_id,))
                
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"خطا در حذف دسته: {e}")
            return False

class FileManagerBot:
    def __init__(self):
        # ایجاد مدیریت دیتابیس
        self.db = DatabaseManager()
        
        # ذخیره فایل‌های در حال آپلود (در حافظه)
        self.pending_uploads: Dict[int, Dict] = {}
    
    def is_admin(self, user_id: int) -> bool:
        """بررسی ادمین بودن کاربر"""
        return user_id in ADMIN_IDS
    
    def generate_category_link(self, category_id: str) -> str:
        """تولید لینک برای دسته"""
        return f"https://t.me/{BOT_USERNAME}?start=cat_{category_id}"

# ایجاد نمونه از کلاس
bot_manager = FileManagerBot()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """کمند شروع"""
    user_id = update.effective_user.id
    
    # بررسی اینکه آیا از طریق لینک دسته آمده
    if context.args and context.args[0].startswith('cat_'):
        category_id = context.args[0][4:]  # حذف پیشوند cat_
        await handle_category_access(update, context, category_id)
        return
    
    if bot_manager.is_admin(user_id):
        await update.message.reply_text(
            "سلام ادمین عزیز! 👋\n\n"
            "برای ایجاد دسته جدید، از دستور /new_category استفاده کنید.\n"
            "برای مشاهده دسته‌های موجود، از دستور /categories استفاده کنید."
        )
    else:
        await update.message.reply_text(
            "سلام! 👋\n\n"
            "این ربات برای مدیریت فایل‌ها توسط ادمین‌ها طراحی شده است.\n"
            "اگر لینک خاصی دارید، روی آن کلیک کنید تا فایل‌ها را دریافت کنید."
        )

async def handle_category_access(update: Update, context: ContextTypes.DEFAULT_TYPE, category_id: str):
    """مدیریت دسترسی به دسته"""
    user_id = update.effective_user.id
    
    category = bot_manager.db.get_category(category_id)
    if not category:
        await update.message.reply_text("❌ دسته مورد نظر یافت نشد!")
        return
    
    if bot_manager.is_admin(user_id):
        # ادمین - نمایش گزینه‌های مدیریت
        keyboard = [
            [InlineKeyboardButton("📁 مشاهده فایل‌ها", callback_data=f"view_{category_id}")],
            [InlineKeyboardButton("➕ اضافه کردن فایل", callback_data=f"add_{category_id}")],
            [InlineKeyboardButton("🗑 حذف فایل", callback_data=f"delete_file_{category_id}")],
            [InlineKeyboardButton("❌ حذف کل دسته", callback_data=f"delete_cat_{category_id}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            f"شما ادمین هستید! 👨‍💼\n\n"
            f"دسته: {category['name']}\n"
            f"تعداد فایل‌ها: {len(category['files'])}\n\n"
            f"آیا می‌خواهید فایل‌ها را ببینید یا قابلیت‌های ادیت دسته برایتان فعال شود؟",
            reply_markup=reply_markup
        )
    else:
        # کاربر عادی - ارسال فایل‌ها
        if not category['files']:
            await update.message.reply_text("این دسته فایلی ندارد! 📂")
            return
        
        await update.message.reply_text(f"در حال ارسال فایل‌های دسته '{category['name']}'... 📤")
        
        for file_info in category['files']:
            try:
                await context.bot.send_document(
                    chat_id=update.effective_chat.id,
                    document=file_info['file_id'],
                    caption=file_info.get('caption', '')
                )
                await asyncio.sleep(0.5)  # تاخیر کوتاه بین ارسال فایل‌ها
            except Exception as e:
                logger.error(f"خطا در ارسال فایل: {e}")

async def new_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ایجاد دسته جدید"""
    user_id = update.effective_user.id
    
    if not bot_manager.is_admin(user_id):
        await update.message.reply_text("❌ شما مجاز به انجام این عمل نیستید!")
        return
    
    if len(context.args) == 0:
        await update.message.reply_text(
            "لطفاً نام دسته را مشخص کنید.\n"
            "مثال: /new_category نام_دسته"
        )
        return
    
    category_name = ' '.join(context.args)
    category_id = str(uuid.uuid4())[:8]
    
    success = bot_manager.db.add_category(category_id, category_name, user_id)
    
    if success:
        link = bot_manager.generate_category_link(category_id)
        
        await update.message.reply_text(
            f"✅ دسته '{category_name}' با موفقیت ایجاد شد!\n\n"
            f"🔗 لینک دسته:\n{link}\n\n"
            f"حالا فایل‌های خود را برای این دسته ارسال کنید.\n"
            f"برای شروع آپلود فایل‌ها، از دستور زیر استفاده کنید:\n"
            f"/upload {category_id}"
        )
    else:
        await update.message.reply_text("❌ خطا در ایجاد دسته!")

async def upload_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """شروع آپلود فایل‌ها برای دسته"""
    user_id = update.effective_user.id
    
    if not bot_manager.is_admin(user_id):
        await update.message.reply_text("❌ شما مجاز به انجام این عمل نیستید!")
        return
    
    if len(context.args) == 0:
        await update.message.reply_text(
            "لطفاً آیدی دسته را مشخص کنید.\n"
            "مثال: /upload category_id"
        )
        return
    
    category_id = context.args[0]
    
    category = bot_manager.db.get_category(category_id)
    if not category:
        await update.message.reply_text("❌ دسته مورد نظر یافت نشد!")
        return
    
    bot_manager.pending_uploads[user_id] = {
        'category_id': category_id,
        'files': []
    }
    
    await update.message.reply_text(
        f"📤 حالت آپلود فایل برای دسته '{category['name']}' فعال شد!\n\n"
        f"فایل‌های خود را ارسال کنید.\n"
        f"برای پایان آپلود، از دستور /finish_upload استفاده کنید."
    )

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """مدیریت دریافت فایل‌ها"""
    user_id = update.effective_user.id
    
    if user_id not in bot_manager.pending_uploads:
        return
    
    upload_info = bot_manager.pending_uploads[user_id]
    document = update.message.document
    
    file_info = {
        'file_id': document.file_id,
        'file_name': document.file_name,
        'file_size': document.file_size,
        'caption': update.message.caption or ''
    }
    
    upload_info['files'].append(file_info)
    
    await update.message.reply_text(
        f"✅ فایل '{document.file_name}' دریافت شد!\n"
        f"تعداد فایل‌های دریافت شده: {len(upload_info['files'])}"
    )

async def finish_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """پایان آپلود فایل‌ها"""
    user_id = update.effective_user.id
    
    if user_id not in bot_manager.pending_uploads:
        await update.message.reply_text("❌ هیچ آپلودی در حال انجام نیست!")
        return
    
    upload_info = bot_manager.pending_uploads[user_id]
    category_id = upload_info['category_id']
    
    if not upload_info['files']:
        await update.message.reply_text("❌ هیچ فایلی آپلود نشده است!")
        return
    
    # اضافه کردن فایل‌ها به دسته در دیتابیس
    success = bot_manager.db.add_files_to_category(category_id, upload_info['files'])
    
    if success:
        # پاک کردن اطلاعات آپلود
        del bot_manager.pending_uploads[user_id]
        
        link = bot_manager.generate_category_link(category_id)
        
        await update.message.reply_text(
            f"✅ {len(upload_info['files'])} فایل با موفقیت به دسته اضافه شد!\n\n"
            f"🔗 لینک دسته:\n{link}"
        )
    else:
        await update.message.reply_text("❌ خطا در ذخیره فایل‌ها!")

async def categories_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """نمایش لیست دسته‌ها"""
    user_id = update.effective_user.id
    
    if not bot_manager.is_admin(user_id):
        await update.message.reply_text("❌ شما مجاز به انجام این عمل نیستید!")
        return
    
    categories = bot_manager.db.get_categories()
    
    if not categories:
        await update.message.reply_text("📂 هیچ دسته‌ای وجود ندارد!")
        return
    
    message = "📁 لیست دسته‌ها:\n\n"
    for cat_id, cat_info in categories.items():
        link = bot_manager.generate_category_link(cat_id)
        message += f"• {cat_info['name']}\n"
        message += f"  فایل‌ها: {len(cat_info['files'])}\n"
        message += f"  لینک: {link}\n\n"
    
    await update.message.reply_text(message)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """مدیریت دکمه‌های inline"""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    data = query.data
    
    if not bot_manager.is_admin(user_id):
        await query.edit_message_text("❌ شما مجاز به انجام این عمل نیستید!")
        return
    
    if data.startswith('view_'):
        category_id = data[5:]
        await view_category_files(query, category_id)
    
    elif data.startswith('add_'):
        category_id = data[4:]
        await start_adding_files(query, category_id, user_id)
    
    elif data.startswith('delete_file_'):
        category_id = data[12:]
        await show_files_for_deletion(query, category_id)
    
    elif data.startswith('delete_cat_'):
        category_id = data[11:]
        await confirm_category_deletion(query, category_id)
    
    elif data.startswith('confirm_del_cat_'):
        category_id = data[16:]
        await delete_category(query, category_id)
    
    elif data.startswith('del_file_'):
        parts = data[9:].split('_', 1)
        category_id, file_index = parts[0], int(parts[1])
        await delete_file_from_category(query, category_id, file_index)

async def view_category_files(query, category_id: str):
    """نمایش فایل‌های دسته"""
    category = bot_manager.db.get_category(category_id)
    if not category:
        await query.edit_message_text("❌ دسته یافت نشد!")
        return
    
    if not category['files']:
        await query.edit_message_text("📂 این دسته فایلی ندارد!")
        return
    
    await query.edit_message_text("📤 در حال ارسال فایل‌ها...")
    
    for file_info in category['files']:
        try:
            await query.bot.send_document(
                chat_id=query.message.chat_id,
                document=file_info['file_id'],
                caption=file_info.get('caption', '')
            )
            await asyncio.sleep(0.5)
        except Exception as e:
            logger.error(f"خطا در ارسال فایل: {e}")

async def start_adding_files(query, category_id: str, user_id: int):
    """شروع اضافه کردن فایل‌ها"""
    bot_manager.pending_uploads[user_id] = {
        'category_id': category_id,
        'files': []
    }
    
    await query.edit_message_text(
        f"📤 حالت اضافه کردن فایل فعال شد!\n\n"
        f"فایل‌های جدید خود را ارسال کنید.\n"
        f"برای پایان، از /finish_upload استفاده کنید."
    )

async def show_files_for_deletion(query, category_id: str):
    """نمایش فایل‌ها برای حذف"""
    category = bot_manager.db.get_category(category_id)
    if not category:
        await query.edit_message_text("❌ دسته یافت نشد!")
        return
    
    if not category['files']:
        await query.edit_message_text("📂 این دسته فایلی ندارد!")
        return
    
    keyboard = []
    for i, file_info in enumerate(category['files']):
        keyboard.append([InlineKeyboardButton(
            f"🗑 {file_info['file_name']}", 
            callback_data=f"del_file_{category_id}_{i}"
        )])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(
        "کدام فایل را می‌خواهید حذف کنید؟",
        reply_markup=reply_markup
    )

async def delete_file_from_category(query, category_id: str, file_index: int):
    """حذف فایل از دسته"""
    category = bot_manager.db.get_category(category_id)
    if not category:
        await query.edit_message_text("❌ دسته یافت نشد!")
        return
    
    if file_index >= len(category['files']):
        await query.edit_message_text("❌ فایل یافت نشد!")
        return
    
    deleted_file_name = category['files'][file_index]['file_name']
    
    success = bot_manager.db.delete_file(category_id, file_index)
    
    if success:
        await query.edit_message_text(
            f"✅ فایل '{deleted_file_name}' با موفقیت حذف شد!"
        )
    else:
        await query.edit_message_text("❌ خطا در حذف فایل!")

async def confirm_category_deletion(query, category_id: str):
    """تأیید حذف دسته"""
    keyboard = [
        [InlineKeyboardButton("✅ بله، حذف شود", callback_data=f"confirm_del_cat_{category_id}")],
        [InlineKeyboardButton("❌ انصراف", callback_data="cancel")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        "آیا مطمئن هستید که می‌خواهید این دسته را حذف کنید؟\n"
        "⚠️ این عمل قابل بازگشت نیست!",
        reply_markup=reply_markup
    )

async def delete_category(query, category_id: str):
    """حذف دسته"""
    category = bot_manager.db.get_category(category_id)
    if not category:
        await query.edit_message_text("❌ دسته یافت نشد!")
        return
    
    category_name = category['name']
    success = bot_manager.db.delete_category(category_id)
    
    if success:
        await query.edit_message_text(
            f"✅ دسته '{category_name}' با موفقیت حذف شد!"
        )
    else:
        await query.edit_message_text("❌ خطا در حذف دسته!")

def main():
    """اجرای ربات"""
    # ایجاد اپلیکیشن
    application = Application.builder().token(BOT_TOKEN).build()
    
    # اضافه کردن هندلرها
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("new_category", new_category))
    application.add_handler(CommandHandler("upload", upload_command))
    application.add_handler(CommandHandler("finish_upload", finish_upload))
    application.add_handler(CommandHandler("categories", categories_list))
    application.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    application.add_handler(CallbackQueryHandler(button_handler))
    
    # اجرای ربات
    print("ربات در حال اجرا...")
    application.run_polling()

if __name__ == '__main__':
    main()