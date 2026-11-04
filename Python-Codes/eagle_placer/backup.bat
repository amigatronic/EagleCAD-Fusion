@echo off
:: Genera un timestamp pulito basato su data e ora (es. 20260618_1530)
for /f "tokens=2 delims==" %%I in ('wmic os get localdatetime /value') do set datetime=%%I
set TIMESTAMP=%datetime:~0,4%%datetime:~4,2%%datetime:~6,2%_%datetime:~8,2%%datetime:~10,2%

:: Imposta la destinazione dentro una cartella con la data e ora corrente
set DEST=%~dp0backup\backup_%TIMESTAMP%

if not exist "%DEST%" mkdir "%DEST%"
xcopy /Y /I "%~dp0*.py" "%DEST%"

echo.
echo Copia cronologica completata in: %DEST%
pause