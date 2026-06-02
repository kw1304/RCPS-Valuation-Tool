' 부팅 자동시작용 — %APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\ 에 복사.
' pythonw(무콘솔)로 run_server.py 기동. run_server가 stdout None 가드 + .env 로드.
Set sh = CreateObject("WScript.Shell")
sh.CurrentDirectory = "C:\Claude\RISK_TOOL"
sh.Run """C:\Users\admin\AppData\Local\Python\bin\pythonw.exe"" run_server.py", 0, False
