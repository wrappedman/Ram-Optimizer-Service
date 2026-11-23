# RAM Optimizer Service — سرویس ویندوز آزادسازی هوشمند حافظه

🇬🇧 **English documentation: [README.en.md](README.en.md)**

یک سرویس ویندوز (پایتون) که **فقط وقتی حافظه واقعاً کم است** دو کار انجام می‌دهد:

1. **`EmptyWorkingSet`** روی پروسه‌های واجد شرایط → رمی که برنامه‌ها گرفته‌اند و
   دیگر استفاده نمی‌کنند آزاد می‌شود.
2. **خالی کردن Standby List** (معادل «Empty Standby List» در RAMMap مایکروسافت) —
   اما **فقط اگر بعد از مرحله‌ی اول هنوز کمبود باشد**.

> **نکته‌ی صادقانه (مهم):** ویندوز جدید حافظه را خوب مدیریت می‌کند و «رم خالی
> زیاد» به‌خودی‌خود سرعت بیشتری نمی‌دهد؛ بخش زیادی از آن چیزی که Task Manager
> به‌عنوان «استفاده‌شده» نشان می‌دهد در واقع **کش (Standby List)** است که سیستم
> عمداً نگه می‌دارد. به همین دلیل این ابزار:
> - با معیار واقعی فشار حافظه تصمیم می‌گیرد (نه فقط یک درصد خام)،
> - کش را تا وقتی لازم نشده خالی نمی‌کند،
> - و اعداد گزارش‌شده‌اش واقعی هستند، نه تبلیغاتی.

نسخه‌ی فعلی: **2.0.0** (فهرست تغییرات: [CHANGELOG.md](CHANGELOG.md) — بازبینی کد:
[docs/CODE_REVIEW_fa.md](docs/CODE_REVIEW_fa.md))

---

## فهرست

