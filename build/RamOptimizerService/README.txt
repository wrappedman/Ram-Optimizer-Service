این پوشه جای exe است، نه خود exe.
=====================================

exe در git نیست چون هر بیلد ~۱۰ مگابایت است و با هر commit سنگین‌تر می‌شود.
سه راه برای پر کردن این پوشه:

۱) روی ویندوز (ساده‌ترین):
       build\build_exe.bat
   نتیجه مستقیم همین‌جا می‌آید:
       build\RamOptimizerService\RamOptimizerService.exe

۲) از CI (بدون نیاز به Python روی ماشین شما):
       GitHub → Actions → آخرین اجرای سبز → Artifacts →
       RamOptimizerService-windows
   فایل zip را باز کنید و محتوای آن را همین‌جا بریزید. ساختار داخل zip:
       RamOptimizerService/RamOptimizerService.exe
       Manage-RamOptimizer.bat
       RamOptimizerControl.ps1
       build_info.json
       SHA256SUMS.txt

۳) از release/nصب‌کننده:
       build_exe.bat  →  iscc installer\ramopt.iss

بعد از آن:
       build\Manage-RamOptimizer.bat      ← منوی نصب/حذف/وضعیت/لاگ
