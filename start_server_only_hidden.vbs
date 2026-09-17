' Runs start_server_only.bat completely hidden (no console, no browser) - for autostart
Set sh = CreateObject("WScript.Shell")
sh.Run """C:\Users\20137\quant-dashboard\start_server_only.bat""", 0, False
