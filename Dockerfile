# 1. Base Image 설정 (FastAPI 및 Python 구동용 경량 리눅스)
FROM python:3.12-slim

# 2. 필수 시스템 패키지 설치
# (supertonic TTS 라이브러리의 오디오 저장을 위한 libsndfile1 패키지가 필수적임)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

# 3. 작업 디렉토리 설정
WORKDIR /code

# 4. 의존성 설치
COPY ./requirements.txt /code/requirements.txt
RUN pip install --no-cache-dir --upgrade -r /code/requirements.txt

# 5. 소스 코드 복사
COPY . .

# 6. 오디오 임시 저장 디렉토리 생성 및 권한 설정
RUN mkdir -p /code/audio && chmod 777 /code/audio

# 7. Hugging Face Spaces는 내부적으로 7860 포트를 수신하므로, 7860으로 서버 구동
# (supertonic은 Hugging Face Hub에서 첫 실행 시 모델을 다운받으므로 가상환경 락 방지를 위해 호스트 0.0.0.0 바인딩)
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "7860"]
