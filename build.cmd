@echo off
rem ============================================================
rem  Rhythm game - one-click build  (charts + song library + skins)
rem
rem  Double-click this file, OR run it from a terminal.
rem
rem  WHAT IT DOES
rem    [1/2] music\Sheet Music Maker.py --missing
rem          Generates a .txt chart for every song folder that has audio
rem          but no chart yet. Folders that already have a chart are left
rem          completely untouched. If nothing is missing it exits right
rem          away - it does not even load librosa, so the common case
rem          costs about 0.6s.
rem          SKIPPED with a warning when no Python 3 is available; only
rem          step 2 runs then. That is fine when you only added a skin,
rem          but a NEW SONG needs a chart, so install Python for songs.
rem    [2/2] build.js
rem          Repacks  music\charts.js                      (song library)
rem          and       role\skins.js + role\palette.js    (skins)
rem
rem  HOW TO ADD A SONG
rem    1) Create a folder under  rhythm\music\  named after the song,
rem       e.g.  rhythm\music\MySong\
rem    2) Drop ONE audio file in it (.mp3 - see NOTE below).
rem       No .txt chart needed; step 1 makes it for you.
rem    3) Double-click THIS file:  rhythm\build.cmd
rem
rem  HOW TO ADD A SKIN
rem    1) Create a folder under  rhythm\role\  (folder name = skin name),
rem       e.g.  rhythm\role\MySkin\
rem    2) Put  Background.png / D.png / R.png / Trailing.png  in it.
rem       Missing images degrade gracefully: no Background -> flat colour,
rem       no D.png -> borrows R.png, no R.png -> borrows D.png.
rem       Trailing.png is the only image ever used for the hold-note trail.
rem       To change the display name / order add  skin.json  in that folder:
rem           { "name": "Display Name", "order": 10 }
rem    3) Double-click THIS file.
rem
rem  NOTE
rem    gen_songs.js only packs .mp3 files, while the chart maker also
rem    accepts .wav/.flac/.m4a/.ogg. So a .wav-only folder would get a
rem    chart but still not appear in the song list - step 1 prints an
rem    explicit warning when it sees that. Use .mp3 to be safe.
rem
rem  Songs and skins already in the library are never modified by this file.
rem  Re-running it is always safe: an existing .txt is updated in place,
rem  never appended.
rem  This file is ASCII-only on purpose (cmd.exe reads it with the OEM code page).
rem ============================================================
setlocal
chcp 65001 >nul

set "MAKER=%~dp0music\Sheet Music Maker.py"
set "RC=0"

rem ---- locate node (required: step 2) ------------------------------------
where node >nul 2>nul
if errorlevel 1 goto NONODE

rem ---- locate a Python 3 interpreter (optional: step 1) ------------------
rem  Order: RHYTHM_PYTHON override  >  py launcher  >  python on PATH.
rem  "py -3" is preferred over a bare "python" because PATH may resolve
rem  "python" to a tool-managed virtualenv that has no librosa/pygame.
rem  Kept as flat labels instead of a "for" or "if" block on purpose: inside a
rem  parenthesised block cmd expands %VAR% at parse time, which is the classic
rem  way an interpreter probe silently picks the wrong one. The command and its
rem  argument live in two variables so a path containing spaces stays quoted.
rem  Python is NOT required for skins, so a missing interpreter is a warning
rem  (goto NOPY_SKIP), not a hard failure.
set "PYCMD="
set "PYARG="
if defined RHYTHM_PYTHON set "PYCMD=%RHYTHM_PYTHON%"
if defined PYCMD goto HAVEPY
where py >nul 2>nul
if errorlevel 1 goto TRY_PYTHON
set "PYCMD=py"
set "PYARG=-3"
goto HAVEPY

:TRY_PYTHON
where python >nul 2>nul
if errorlevel 1 goto NOPY_SKIP
set "PYCMD=python"
goto HAVEPY

:HAVEPY
echo ============================================================
echo  Step 1/2   Charts - generate only what is missing
echo ============================================================
"%PYCMD%" %PYARG% "%MAKER%" --missing
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" goto CHARTFAIL
goto STEP2

:NOPY_SKIP
echo ============================================================
echo  Step 1/2   SKIPPED - no Python 3 interpreter was found
echo ============================================================
echo  Charts will NOT be generated. Existing songs are unaffected,
echo  and step 2 still runs, so SKINS are rebuilt normally.
echo.
echo  But if you just added a NEW SONG it will not show up in the song
echo  list until a chart exists for it. Install Python 3 from
echo  https://python.org, or point this file at an interpreter:
echo.
echo      set RHYTHM_PYTHON=D:\Python313\python.exe
echo.
echo  then run this file again.
echo.

:STEP2
echo ============================================================
echo  Step 2/2   Repack song library + skins
echo ============================================================
node "%~dp0build.js"
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" goto BUILDFAIL

echo.
echo All done.  Open  rhythm\index.html  and reload to see the new song / skin.
echo.
pause
exit /b 0

:CHARTFAIL
echo.
echo [err] Chart generation failed (exit code %RC%).
echo       The song library was NOT rebuilt, and nothing already in the
echo       library was modified.  Fix the problem and run this file again.
echo.
pause
exit /b %RC%

:BUILDFAIL
echo.
echo [err] build.js failed (exit code %RC%).
echo       Charts may already have been generated - fix the problem and
echo       simply run this file again.  It is safe to repeat: an existing
echo       .txt is updated in place, never appended.
echo.
pause
exit /b %RC%

:NONODE
echo.
echo [err] Node.js was not found on PATH.
echo       Install Node.js from https://nodejs.org, or - if it is installed
echo       but just not on PATH - call it explicitly, e.g.:
echo         "<path-to-node>\node.exe" "%~dp0build.js"
echo.
pause
exit /b 1
