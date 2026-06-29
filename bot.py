import os
import queue
import signal
import sys
import threading
from pathlib import Path
from pyrubi import Client

from const import DEFAULT_CONFIG, CONFIG_FILE, PROGRESS_FILE, GROUPS_FILE, FORWARDED_FILE, STATS_FILE, SECONDARY_COUNTS_FILE
from mixins.storage import StorageMixin
from mixins.sender import SenderMixin
from mixins.joiner import JoinerMixin
from mixins.handler import HandlerMixin

class RubikaJoiner(StorageMixin, SenderMixin, JoinerMixin, HandlerMixin):
    DEFAULT_CONFIG = DEFAULT_CONFIG

    def __init__(self, session_name, admin_user_id, base_dir=None):
        self.session_name = session_name
        self.admin_user_id = admin_user_id
        if base_dir is None:
            base_dir = os.getcwd()
        self.base_dir = Path(base_dir) / session_name
        self.base_dir.mkdir(parents=True, exist_ok=True)

        self.config_path = self.base_dir / CONFIG_FILE
        self.progress_path = self.base_dir / PROGRESS_FILE
        self.groups_path = self.base_dir / GROUPS_FILE
        self.forwarded_path = self.base_dir / FORWARDED_FILE
        self.stats_path = self.base_dir / STATS_FILE
        self.secondary_counts_path = self.base_dir / SECONDARY_COUNTS_FILE

        self.bot = Client(session=session_name)
        self.running = False
        self.status_msg_id = None
        self.status_chat = None
        self.lock = threading.Lock()

        self.config = self._load_config()
        self.join_links = []
        self.current_index = 0
        self.stop_join = False
        self.join_thread = None

        self.stats = {'joined': 0, 'skipped': 0, 'failed': 0, 'processed': 0, 'total': 0}

        self.forwarded_users = self._load_forwarded_users()
        self.secondary_counts = self._load_secondary_counts()
        self.total_messages_received = 0
        self.total_forwarded_success = 0
        self._load_stats()

        self.groups = self._load_groups()
        self.active_groups = []

        self.send_queue = queue.Queue()
        self.send_thread = None
        self.send_running = False
        self._start_sender()

        self.continue_event = threading.Event()
        self.airplane_waiting = False

        @self.bot.on_message()
        def handle(m):
            self._handle_message(m)

    def _edit_status(self, text):
        if self.status_msg_id and self.status_chat:
            try:
                self.bot.methods.editMessage(objectGuid=self.status_chat, messageId=self.status_msg_id, text=text)
            except:
                pass

    def update_status_message(self, final=False):
        if not self.status_msg_id or not self.status_chat:
            return
        stats = self.stats
        total = stats['total']
        processed = stats['processed']
        percent = (processed / total * 100) if total > 0 else 0
        text = f"📊 پیشرفت جوین\n➖➖➖➖➖➖➖➖➖➖\n📌 کل: {total}\n🔄 پردازش: {processed} ({percent:.1f}%)\n✅ عضو: {stats['joined']}\n⏭️ رد: {stats['skipped']}\n❌ خطا: {stats['failed']}"
        if final:
            text += "\n\n🏁 تمام شد!"
        else:
            text += "\n\n⏳ در حال اجرا..."
        self._edit_status(text)

    def _format_join_stats(self):
        s = self.stats
        return f"📊 گزارش نهایی\n➖➖➖➖➖➖➖➖➖➖\n🔍 بررسی: {s['processed']}\n✅ عضو: {s['joined']}\n⏭️ رد: {s['skipped']}\n❌ خطا: {s['failed']}"

    def _process_admin_command(self, chat_guid, command_text):
        parts = command_text.strip().split()
        if not parts:
            return
        main = parts[0]

        if main == "ادامه":
            if self.airplane_waiting:
                self.continue_event.set()
                self.bot.send_text(object_guid=chat_guid, text="✅ ادامه یافت")
            else:
                self.bot.send_text(object_guid=chat_guid, text="⏳ در حالت توقف نیست")
            return

        if main == "شروع":
            if self.running:
                self.bot.send_text(object_guid=chat_guid, text="🌀 در حال اجراست")
                return
            self.start_joining(chat_guid)
            return

        if main == "توقف":
            self.stop_joining(chat_guid)
            return

        if main == "وضعیت":
            self._send_status(chat_guid)
            return

        if main == "امار":
            if len(parts) > 1 and parts[1] == "گروه":
                self._send_group_stats(chat_guid)
            else:
                self._send_user_stats(chat_guid)
            return

        if main == "لیست":
            if len(parts) > 1 and parts[1] == "گروه":
                self._list_groups(chat_guid)
            else:
                self.bot.send_text(object_guid=chat_guid, text="❌ مثال: لیست گروه")
            return

        if main == "لف":
            if len(parts) < 2:
                self.bot.send_text(object_guid=chat_guid, text="❌ شماره گروه مثال: لف 1")
                return
            try:
                index = int(parts[1]) - 1
                if index < 0 or index >= len(self.active_groups):
                    self.bot.send_text(object_guid=chat_guid, text="❌ شماره اشتباه")
                    return
                guid = self.active_groups[index]
                try:
                    self.bot.leave_chat(object_guid=guid)
                    self._remove_group_from_lists(guid)
                    self.bot.send_text(object_guid=chat_guid, text=f"✅ خروج از گروه {index+1}")
                except Exception as e:
                    self.bot.send_text(object_guid=chat_guid, text=f"❌ خطا: {str(e)}")
            except ValueError:
                self.bot.send_text(object_guid=chat_guid, text="❌ فقط عدد")
            return

        if main == "راهنما":
            self.bot.send_text(object_guid=chat_guid, text=self._get_help_text())
            return

        if main == "تنظیم":
            if len(parts) < 3:
                self.bot.send_text(object_guid=chat_guid, text="❌ دستور ناقص")
                return
            sub = parts[1]
            try:
                if sub == "تاخیر":
                    val = float(parts[2])
                    self.config["DELAY_BETWEEN_JOINS"] = val
                    self._save_config()
                    self.bot.send_text(object_guid=chat_guid, text=f"✅ تاخیر {val}s")
                elif sub == "تعداد" and len(parts) >= 4 and parts[2] == "دسته":
                    val = int(parts[3])
                    self.config["BATCH_SIZE"] = val
                    self._save_config()
                    self.bot.send_text(object_guid=chat_guid, text=f"✅ دسته {val}")
                elif sub == "زمان" and len(parts) >= 4 and parts[2] == "سرد":
                    val = int(parts[3])
                    self.config["COOLDOWN_MINUTES"] = val
                    self._save_config()
                    self.bot.send_text(object_guid=chat_guid, text=f"✅ سرد {val} دقیقه")
                elif sub == "فاصله" and len(parts) >= 4 and parts[2] == "ارسال":
                    val = float(parts[3])
                    self.config["SEND_INTERVAL"] = val
                    self._save_config()
                    self.bot.send_text(object_guid=chat_guid, text=f"✅ فاصله {val}s")
                elif sub == "حداقل" and len(parts) >= 4 and parts[2] == "ممبر":
                    val = int(parts[3])
                    self.config["MIN_MEMBERS"] = val
                    self._save_config()
                    self.bot.send_text(object_guid=chat_guid, text=f"✅ حداقل {val}")
                elif sub == "متن":
                    new_text = ' '.join(parts[2:])
                    if new_text:
                        self.config["GROUP_TEXT_POOL"] = [new_text]
                        self.config["TEXT_TO_SEND"] = new_text
                        self._save_config()
                        self.bot.send_text(object_guid=chat_guid, text=f"✅ متن گروه: {new_text}")
                    else:
                        self.bot.send_text(object_guid=chat_guid, text="❌ متن خالی")
                elif sub == "هواپیما":
                    val = parts[2].lower()
                    if val in ("on", "true", "1", "yes"):
                        self.config["AIRPLANE_MODE_PROMPT"] = True
                        self._save_config()
                        self.bot.send_text(object_guid=chat_guid, text="✈️ فعال")
                    elif val in ("off", "false", "0", "no"):
                        self.config["AIRPLANE_MODE_PROMPT"] = False
                        self._save_config()
                        self.bot.send_text(object_guid=chat_guid, text="❌ غیرفعال")
                    else:
                        self.bot.send_text(object_guid=chat_guid, text="❌ on/off")
                elif sub == "پاسخ":
                    val = parts[2].lower()
                    if val in ("on", "true", "1", "yes"):
                        self.config["SECONDARY_REPLY_ENABLED"] = True
                        self._save_config()
                        self.bot.send_text(object_guid=chat_guid, text="✅ پاسخ ثانویه فعال")
                    elif val in ("off", "false", "0", "no"):
                        self.config["SECONDARY_REPLY_ENABLED"] = False
                        self._save_config()
                        self.bot.send_text(object_guid=chat_guid, text="❌ پاسخ ثانویه غیرفعال")
                    else:
                        self.bot.send_text(object_guid=chat_guid, text="❌ on/off")
                elif sub == "متن‌پاسخ":
                    new_text = ' '.join(parts[2:])
                    if new_text:
                        self.config["SECONDARY_REPLY_TEXTS"] = [new_text]
                        self.config["SECONDARY_REPLY_TEXT"] = new_text
                        self._save_config()
                        self.bot.send_text(object_guid=chat_guid, text=f"✅ متن پاسخ: {new_text}")
                    else:
                        self.bot.send_text(object_guid=chat_guid, text="❌ متن خالی")
                elif sub == "محدودیت" and len(parts) >= 4 and parts[2] == "پاسخ":
                    val = int(parts[3])
                    if val < 0:
                        self.bot.send_text(object_guid=chat_guid, text="❌ مثبت باشد")
                    else:
                        self.config["SECONDARY_REPLY_LIMIT"] = val
                        self._save_config()
                        self.bot.send_text(object_guid=chat_guid, text=f"✅ محدودیت {val}")
                else:
                    self.bot.send_text(object_guid=chat_guid, text="❌ دستور نامشخص")
            except ValueError:
                self.bot.send_text(object_guid=chat_guid, text="❌ عدد وارد کن")
            except Exception as e:
                self.bot.send_text(object_guid=chat_guid, text=f"❌ خطا: {e}")
            return

        self.bot.send_text(object_guid=chat_guid, text=self._get_help_text())

    def _send_status(self, admin_guid):
        status = "🟢 در حال کار" if self.running else "🔴 خاموش"
        progress = f"{self.stats['processed']} از {self.stats['total']}" if self.stats.get('total', 0) > 0 else "شروع نشده"
        queue_size = self.send_queue.qsize()
        text = (
            f"📊 وضعیت\n"
            f"➖➖➖➖➖➖➖➖➖➖\n"
            f"🔹 جوین: {status}\n"
            f"📈 پیشرفت: {progress}\n"
            f"👥 گروه‌ها: {len(self.groups)}\n\n"
            f"⚙️ تنظیمات\n"
            f"🕒 تاخیر: {self.config['DELAY_BETWEEN_JOINS']}s\n"
            f"📦 دسته: {self.config['BATCH_SIZE']}\n"
            f"⏳ سرد: {self.config['COOLDOWN_MINUTES']}m\n"
            f"📨 فاصله: {self.config['SEND_INTERVAL']}s\n"
            f"👥 حداقل: {self.config['MIN_MEMBERS']}\n"
            f"✈️ هواپیما: {'✅' if self.config['AIRPLANE_MODE_PROMPT'] else '❌'}\n"
            f"💬 پاسخ ثانویه: {'✅' if self.config.get('SECONDARY_REPLY_ENABLED', True) else '❌'}\n"
            f"🔢 محدودیت: {self.config.get('SECONDARY_REPLY_LIMIT', 1)}\n"
            f"📊 صف: {queue_size} گروه"
        )
        self.bot.send_text(object_guid=admin_guid, text=text)

    def _send_user_stats(self, admin_guid):
        total_users = len(self.forwarded_users)
        returned = self.total_messages_received - self.total_forwarded_success
        return_percent = (returned / self.total_messages_received * 100) if self.total_messages_received > 0 else 0
        text = (
            f"📈 آمار پی‌وی\n"
            f"➖➖➖➖➖➖➖➖➖➖\n"
            f"👥 کاربران: {total_users}\n"
            f"📥 دریافت: {self.total_messages_received}\n"
            f"📤 ارسال موفق: {self.total_forwarded_success}\n"
            f"🔄 تکراری: {returned} ({return_percent:.1f}%)"
        )
        self.bot.send_text(object_guid=admin_guid, text=text)

    def _send_group_stats(self, admin_guid):
        if not self.groups:
            self.bot.send_text(object_guid=admin_guid, text="📭 گروهی ثبت نشده")
            return

        now = datetime.now()
        total = len(self.groups)
        cooldown_ok = 0
        cooldown_wait = 0
        for guid, info in self.groups.items():
            diff = now - info['last_send']
            minutes = int(diff.total_seconds() // 60)
            if minutes >= self.config["COOLDOWN_MINUTES"]:
                cooldown_ok += 1
            else:
                cooldown_wait += 1

        ok_percent = (cooldown_ok / total * 100) if total > 0 else 0
        wait_percent = (cooldown_wait / total * 100) if total > 0 else 0

        lines = [
            f"📊 آمار گروه‌ها (کل: {total})",
            "➖➖➖➖➖➖➖➖➖➖",
            f"✅ آماده: {cooldown_ok} ({ok_percent:.1f}%)",
            f"⏳ استراحت: {cooldown_wait} ({wait_percent:.1f}%)",
            "📋 ۱۰ گروه فعال"
        ]

        for i, guid in enumerate(self.active_groups[-10:], 1):
            info = self.groups.get(guid)
            if not info:
                continue
            title = info.get('title', 'ناشناس')
            diff = now - info['last_send']
            minutes = int(diff.total_seconds() // 60)
            if minutes >= self.config["COOLDOWN_MINUTES"]:
                status = "✅ آماده"
            else:
                remaining = self.config["COOLDOWN_MINUTES"] - minutes
                status = f"⏳ {remaining}m"
            lines.append(f"{i} ➖ {title} 👈 {status}")

        if total > 10:
            lines.append(f"\n... و {total - 10} گروه دیگر")

        self.bot.send_text(object_guid=admin_guid, text="\n".join(lines))

    def _list_groups(self, admin_guid):
        if not self.active_groups:
            self.bot.send_text(object_guid=admin_guid, text="📭 گروهی پیدا نشد")
            return

        lines = ["📋 ۱۰ گروه اخیر", "➖➖➖➖➖➖➖➖➖➖"]
        for i, guid in enumerate(self.active_groups, 1):
            title = self.groups.get(guid, {}).get('title', 'ناشناس')
            lines.append(f"{i} ➖ {title}")
        self.bot.send_text(object_guid=admin_guid, text="\n".join(lines))

    def _get_help_text(self):
        return (
            "🤖 راهنما\n"
            "➖➖➖➖➖➖➖➖➖➖\n"
            "▶️ شروع\n"
            "⏹️ توقف\n"
            "📊 وضعیت\n"
            "📈 امار\n"
            "📈 امار گروه\n"
            "📋 لیست گروه\n"
            "🚪 لف [شماره]\n\n"
            "⚙️ تنظیمات\n"
            "🕒 تنظیم تاخیر [عدد]\n"
            "📦 تنظیم تعداد دسته [عدد]\n"
            "⏳ تنظیم زمان سرد [عدد]\n"
            "📨 تنظیم فاصله ارسال [عدد]\n"
            "👥 تنظیم حداقل ممبر [عدد]\n"
            "✈️ تنظیم هواپیما [on/off]\n"
            "📝 تنظیم متن [متن]\n\n"
            "💬 پی‌وی\n"
            "✅ تنظیم پاسخ [on/off]\n"
            "📝 تنظیم متن‌پاسخ [متن]\n"
            "🔢 تنظیم محدودیت پاسخ [عدد]\n"
        )

    def run(self):
        def signal_handler(sig, frame):
            self.send_running = False
            sys.exit(0)

        if threading.current_thread() is threading.main_thread():
            signal.signal(signal.SIGINT, signal_handler)

        while True:
            try:
                self.bot.run()
                self.bot.send_text(object_guid=self.admin_user_id, text="🟢 آماده")
            except:
                time.sleep(5)
                continue
            else:
                break