- [چه چیزی تغییر کرد نسبت به نسخه‌ی ۱](#چه-چیزی-تغییر-کرد)
- [نصب سریع (exe)](#نصب-سریع-exe)
- [نصب با نصب‌کننده](#نصب-با-نصب‌کننده-recommended)
- [اجرا بدون نصب سرویس](#اجرا-بدون-نصب-سرویس)
- [پیکربندی](#پیکربندی)
- [خط فرمان](#خط-فرمان)
- [پایش و لاگ](#پایش-و-لاگ)
- [نصب از سورس / توسعه](#نصب-از-سورس--توسعه)
- [عیب‌یابی](#عیب-یابی)
- [سؤالات متداول](#سؤالات-متداول)

---

## چه چیزی تغییر کرد

نسخه‌ی ۱ برای هر کسی که آستانه را جدی می‌گرفت، سه مشکل اساسی داشت: آستانه در کد
۵۵٪ بود ولی در مستندات ۷۵٪، معیار «مصرف» کش ویندوز را هم حساب می‌کرد، و
پاک‌سازی هر ۶۰ ثانیه بدون هیچ محدودیتی تکرار می‌شد. خلاصه‌ی تغییرات:

| موضوع | نسخه ۱ | نسخه ۲ |
|---|---|---|
| آستانه | ۵۵٪ در کد / ۷۵٪ در مستندات | ۷۵٪ در هر دو، قابل تنظیم |
| معیار تصمیم | `psutil.percent` (شامل کش) | `GlobalMemoryStatusEx` + هدف مطلق |
| تکرار | هر ۶۰ ثانیه، بی‌نهایت | هیسترزیس ۷۵/۶۵ + cooldown + سقف ساعتی + بک‌آف |
| خالی کردن کش | همیشه | فقط اگر بعد از trim هنوز کمبود باشد |
| لیست استثنا | نداشت | پروسه‌های حیاتی، آنتی‌ویروس‌ها و الگوها |
| حالت تمام‌صفحه / باتری / ساعت سکوت | نداشت | دارد |
| گزارش موفقیت | همیشه «انجام شد» | فقط اگر واقعاً کاری شده باشد |
| عدد «آزادشده» | اختلاف «used» (نوسان کش) | کاهش واقعی Working Set + free |
| پیکربندی | ویرایش کد + بیلد مجدد | `config.ini` |
| پس از کرش سرویس | بدون ری‌استارت | سه failure action + delayed start |
| تست و CI | نداشت | ۷۰+ تست، lint، mypy، CI ویندوز و لینوکس |

---

## نصب سریع (exe)

1. **`build_exe.bat`** را دابل‌کلیک کنید (Python 3.9+ باید در PATH باشد).
2. وارد پوشه‌ی **`release`** شوید و **`install_service.bat`** را دابل‌کلیک کنید
   (در پنجره‌ی UAC گزینه‌ی Yes).
3. تمام. سرویس با تأخیر بعد از بوت بالا می‌آید و در صورت کرش خودکار ری‌استارت
   می‌شود.

⚠️ پوشه‌ی `RamOptimizerService` را جابه‌جا یا حذف نکنید؛ exe از همان‌جا اجرا
می‌شود. برای جابه‌جایی: `uninstall_service.bat` → جابه‌جا کردن → `install_service.bat`

### حذف

`uninstall_service.bat` — و اگر خواستید لاگ/تنظیمات هم پاک شود، در همان پنجره
`y` بزنید.

---

## نصب با نصب‌کننده (recommended)

اگر [Inno Setup](https://jrsoftware.org/isinfo.php) نصب دارید:

```bat
build_exe.bat
iscc installer\ramopt.iss
```

خروجی `installer\Output\RamOptimizerService-2.0.0-setup.exe` است و مزیت‌هایش:

- **ارتقا** درست کار می‌کند (سرویس قبلی قبل از کپی فایل‌ها متوقف و حذف می‌شود)
- حذف کامل: سرویس، منبع Event Log و پوشه‌ی داده‌ها
- سرویس بعد از نصب خودکار نصب و راه‌اندازی می‌شود

---

## اجرا بدون نصب سرویس

```bat
:: یک چرخه‌ی آزمایشی، بدون هیچ تغییری در سیستم (بی‌خطرترین شروع)
RamOptimizerService.exe test --dry-run

:: یک چرخه‌ی واقعی (فقط اگر آستانه رد شده باشد)
RamOptimizerService.exe test

:: اجرای زور (صرف‌نظر از آستانه و cooldown) - برای تست
RamOptimizerService.exe test --force

:: اجرای دائمی در پیش‌زمینه
RamOptimizerService.exe console
```

هر دو دستور باید در **CMD با دسترسی Administrator** اجرا شوند.

---

## پیکربندی

فایل: `C:\ProgramData\RamOptimizer\config.ini` (با `config --init` ساخته
می‌شود؛ اگر نباشد، پیش‌فرض‌های امن استفاده می‌شوند).

```ini
[general]
check_interval_seconds = 60
startup_delay_seconds = 60

[policy]
trigger_percent = 75          ; آستانه‌ی شروع پاک‌سازی
reset_percent = 65            ; تا این درصد، حالت فعال می‌ماند (ضد لرزش)
cooldown_seconds = 300        ; حداقل فاصله بین دو پاک‌سازی
max_purges_per_hour = 6       ; سقف ساعتی (۰ = بی‌نهایت)
min_available_mb = 0          ; اگر این قدر آزاد است، هرگز کاری نکن (۰ = خاموش)

[standby]
purge = true
min_free_mb_after_trim = 512  ; کش فقط اگر بعد از trim هنوز کمتر از این آزاد است
flush_modified_list = false

[targets]
min_process_ws_mb = 20        ; پروسه‌های کوچک‌تر دست نمی‌خورند
max_processes = 64            ; سقف تعداد پروسه در هر دور (۰ = بی‌نهایت)
exclude = dwm.exe, csrss.exe, lsass.exe, explorer.exe, ...
exclude_patterns = msmpeng*, *defender*

[safety]
skip_when_fullscreen = true   ; بازی/ارائه
skip_on_battery = false
quiet_hours =                 ; مثلاً 23:00-06:00

[logging]
level = info                  ; debug | info | warning | error
```

بدون نیاز به بیلد مجدد، بعد از تغییر: `Restart-Service RamOptimizerService`
(یا `RamOptimizerService.exe service restart`).

### تنظیمات پیشنهادی

| سناریو | تنظیم |
|---|---|
| لپ‌تاپ با باتری محدود | `skip_on_battery = true`، `check_interval_seconds = 120` |
| سیستم ۳۲/۶۴ گیگ که «همیشه ۸۰٪ است» | `min_available_mb = 4096` (اصلاً دخالت نکن) |
| سیستم ۸ گیگ با کندی محسوس | `trigger_percent = 80`, `reset_percent = 70`, `cooldown_seconds = 600` |
| گیمر | `skip_when_fullscreen = true` (پیش‌فرض) و `min_process_ws_mb = 200` |
| حداقل دخالت، فقط تمیزکاری | `purge = false` (فقط trim) |

---

## خط فرمان

```
RamOptimizerService.exe version          نسخه، پایتون، مسیر داده‌ها
RamOptimizerService.exe status [--json]  وضعیت فعلی از status.json
RamOptimizerService.exe config --init    ساخت فایل پیکربندی نمونه
RamOptimizerService.exe config --show    نمایش پیکربندی مؤثر
RamOptimizerService.exe config --validate بررسی اعتبار فایل
RamOptimizerService.exe test --dry-run   فقط تصمیم (بدون تغییر سیستم)
RamOptimizerService.exe test --force     اجرای دستی
RamOptimizerService.exe console          اجرای دائمی در پیش‌زمینه
RamOptimizerService.exe service install|remove|start|stop|restart|pause|continue|query|repair
RamOptimizerService.exe log --lines 50   نمایش انتهای لاگ
```

اگر از سورس اجرا می‌کنید، همان دستورها با `python -m ramopt` یا `ramopt` در دسترس‌اند.

---

## پایش و لاگ

| فایل | محتوا |
|---|---|
| `%ProgramData%\RamOptimizer\ram_optimizer.log` | لاگ چرخشی (۲MB × ۳) |
| `%ProgramData%\RamOptimizer\crash.log` | استثناهای کشنده، چرخشی |
| `%ProgramData%\RamOptimizer\status.json` | وضعیت ماشین‌خوان برای پایش |
| `%ProgramData%\RamOptimizer\config.ini` | پیکربندی |

نمونه‌ی `status.json`:

```json
{
  "version": "2.0.0",
  "state": "running",
  "pid": 4212,
  "last_cycle_at": "2026-11-23T12:00:00",
  "last_action": "optimized",
  "last_reason": "آستانه رد شده و محدودیتی نیست",
  "memory": {"used_percent": 81.2, "available_mb": 2450, "commit_percent": 42.0, "standby_mb": 3100},
  "counters": {"purges": 3, "freed_mb": 812.5, "errors": 0, "cycles": 240}
}
```

رویدادها در **Event Viewer → Windows Logs → Application** با Source
`RamOptimizerService` هم ثبت می‌شوند.

---

## نصب از سورس / توسعه

```bash
python -m venv .venv
.venv\Scripts\activate            # ویندوز (لینوکس: source .venv/bin/activate)
pip install -r requirements-dev.txt

pytest -q                          # ۷۰+ تست (بخش ویندوزی روی لینوکس skip می‌شود)
ruff check . && ruff format --check .
mypy ramopt

python -m ramopt test --dry-run    # اجرای برنامه از سورس
python ram_optimizer_service.py service install
```

ساختار پروژه:

```
ramopt/
  config.py         پیکربندی + اعتبارسنجی
  engine.py         سیاست تصمیم‌گیری و اجرا (بدون وابستگی به ویندوز → قابل تست)
  memory.py         اندازه‌گیری و عملیات حافظه
  win32.py          لایه‌ی ctypes (تنها جایی که Win32 صدا زده می‌شود)
  service.py        کلاس سرویس pywin32
  service_admin.py  نصب/حذف/کنترل با failure actions و delayed start
  runner.py         حلقه‌ی مشترک سرویس/کنسول/تسک
  status.py         status.json
  logging_setup.py  لاگ چرخشی + Event Log + crash
  cli.py            خط فرمان
tests/              pytest (FakeApi کامل، بدون نیاز به ویندوز برای سیاست‌ها)
installer/          اسکریپت Inno Setup
.github/workflows/  CI (لینوکس + ویندوز واقعی + بیلد exe)
```

---

## عیب‌یابی

**خطای «The service did not respond to the start or control request in a timely fashion»**

1. `uninstall_service.bat` (پاک کردن نصب قبلی)
2. `build_exe.bat` دوباره (حالت onedir عمداً استفاده می‌شود؛ exe تک‌فایلی این
   خطا را می‌سازد)
3. `install_service.bat`
4. اگر باز هم نشد، در CMD ادمین:
   ```bat
   cd /d "مسیر\release\RamOptimizerService"
   RamOptimizerService.exe console
   ```
   و خطا را از همان خروجی بخوانید؛ فایل‌های `crash.log` و
   `ram_optimizer.log` را هم ببینید.

**سرویس اجراست ولی هیچ کاری نمی‌کند**
- `RamOptimizerService.exe status` → آخرین دلیل در `last_reason` است
  (مثلاً «تأخیر شروع»، «cooldown»، «تمام‌صفحه»).
- `RamOptimizerService.exe test --dry-run` نشان می‌دهد در حال حاضر چه تصمیمی
  گرفته می‌شود و چند پروسه هدف هستند.

**«دسترسی رد شد» در لاگ زیاد است**
سرویس با حساب `LocalSystem` اجرا می‌شود که برای trim کافی است؛ اگر با حساب
محدود اجرا می‌کنید، بخشی از پروسه‌ها پاک نمی‌شوند (در لاگ شمرده می‌شوند).

**آنتی‌ویروس/SmartScreen هشدار داد**
برای exe بدون امضای دیجیتال ساخته‌شده با PyInstaller این هشدار رایج است.
تنها راه واقعی رفع آن [امضای کد](https://learn.microsoft.com/windows/win32/seccrypto/signtool)
است؛ راه‌حل موقت: پوشه را به Exclusion آنتی‌ویروس اضافه کنید یا از سورس اجرا کنید.

**سرویس را کجا ببینم؟** `Win+R` → `services.msc` → **RAM Optimizer Service**

---

## سؤالات متداول

**آیا امن است؟**
بله — فقط از APIهای رسمی ویندوز استفاده می‌کند (`EmptyWorkingSet` و همان
مکانیزم RAMMap). هیچ پروسه‌ای بسته نمی‌شود و هیچ داده‌ای از بین نمی‌رود.
`SeDebugPrivilege` هم عمداً درخواست نمی‌شود.

**چرا حافظه‌ی آزاد بلافاصله بعد از اجرا کم می‌شود؟**
چون کش (standby) دوباره پر می‌شود — این رفتار درست ویندوز است. اگر این ابزار
قرار بود کش را دائم خالی نگه دارد، سیستم عملاً کندتر می‌شد.

**روی سیستم ۶۴ گیگی با ۸۰٪ مصرف کاری نمی‌کند؟**
درست است. اگر `min_available_mb` را تنظیم کنید (مثلاً ۴۰۹۶)، برنامه وقتی RAM
کافی آزاد است دخالت نمی‌کند — حتی اگر درصد بالا باشد.

**تفاوت با Wise Memory Optimizer / RAMMap؟**
همان مکانیزم‌ها، ولی با سیاست محدودشده (cooldown، سقف، لیست استثنا، احترام به
تمام‌صفحه و باتری) و پیکربندی/پایش قابل اتکا.

**مجوز؟** GPLv3 — [LICENSE](LICENSE)
