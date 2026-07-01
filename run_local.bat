@echo off
chcp 65001 > nul
title Supertonic 시험 방송 시스템 원클릭 자동 실행기

echo ========================================================
echo  Supertonic 시험 시간 자동 안내 방송 시스템 실행기
echo ========================================================
echo.

:: 1. 파이썬 설치 검증
echo [1/3] 파이썬(Python) 설치 여부를 확인하는 중...
where python >nul 2>nul
if %errorlevel% neq 0 (
    echo.
    echo [경고] 컴퓨터에 파이썬이 설치되어 있지 않거나 환경 변수에 등록되지 않았습니다!
    echo 자동으로 파이썬 공식 다운로드 페이지를 열어 드립니다.
    echo 파이썬 설치 시 [Add python.exe to PATH] 옵션을 반드시 체크해 주세요!
    echo.
    pause
    start https://www.python.org/downloads/
    exit
)
echo 파이썬이 정상 확인되었습니다.
echo.

:: 2. 필수 라이브러리 검증 및 자동 설치
echo [2/3] 필수 라이브러리 설치 여부를 점검하는 중...
python -c "import fastapi, supertonic, uvicorn, apscheduler" >nul 2>nul
if %errorlevel% neq 0 (
    echo [안내] 필수 패키지가 없습니다. 자동 설치를 시작합니다. (최초 1회 실행)
    echo (인터넷 연결 속도에 따라 수 분이 소요될 수 있습니다...)
    echo.
    pip install -r requirements.txt
    if %errorlevel% neq 0 (
        echo.
        echo [오류] 라이브러리 자동 설치에 실패했습니다. 인터넷 연결 상태를 확인하고 다시 실행해 주세요.
        pause
        exit
    )
    echo 라이브러리 설치가 성공적으로 완료되었습니다!
) else (
    echo 모든 필수 라이브러리가 이미 설치되어 있습니다.
)
echo.

:: 3. 로컬 서버 실행 및 브라우저 기동
echo [3/3] 시험 방송 시스템 서버를 기동하는 중...
echo.
echo ========================================================
echo  ★ 서버 구동 성공! 이 까만 창을 절대 닫지 마세요.
echo  ★ 이 창이 켜져 있는 동안 방송 시스템이 작동합니다.
echo ========================================================
echo.

:: 기본 웹 브라우저로 로컬 제어판 즉시 연결
start http://localhost:8000

:: uvicorn 서버 실행
python app.py

pause
